import asyncio
import os
from typing import List, Tuple, Optional
import ccxt
from loguru import logger
from .config import (
    START_MODE,
    STRAT_ENABLE,
    DATA_EXCHANGE_ID,
    DATA_IS_TESTNET,
    STRAT_SYMBOLS,
    STRAT_TIMEFRAME,
    STRAT_QTY_USD,
    STRAT_LEVERAGE,
    STRAT_EMA_FAST,
    STRAT_EMA_SLOW,
    STRAT_ATR_LEN,
    STRAT_ATR_MA_LEN,
    STRAT_ATR_MULT,
    STRAT_BREAKOUT_LEN,
    STRAT_VOLMA_LEN,
    STRAT_VOL_MULT,
    CONFIRM_TF,
    HTF_EMA_FAST,
    HTF_EMA_SLOW,
    POSITION_SIZING,
    RISK_USD,
    MIN_BASE_QTY,
    BRACKET_ENABLE,
    BRACKET_TP_RR,
    BRACKET_TP_AS_MARKET,
    BRACKET_WORKING_TYPE,
    STRAT_POLL_SEC,
    STRAT_LOG_EVERY_BAR,
)


def ema_series(vals: List[float], length: int) -> List[float]:
    if length <= 1:
        return vals[:]
    k = 2 / (length + 1)
    out = []
    e = vals[0]
    for v in vals:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


def compute_atr(
    h: List[float], l: List[float], c: List[float], length: int
) -> List[float]:
    trs = []
    prev = c[0]
    for i in range(1, len(c)):
        tr = max(h[i] - l[i], abs(h[i] - prev), abs(l[i] - prev))
        trs.append(tr)
        prev = c[i]
    atr = ema_series(trs, length)
    return [atr[0]] + atr if atr else atr


class StrategyLoop:
    """
    v1: 5m breakout + 1h trend filter + ATR/volume expansion.
    On entry, place reduceOnly bracket (SL/TP) if engine supports it.
    Supports dynamic risk sizing from equity via env toggles.
    """

    def __init__(self, engine):
        self.engine = engine
        self.running = False
        self.last_bar_ts = {}
        self.pos_side = {}
        self.entry_price = {}
        self.sl_price = {}
        self.tp_price = {}
        # data-only client (ccxt)
        self.data_ex = getattr(ccxt, DATA_EXCHANGE_ID)({"enableRateLimit": True})
        try:
            self.data_ex.set_sandbox_mode(DATA_IS_TESTNET)
        except Exception:
            pass
        try:
            self.data_ex.load_markets()
        except Exception:
            pass
        self.symbols = [s.strip() for s in STRAT_SYMBOLS.split(",") if s.strip()]

        # ----- Dynamic risk knobs (from env; safe defaults) -------------------
        # Enable with: RISK_DYNAMIC_ENABLE=1
        # RISK_EQUITY_PCT=0.0075 -> 0.75% of equity per trade (clamped)
        self.risk_dyn_enable = str(os.getenv("RISK_DYNAMIC_ENABLE", "0")).lower() in ("1", "true", "yes", "y", "on")
        self.risk_equity_pct = float(os.getenv("RISK_EQUITY_PCT", "0.0075"))
        self.risk_equity_min = float(os.getenv("RISK_EQUITY_MIN_USD", "5"))
        self.risk_equity_max = float(os.getenv("RISK_EQUITY_MAX_USD", "50"))

        logger.info(
          f"[RISK] dynamic={'ON' if self.risk_dyn_enable else 'OFF'} "
          f"pct={self.risk_equity_pct} min={self.risk_equity_min} max={self.risk_equity_max}"
        )

    # ---- utils ----
    def _get_engine_position_side(self, symbol: str) -> Optional[str]:
        if hasattr(self.engine, "positions"):  # Paper
            pos = getattr(self.engine, "positions", {}).get(symbol)
            if not pos or abs(pos.get("amount", 0.0)) == 0:
                return None
            return "long" if pos["amount"] > 0 else "short"
        if hasattr(self.engine, "_get_position_size"):  # Binance wrapper
            try:
                size = self.engine._get_position_size(symbol)
                if size == 0:
                    return None
                return "long" if size > 0 else "short"
            except Exception:
                return None
        return None

    async def _get_equity_usdt(self) -> Optional[float]:
        """
        Try multiple sources to get USDT equity for USD-M futures:
        1) engine helpers if available
        2) ccxt handle (engine.ex or engine.exchange).fetch_balance()
        3) binance client fallbacks
        """
        # 1) Engine helpers
        for name in ("get_equity", "equity", "get_balance_usdt"):
            if hasattr(self.engine, name):
                try:
                    res = getattr(self.engine, name)()
                    if asyncio.iscoroutine(res):
                        res = await res
                    if isinstance(res, (int, float)):
                        return float(res)
                    if isinstance(res, dict):
                        if "equity" in res:
                            return float(res["equity"])
                        usdt = res.get("USDT") or res.get("usdt")
                        if isinstance(usdt, dict):
                            for k in ("total", "free", "walletBalance", "crossWalletBalance", "equity"):
                                v = usdt.get(k)
                                if v not in (None, "", 0, "0"):
                                    return float(v)
                except Exception as e:
                    logger.warning(f"[RISK] engine.{name}() failed: {e}")

        # 2) ccxt futures balance
        ex = getattr(self.engine, "ex", None) or getattr(self.engine, "exchange", None)
        if ex and hasattr(ex, "fetch_balance"):
            try:
                bal = await asyncio.to_thread(ex.fetch_balance)
                if isinstance(bal, dict):
                    info = bal.get("info") or {}
                    for k in ("totalWalletBalance", "totalCrossWalletBalance", "totalMarginBalance"):
                        val = info.get(k)
                        if val not in (None, "", 0, "0"):
                            return float(val)
                    usdt = bal.get("USDT") or bal.get("usdt")
                    if isinstance(usdt, dict):
                        for k in ("equity", "total", "walletBalance", "crossWalletBalance", "cashBalance", "balance"):
                            val = usdt.get(k)
                            if val not in (None, "", 0, "0"):
                                return float(val)
            except Exception as e:
                logger.warning(f"[RISK] ccxt fetch_balance failed: {e}")

        # 3) binance python client fallback
        client = getattr(self.engine, "client", None)
        for m in ("futures_account", "fapiPrivateV2GetBalance", "fapiPrivateGetBalance"):
            if client and hasattr(client, m):
                try:
                    res = getattr(client, m)()
                    if asyncio.iscoroutine(res):
                        res = await res
                    if isinstance(res, dict):
                        for k in ("totalWalletBalance", "totalCrossWalletBalance", "totalMarginBalance"):
                            v = res.get(k)
                            if v not in (None, "", 0, "0"):
                                return float(v)
                    if isinstance(res, list):
                        for a in res:
                            if a.get("asset") == "USDT":
                                for k in ("balance", "walletBalance", "crossWalletBalance"):
                                    v = a.get(k)
                                    if v not in (None, "", 0, "0"):
                                        return float(v)
                except Exception as e:
                    logger.warning(f"[RISK] binance client {m} failed: {e}")
        return None

    async def _get_dynamic_risk_usd(self) -> Optional[float]:
        """Return dynamic RISK_USD from equity * pct (clamped), or None if disabled/unavailable."""
        if not self.risk_dyn_enable:
            return None
        eq = await self._get_equity_usdt()
        if eq is None:
            logger.warning("[RISK] equity unavailable; fallback to static RISK_USD")
            return None
        risk = float(eq) * float(self.risk_equity_pct)
        risk = max(self.risk_equity_min, min(self.risk_equity_max, risk))  # clamp
        return float(risk)

    def _split(self, ohlcv):
        ts = [r[0] for r in ohlcv]
        o = [r[1] for r in ohlcv]
        h = [r[2] for r in ohlcv]
        l = [r[3] for r in ohlcv]
        c = [r[4] for r in ohlcv]
        v = [r[5] for r in ohlcv]
        return ts, o, h, l, c, v

    def _calc_ltf(self, ohlcv):
        ts, o, h, l, c, v = self._split(ohlcv)
        i = -2
        efast = ema_series(c, STRAT_EMA_FAST)
        eslow = ema_series(c, STRAT_EMA_SLOW)
        atr = compute_atr(h, l, c, STRAT_ATR_LEN)
        atr_ma = sum(atr[-STRAT_ATR_MA_LEN - 1 : -1]) / max(1, STRAT_ATR_MA_LEN)
        vol_ok = (
            v[i]
            > (sum(v[-(STRAT_VOLMA_LEN + 1) : -1]) / max(1, STRAT_VOLMA_LEN))
            * STRAT_VOL_MULT
        )
        hh = max(h[-(STRAT_BREAKOUT_LEN + 1) : -1])
        ll = min(l[-(STRAT_BREAKOUT_LEN + 1) : -1])
        brk_long = c[i] > hh
        brk_short = c[i] < ll
        return {
            "ts": ts[i],
            "close": c[i],
            "atr": atr[i],
            "atr_ma": atr_ma,
            "vol_ok": vol_ok,
            "trend_ltf_long": efast[i] > eslow[i],
            "trend_ltf_short": efast[i] < eslow[i],
            "brk_long": brk_long,
            "brk_short": brk_short,
        }

    def _calc_htf_trend(self, ohlcv_htf):
        ts, o, h, l, c, v = self._split(ohlcv_htf)
        i = -2
        efast = ema_series(c, HTF_EMA_FAST)
        eslow = ema_series(c, HTF_EMA_SLOW)
        return {
            "trend_htf_long": efast[i] > eslow[i],
            "trend_htf_short": efast[i] < eslow[i],
        }

    def _size_position(self, price: float, stop_distance: float, risk_usd: Optional[float] = None) -> float:
        """
        When POSITION_SIZING=RISK:
          size = (risk_usd or RISK_USD) / stop_distance
        Otherwise (FIXED_USD):
          size = STRAT_QTY_USD / price
        """
        if POSITION_SIZING == "RISK":
            if stop_distance <= 0:
                return 0.0
            use_risk = (risk_usd if (risk_usd is not None) else RISK_USD)
            base = use_risk / stop_distance
        else:  # FIXED_USD
            base = STRAT_QTY_USD / max(price, 1e-9)
        return max(base, MIN_BASE_QTY)

    async def _maybe_eval_symbol(self, symbol: str):
        try:
            ltf = self.data_ex.fetch_ohlcv(symbol, timeframe=STRAT_TIMEFRAME, limit=300)
            htf = self.data_ex.fetch_ohlcv(symbol, timeframe=CONFIRM_TF, limit=300)
        except Exception as e:
            logger.warning(f"[DATA]{symbol} fetch_ohlcv failed: {e}")
            return

        l = self._calc_ltf(ltf)
        h = self._calc_htf_trend(htf)

        # closed-bar duplicate guard
        if self.last_bar_ts.get(symbol) == l["ts"]:
            # if flat, cancel leftover reduceOnly orders
            if hasattr(self.engine, "cancel_reduces_if_flat"):
                try:
                    self.engine.cancel_reduces_if_flat(symbol)
                except Exception:
                    pass
            return
        self.last_bar_ts[symbol] = l["ts"]

# --- add: show dynamic risk each new bar (even without entry) ---
if self.risk_dyn_enable and STRAT_LOG_EVERY_BAR:
    try:
        stop_distance_preview = l["atr"] * STRAT_ATR_MULT
        dyn = await self._get_dynamic_risk_usd()
        if dyn is not None and stop_distance_preview > 0:
            est_qty = max(dyn / stop_distance_preview, MIN_BASE_QTY)
            logger.info(
                f"[RISK] {symbol} dyn={dyn:.4f} stop={stop_distance_preview:.6f} est_qty~{est_qty:.6f}"
            )
    except Exception as e:
        logger.warning(f"[RISK] preview failed: {e}")
# --- end add ---

        price = l["close"]
        side_now = self._get_engine_position_side(symbol)

        # entry conditions
        long_ok = (
            h["trend_htf_long"]
            and l["trend_ltf_long"]
            and (l["atr"] > l["atr_ma"])
            and l["vol_ok"]
            and l["brk_long"]
        )
        short_ok = (
            h["trend_htf_short"]
            and l["trend_ltf_short"]
            and (l["atr"] > l["atr_ma"])
            and l["vol_ok"]
            and l["brk_short"]
        )

        # per-bar summary log
        if STRAT_LOG_EVERY_BAR:
            logger.info(
                f"[BAR] {symbol} tf={STRAT_TIMEFRAME} ts={l['ts']} px={price:.4f} "
                f"ATR={l['atr']:.4f}/{l['atr_ma']:.4f} vol_ok={l['vol_ok']} "
                f"LTF(L/S)=({l['trend_ltf_long']}/{l['trend_ltf_short']}) "
                f"HTF(L/S)=({h['trend_htf_long']}/{h['trend_htf_short']}) "
                f"brk(L/S)=({l['brk_long']}/{l['brk_short']}) side_now={side_now} "
                f"setup(L/S)=({long_ok}/{short_ok})"
            )

        # entries / reversals
        if long_ok and side_now != "long":
            if side_now == "short":
                self.engine.close_all(symbol)
            stop_distance = l["atr"] * STRAT_ATR_MULT
            dyn_risk = await self._get_dynamic_risk_usd()
            base_amt = self._size_position(price, stop_distance, risk_usd=dyn_risk)
            self.engine.open_market(symbol, "long", base_amt, leverage=STRAT_LEVERAGE)

            self.entry_price[symbol] = price
            self.sl_price[symbol] = price - stop_distance
            self.tp_price[symbol] = price + stop_distance * BRACKET_TP_RR

            logger.info(
                f"[ENTRY] {symbol} LONG qty={base_amt:.6f} entry~{price:.4f} "
                f"SL={self.sl_price[symbol]:.4f} TP={self.tp_price[symbol]:.4f} "
                f"stop={stop_distance:.4f} risk_used={(dyn_risk if dyn_risk is not None else RISK_USD):.4f} lev={STRAT_LEVERAGE}"
            )

            if BRACKET_ENABLE and hasattr(self.engine, "place_bracket"):
                try:
                    self.engine.place_bracket(
                        symbol,
                        "long",
                        base_amt,
                        self.sl_price[symbol],
                        self.tp_price[symbol],
                        tp_as_market=BRACKET_TP_AS_MARKET,
                        working_type=BRACKET_WORKING_TYPE,
                    )
                    logger.info(
                        f"[BRACKET] {symbol} LONG placed (reduceOnly): SL={self.sl_price[symbol]:.4f}, TP={self.tp_price[symbol]:.4f}"
                    )
                except Exception as e:
                    logger.warning(f"[BRACKET]{symbol} failed: {e}")

        elif short_ok and side_now != "short":
            if side_now == "long":
                self.engine.close_all(symbol)
            stop_distance = l["atr"] * STRAT_ATR_MULT
            dyn_risk = await self._get_dynamic_risk_usd()
            base_amt = self._size_position(price, stop_distance, risk_usd=dyn_risk)
            self.engine.open_market(symbol, "short", base_amt, leverage=STRAT_LEVERAGE)

            self.entry_price[symbol] = price
            self.sl_price[symbol] = price + stop_distance
            self.tp_price[symbol] = price - stop_distance * BRACKET_TP_RR

            logger.info(
                f"[ENTRY] {symbol} SHORT qty={base_amt:.6f} entry~{price:.4f} "
                f"SL={self.sl_price[symbol]:.4f} TP={self.tp_price[symbol]:.4f} "
                f"stop={stop_distance:.4f} risk_used={(dyn_risk if dyn_risk is not None else RISK_USD):.4f} lev={STRAT_LEVERAGE}"
            )

            if BRACKET_ENABLE and hasattr(self.engine, "place_bracket"):
                try:
                    self.engine.place_bracket(
                        symbol,
                        "short",
                        base_amt,
                        self.sl_price[symbol],
                        self.tp_price[symbol],
                        tp_as_market=BRACKET_TP_AS_MARKET,
                        working_type=BRACKET_WORKING_TYPE,
                    )
                    logger.info(
                        f"[BRACKET] {symbol} SHORT placed (reduceOnly): SL={self.sl_price[symbol]:.4f}, TP={self.tp_price[symbol]:.4f}"
                    )
                except Exception as e:
                    logger.warning(f"[BRACKET]{symbol} failed: {e}")
        else:
            if STRAT_LOG_EVERY_BAR:
                reasons = []
                if not (l["atr"] > l["atr_ma"]):
                    reasons.append("no_ATR_exp")
                if not l["vol_ok"]:
                    reasons.append("no_vol")
                if not (l["trend_ltf_long"] or l["trend_ltf_short"]):
                    reasons.append("no_LTF_trend")
                if not (h["trend_htf_long"] or h["trend_htf_short"]):
                    reasons.append("no_HTF_trend")
                if not (l["brk_long"] or l["brk_short"]):
                    reasons.append("no_breakout")
                logger.info(
                    f"[NOENTRY] {symbol} reasons={','.join(reasons) or 'filtered'}"
                )

        # if flat -> clear leftover reduceOnly orders
        if hasattr(self.engine, "cancel_reduces_if_flat"):
            try:
                self.engine.cancel_reduces_if_flat(symbol)
            except Exception:
                pass

    async def run(self):
        self.running = True
        logger.info(
            f"[STRAT v1] symbols={self.symbols} tf={STRAT_TIMEFRAME} htf={CONFIRM_TF} sizing={POSITION_SIZING}"
        )
        while self.running:
            for s in self.symbols:
                await self._maybe_eval_symbol(s)
            await asyncio.sleep(STRAT_POLL_SEC)

    async def stop(self):
        self.running = False

