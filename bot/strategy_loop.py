import asyncio
from typing import List, Optional
import ccxt
from loguru import logger
from .config import (
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
    v1: 5m 돌파 + 1h 추세 필터 + ATR/볼륨 확장.
    진입 시 STOP_MARKET(손절) + TP(MARKET) 브래킷 제출.
    매 봉마다 판단 요약 로그(옵션) 출력.
    """

    def __init__(self, engine):
        self.engine = engine
        self.running = False
        self.last_bar_ts = {}
        self.pos_side = {}
        self.entry_price = {}
        self.sl_price = {}
        self.tp_price = {}
        # 데이터 전용 클라이언트
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

    # ---- utils ----
    def _get_engine_position_side(self, symbol: str) -> Optional[str]:
        if hasattr(self.engine, "positions"):  # Paper
            pos = getattr(self.engine, "positions", {}).get(symbol)
            if not pos or abs(pos.get("amount", 0.0)) == 0:
                return None
            return "long" if pos["amount"] > 0 else "short"
        if hasattr(self.engine, "_get_position_size"):  # Binance
            try:
                size = self.engine._get_position_size(symbol)
                if size == 0:
                    return None
                return "long" if size > 0 else "short"
            except Exception:
                return None
        return None

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

    def _size_position(self, price: float, stop_distance: float) -> float:
        if POSITION_SIZING == "RISK":
            if stop_distance <= 0:
                return 0.0
            base = RISK_USD / stop_distance
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

        # 닫힌 봉(ts) 중복 체크
        if self.last_bar_ts.get(symbol) == l["ts"]:
            # 포지션 0이면 잔여 reduceOnly 주문 정리
            if hasattr(self.engine, "cancel_reduces_if_flat"):
                try:
                    self.engine.cancel_reduces_if_flat(symbol)
                except Exception:
                    pass
            return
        self.last_bar_ts[symbol] = l["ts"]

        price = l["close"]
        side_now = self._get_engine_position_side(symbol)

        # 조건 계산
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

        # --- 매 봉 요약 로그(옵션) ---
        if STRAT_LOG_EVERY_BAR:
            logger.info(
                f"[BAR] {symbol} tf={STRAT_TIMEFRAME} ts={l['ts']} px={price:.4f} "
                f"ATR={l['atr']:.4f}/{l['atr_ma']:.4f} vol_ok={l['vol_ok']} "
                f"LTF(L/S)=({l['trend_ltf_long']}/{l['trend_ltf_short']}) "
                f"HTF(L/S)=({h['trend_htf_long']}/{h['trend_htf_short']}) "
                f"brk(L/S)=({l['brk_long']}/{l['brk_short']}) side_now={side_now} "
                f"setup(L/S)=({long_ok}/{short_ok})"
            )

        # 진입/전환
        if long_ok and side_now != "long":
            if side_now == "short":
                self.engine.close_all(symbol)
            stop_distance = l["atr"] * STRAT_ATR_MULT
            base_amt = self._size_position(price, stop_distance)
            self.engine.open_market(symbol, "long", base_amt, leverage=STRAT_LEVERAGE)

            self.entry_price[symbol] = price
            self.sl_price[symbol] = price - stop_distance
            self.tp_price[symbol] = price + stop_distance * BRACKET_TP_RR

            logger.info(
                f"[ENTRY] {symbol} LONG qty={base_amt:.6f} entry~{price:.4f} SL={self.sl_price[symbol]:.4f} TP={self.tp_price[symbol]:.4f} stop={stop_distance:.4f}"
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
            base_amt = self._size_position(price, stop_distance)
            self.engine.open_market(symbol, "short", base_amt, leverage=STRAT_LEVERAGE)

            self.entry_price[symbol] = price
            self.sl_price[symbol] = price + stop_distance
            self.tp_price[symbol] = price - stop_distance * BRACKET_TP_RR

            logger.info(
                f"[ENTRY] {symbol} SHORT qty={base_amt:.6f} entry~{price:.4f} SL={self.sl_price[symbol]:.4f} TP={self.tp_price[symbol]:.4f} stop={stop_distance:.4f}"
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
            # 진입 안 할 때 이유 요약(옵션)
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

        # 포지션 0이면 잔여 reduceOnly 주문 정리
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
