from loguru import logger
from typing import Dict, Any, Optional
import ccxt

class BinanceUSDMExchange:
    """
    - 시장가 진입
    - 레버리지 설정(best-effort)
    - 포지션 전량 청산
    - 브래킷(손절/익절) reduceOnly 주문 동시 제출 + 포지션 0일 때 잔여 주문 청소
    """
    def __init__(self, api_key: str, api_secret: str, is_testnet: bool = True, default_leverage: int = 5):
        self.exchange = ccxt.binanceusdm({
            "apiKey": api_key,
            "secret": api_secret,
            "options": {"defaultType": "future"},
            "enableRateLimit": True,
        })
        try:
            self.exchange.set_sandbox_mode(is_testnet)
            logger.info(f"[BINANCE] Sandbox: {is_testnet}")
        except Exception as e:
            logger.warning(f"[BINANCE] set_sandbox_mode failed: {e}")
        self.default_leverage = default_leverage
        self.exchange.load_markets()

    def fetch_price(self, symbol: str) -> float:
        return float(self.exchange.fetch_ticker(symbol)["last"])

    def set_leverage(self, symbol: str, leverage: Optional[int]):
        lev = leverage or self.default_leverage
        try:
            self.exchange.set_leverage(lev, symbol)
            logger.info(f"[BINANCE] leverage {symbol} -> {lev}")
        except Exception as e:
            logger.warning(f"[BINANCE] set_leverage failed: {e}")

    def open_market(self, symbol: str, side: str, base_amount: float, leverage: Optional[int]=None) -> Dict[str, Any]:
        side = side.lower()
        order_side = "buy" if side=="long" else "sell"
        self.set_leverage(symbol, leverage)
        order = self.exchange.create_market_order(symbol, order_side, amount=base_amount, params={"reduceOnly": False})
        return {"status":"submitted","exchange_order":order}

    def _get_position_size(self, symbol: str) -> float:
        try:
            positions = self.exchange.fetch_positions([symbol])
        except Exception as e:
            logger.error(f"[BINANCE] fetch_positions failed: {e}")
            return 0.0
        size = 0.0
        for p in positions:
            info = p.get("info", {})
            try:
                amt = float(info.get("positionAmt", 0) or 0)
            except Exception:
                amt = 0.0
            size += amt
        return size

    def close_all(self, symbol: str) -> Dict[str, Any]:
        size = self._get_position_size(symbol)
        if size == 0.0:
            return {"status":"no_position","symbol":symbol}
        side = "sell" if size > 0 else "buy"
        order = self.exchange.create_market_order(symbol, side, amount=abs(size), params={"reduceOnly": True})
        return {"status":"submitted","exchange_order":order}

    # ---- OCO 에뮬: 브래킷 제출 ----
    def place_bracket(self, symbol: str, side: str, amount: float,
                      sl_price: float, tp_price: float,
                      tp_as_market: bool = True,
                      working_type: str = "MARK_PRICE"):
        """
        진입 직후 손절/익절 reduceOnly 주문 2개를 동시에 제출.
        side: 'long' 또는 'short' (현재 포지션 방향)
        """
        exit_side = "sell" if side.lower() == "long" else "buy"
        base_params = {
            "reduceOnly": True,
            "workingType": working_type,  # 'MARK_PRICE' or 'CONTRACT_PRICE'
            "timeInForce": "GTC",
        }
        # 손절: STOP_MARKET
        sl = self.exchange.create_order(
            symbol=symbol,
            type="STOP_MARKET",
            side=exit_side,
            amount=amount,
            params={**base_params, "stopPrice": float(sl_price)}
        )
        # 익절: TP(MARKET or LIMIT)
        if tp_as_market:
            tp = self.exchange.create_order(
                symbol=symbol,
                type="TAKE_PROFIT_MARKET",
                side=exit_side,
                amount=amount,
                params={**base_params, "stopPrice": float(tp_price)}
            )
        else:
            tp = self.exchange.create_order(
                symbol=symbol,
                type="TAKE_PROFIT",
                side=exit_side,
                amount=amount,
                price=float(tp_price),
                params={**base_params, "stopPrice": float(tp_price)}
            )
        return {"sl_id": sl.get("id"), "tp_id": tp.get("id")}

    def cancel_reduces_if_flat(self, symbol: str):
        """포지션이 0이면 남은 reduceOnly 주문들을 정리."""
        size = self._get_position_size(symbol)
        if abs(size) > 0:
            return
        try:
            opens = self.exchange.fetch_open_orders(symbol)
            for o in opens:
                info = o.get("info", {})
                if str(info.get("reduceOnly", info.get("reduce_only", ""))).lower() in ["true","1"]:
                    try:
                        self.exchange.cancel_order(o["id"], symbol)
                    except Exception:
                        pass
        except Exception:
            pass
