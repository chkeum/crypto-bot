from loguru import logger
from typing import Dict, Any, Optional, Tuple
import ccxt


class BinanceUSDMExchange:
    """
    Binance USDT-M Futures wrapper.

    - ccxt client at `self.exchange` (alias `self.ex` for other modules)
    - Robust position helpers used by restore/bootstrap
    - Market open/close + reduceOnly bracket helpers
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        is_testnet: bool = True,
        default_leverage: int = 5,
    ):
        self.exchange = ccxt.binanceusdm(
            {
                "apiKey": api_key,
                "secret": api_secret,
                "options": {"defaultType": "future"},
                "enableRateLimit": True,
            }
        )
        self.ex = self.exchange  # alias for compatibility
        try:
            self.exchange.set_sandbox_mode(bool(is_testnet))
        except Exception:
            pass
        try:
            self.exchange.load_markets()
        except Exception:
            pass
        self.default_leverage = int(default_leverage or 1)
        logger.info(f"[BINANCE] Sandbox: {bool(is_testnet)}")

    # -------- position helpers ----------
    def get_position_detail(
        self, symbol: str
    ) -> Tuple[Optional[str], float, Optional[float]]:
        """
        Returns (side in {'long','short',None}, abs_size, entry_price_or_None)
        """
        try:
            positions = self.exchange.fetch_positions()
        except Exception as e:
            logger.warning(f"[BINANCE]{symbol} fetch_positions(all) failed: {e}")
            return None, 0.0, None

        target = None
        for p in positions or []:
            try:
                contracts = float(p.get("contracts") or 0.0)
            except Exception:
                contracts = 0.0
            if p.get("symbol") == symbol and abs(contracts) > 0:
                target = p
                break

        if not target:
            try:
                m = self.exchange.market(symbol)
                mid = m.get("id")
                for p in positions or []:
                    info = p.get("info") or {}
                    try:
                        contracts = float(p.get("contracts") or 0.0)
                    except Exception:
                        contracts = 0.0
                    if info.get("symbol") == mid and abs(contracts) > 0:
                        target = p
                        break
            except Exception:
                pass

        if not target:
            return None, 0.0, None

        amt = float(target.get("contracts") or 0.0)
        side = target.get("side") or (
            "long" if amt > 0 else ("short" if amt < 0 else None)
        )
        try:
            entry = float(target.get("entryPrice") or 0.0) or None
        except Exception:
            entry = None
        return side, abs(amt), entry

    def _get_position_size(self, symbol: str) -> float:
        _, size, _ = self.get_position_detail(symbol)
        return float(size or 0.0)

    # -------- leverage & orders ----------
    def set_leverage(self, symbol: str, leverage: Optional[int] = None) -> None:
        lev = int(leverage or self.default_leverage or 1)
        try:
            m = self.exchange.market(symbol)
            self.exchange.set_leverage(
                lev, symbol, params={"marginMode": m.get("marginMode", "cross")}
            )
        except Exception as e:
            logger.warning(f"[BINANCE] set_leverage failed: {e}")

    def open_market(
        self, symbol: str, side: str, amount: float, leverage: Optional[int] = None
    ) -> Dict[str, Any]:
        side = side.lower()
        order_side = "buy" if side == "long" else "sell"
        self.set_leverage(symbol, leverage)
        order = self.exchange.create_market_order(
            symbol, order_side, amount=amount, params={"reduceOnly": False}
        )
        return {"status": "submitted", "exchange_order": order}

    def close_all(self, symbol: str) -> Dict[str, Any]:
        size = self._get_position_size(symbol)
        if abs(size) <= 0:
            return {"status": "no_position", "symbol": symbol}
        exit_side = "sell" if size > 0 else "buy"
        try:
            order = self.exchange.create_market_order(
                symbol, exit_side, amount=abs(size), params={"reduceOnly": True}
            )
            return {"status": "submitted", "exchange_order": order}
        except Exception as e:
            logger.error(f"[BINANCE] close_all failed: {e}")
            return {"status": "error", "error": str(e)}

    # -------- reduceOnly bracket ----------
    def place_bracket(
        self,
        symbol: str,
        side: str,
        amount: float,
        sl_price: Optional[float],
        tp_price: Optional[float],
        tp_as_market: bool = True,
        working_type: str = "CONTRACT_PRICE",
    ) -> Dict[str, Any]:
        """
        Submit reduceOnly SL/TP orders. Use market variants by default for reliability.
        """
        side = side.lower()
        if not sl_price and not tp_price:
            return {"status": "skipped", "reason": "no sl/tp"}

        exit_side = "sell" if side == "long" else "buy"
        base_params = {"reduceOnly": True, "workingType": working_type}
        res: Dict[str, Any] = {"status": "ok"}

        try:
            if sl_price:
                sl = self.exchange.create_order(
                    symbol=symbol,
                    type="STOP_MARKET",
                    side=exit_side,
                    amount=amount,
                    params={**base_params, "stopPrice": float(sl_price)},
                )
                res["sl"] = sl
            if tp_price:
                if tp_as_market:
                    tp = self.exchange.create_order(
                        symbol=symbol,
                        type="TAKE_PROFIT_MARKET",
                        side=exit_side,
                        amount=amount,
                        params={**base_params, "stopPrice": float(tp_price)},
                    )
                else:
                    tp = self.exchange.create_order(
                        symbol=symbol,
                        type="TAKE_PROFIT",
                        side=exit_side,
                        amount=amount,
                        price=float(tp_price),
                        params={**base_params, "stopPrice": float(tp_price)},
                    )
                res["tp"] = tp
        except Exception as e:
            logger.warning(f"[BINANCE]{symbol} place_bracket failed: {e}")
            res["status"] = "error"
            res["error"] = str(e)
        return res

    def cancel_reduces_if_flat(self, symbol: str) -> None:
        """When flat, cancel stray reduceOnly orders."""
        size = self._get_position_size(symbol)
        if abs(size) > 0:
            return
        try:
            opens = self.exchange.fetch_open_orders(symbol)
            for o in opens or []:
                info = o.get("info", {})
                ro = str(
                    info.get("reduceOnly", info.get("reduce_only", ""))
                ).lower() in ("true", "1")
                if ro:
                    try:
                        self.exchange.cancel_order(o["id"], symbol)
                    except Exception:
                        pass
        except Exception:
            pass
