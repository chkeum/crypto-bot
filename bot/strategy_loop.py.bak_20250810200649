import asyncio
import os
import json
import time
from pathlib import Path
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

# ---------------- math helpers ----------------
def ema_series(vals: List[float], length: int) -> List[float]:
    if not vals:
        return []
    if length <= 1:
        return vals[:]
    k = 2 / (length + 1)
    out = []
    e = vals[0]
    for v in vals:
        e = v * k + e * (1 - k)
        out.append(e)
    return out

def compute_atr(h: List[float], l: List[float], c: List[float], length: int) -> List[float]:
    if not c:
        return []
    trs = []
    prev = c[0]
    for i in range(1, len(c)):
        tr = max(h[i] - l[i], abs(h[i] - prev), abs(l[i] - prev))
        trs.append(tr)
        prev = c[i]
    atr = ema_series(trs, length)
    return [atr[0]] + atr if atr else atr

# ------------------------------------------------
class StrategyLoop:
    """
    v1: 5m breakout + 1h trend filter + ATR/volume expansion.
    On entry:
      - market entry (engine.open_market)
      - optional reduceOnly bracket (SL/TP) (engine.place_bracket)
      - store a "bot tag" so restore can later rebuild SL/TP ONLY for bot-made positions.

    Also supports:
      - Dynamic risk sizing from equity or free balance (env)
      - Margin availability check with auto shrink/skip (env)
    """

    def __init__(self, engine):
        self.engine = engine
        self.running = False
        self.last_bar_ts = {}
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

        # ----- Dynamic risk knobs (from env) -----
        self.risk_dyn_enable = str(os.getenv("RISK_DYNAMIC_ENABLE", "0")).lower() in ("1","true","yes","y","on")
        self.risk_use_free   = str(os.getenv("RISK_USE_FREE", "0")).lower() in ("1","true","yes","y","on")  # use FREE instead of EQUITY
        self.risk_equity_pct = float(os.getenv("RISK_EQUITY_PCT", "0.0075"))
        self.risk_equity_min = float(os.getenv("RISK_EQUITY_MIN_USD", "5"))
        self.risk_equity_max = float(os.getenv("RISK_EQUITY_MAX_USD", "50"))
        logger.info(
            f"[RISK] dynamic={'ON' if self.risk_dyn_enable else 'OFF'} "
            f"source={'FREE' if self.risk_use_free else 'EQUITY'} "
            f"pct={self.risk_equity_pct} min={self.risk_equity_min} max={self.risk_equity_max}"
        )

        # ----- Margin check knobs -----
        self.margin_check_enable = str(os.getenv("MARGIN_CHECK_ENABLE", "0")).lower() in ("1","true","yes","y","on")
        self.margin_adjust_mode  = os.getenv("MARGIN_ADJUST_MODE", "shrink").lower()  # shrink|skip
        self.margin_fee_buffer   = float(os.getenv("MARGIN_FEE_BUFFER", "0.001"))
        logger.info(f"[MARGIN] check={'ON' if self.margin_check_enable else 'OFF'} mode={self.margin_adjust_mode} fee_buf={self.margin_fee_buffer}")

        # ----- Bot tag file (shared with restore) -----
        self.tag_file = os.getenv("RESTORE_TAG_FILE", str((Path(__file__).resolve().parents[1] / "state" / "bot_positions.json")))
        self._ensure_tag_dir()

    # -------------- tag helpers --------------
    def _ensure_tag_dir(self) -> None:
        try:
            Path(self.tag_file).parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    def _load_tags(self) -> dict:
        p = Path(self.tag_file)
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8") or "{}")
        except Exception:
            return {}

    def _save_tags(self, tags: dict) -> None:
        p = Path(self.tag_file)
        tmp = p.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(tags, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            tmp.replace(p)
        except Exception as e:
            logger.warning(f"[TAG] save failed: {e}")

    async def _record_bot_tag(self, symbol: str, side: str, qty: float, entry: float, sl: float, tp: float, stop_distance: float) -> None:
        def _update():
            tags = self._load_tags()
            tags[symbol] = {
                "ts": int(time.time() * 1000),
                "side": side,
                "qty": float(qty),
                "entry": float(entry),
                "sl": float(sl),
                "tp": float(tp),
                "stop_distance": float(stop_distance),
            }
            self._save_tags(tags)
        await asyncio.to_thread(_update)

    # -------------- engine helpers --------------
    def _get_engine_position_side(self, symbol: str) -> Optional[str]:
        # Paper mode
        if hasattr(self.engine, "positions"):
            pos = getattr(self.engine, "positions", {}).get(symbol)
            if not pos or abs(pos.get("amount", 0.0)) == 0:
                return None
            return "long" if pos["amount"] > 0 else "short"
        # Binance wrapper
        if hasattr(self.engine, "_get_position_size"):
            try:
                size = self.engine._get_position_size(symbol)
                if size == 0:
                    return None
                return "long" if size > 0 else "short"
            except Exception:
                return None
        return None

    async def _get_equity_usdt(self) -> Optional[float]:
        # engine helpers
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
                            for k in ("total","free","walletBalance","crossWalletBalance","equity"):
                                v = usdt.get(k)
                                if v not in (None, "", 0, "0"):
                                    return float(v)
                except Exception as e:
                    logger.warning(f"[RISK] engine.{name}() failed: {e}")
        # ccxt
        ex = getattr(self.engine, "ex", None) or getattr(self.engine, "exchange", None)
        if ex and hasattr(ex, "fetch_balance"):
            try:
                bal = await asyncio.to_thread(ex.fetch_balance)
                if isinstance(bal, dict):
                    info = bal.get("info") or {}
                    for k in ("totalWalletBalance","totalCrossWalletBalance","totalMarginBalance"):
                        val = info.get(k)
                        if val not in (None,"",0,"0"):
                            return float(val)
                    usdt = bal.get("USDT") or bal.get("usdt")
                    if isinstance(usdt, dict):
                        for k in ("equity","total","walletBalance","crossWalletBalance","cashBalance","balance"):
                            val = usdt.get(k)
                            if val not in (None,"",0,"0"):
                                return float(val)
            except Exception as e:
                logger.warning(f"[RISK] ccxt fetch_balance failed: {e}")
        # binance client fallback
        client = getattr(self.engine, "client", None)
        for m in ("futures_account","fapiPrivateV2GetBalance","fapiPrivateGetBalance"):
            if client and hasattr(client, m):
                try:
                    res = getattr(client, m)()
                    if asyncio.iscoroutine(res):
                        res = await res
                    if isinstance(res, dict):
                        for k in ("totalWalletBalance","totalCrossWalletBalance","totalMarginBalance"):
                            v = res.get(k)
                            if v not in (None,"",0,"0"):
                                return float(v)
                    if isinstance(res, list):
                        for a in res:
                            if a.get("asset") == "USDT":
                                for k in ("balance","walletBalance","crossWalletBalance"):
                                    v = a.get(k)
                                    if v not in (None,"",0,"0"):
                                        return float(v)
                except Exception as e:
                    logger.warning(f"[RISK] binance client {m} failed: {e}")
        return None

    async def _get_free_usdt(self) -> Optional[float]:
        # engine helpers
        for name in ("get_available_usdt","get_free_usdt","available_usdt"):
            if hasattr(self.engine, name):
                try:
                    res = getattr(self.engine, name)()
                    if asyncio.iscoroutine(res):
                        res = await res
                    if isinstance(res, (int,float)):
                        return float(res)
                    if isinstance(res, dict):
                        usdt = res.get("USDT") or res.get("usdt")
                        if isinstance(usdt, dict):
                            for k in ("free","availableBalance","availableMargin"):
                                v = usdt.get(k)
                                if v not in (None,"",0,"0"):
                                    return float(v)
                except Exception as e:
                    logger.warning(f"[MARGIN] engine.{name}() failed: {e}")
        # ccxt
        ex = getattr(self.engine, "ex", None) or getattr(self.engine, "exchange", None)
        if ex and hasattr(ex, "fetch_balance"):
            try:
                bal = await asyncio.to_thread(ex.fetch_balance)
                if isinstance(bal, dict):
                    usdt = bal.get("USDT") or bal.get("usdt")
                    if isinstance(usdt, dict):
                        for k in ("free","availableBalance","availableMargin"):
                            v = usdt.get(k)
                            if v not in (None,"",0,"0"):
                                return float(v)
                    info = bal.get("info") or {}
                    for k in ("availableBalance","totalAvailableBalance"):
                        v = info.get(k)
                        if v not in (None,"",0,"0"):
                            return float(v)
            except Exception as e:
                logger.warning(f"[MARGIN] ccxt fetch_balance failed: {e}")
        # binance client
        client = getattr(self.engine, "client", None)
        for m in ("futures_account","fapiPrivateV2GetBalance","fapiPrivateGetBalance"):
            if client and hasattr(client, m):
                try:
                    res = getattr(client, m)()
                    if asyncio.iscoroutine(res):
                        res = await res
                    if isinstance(res, dict):
                        v = res.get("availableBalance")
                        if v not in (None,"",0,"0"):
                            return float(v)
                        assets = res.get("assets")
                        if isinstance(assets, list):
                            for a in assets:
                                if a.get("asset") == "USDT":
                                    v = a.get("availableBalance") or a.get("walletBalance")
                                    if v not in (None,"",0,"0"):
                                        return float(v)
                    if isinstance(res, list):
                        for a in res:
                            if a.get("asset") == "USDT":
                                v = a.get("availableBalance") or a.get("balance")
                                if v not in (None,"",0,"0"):
                                    return float(v)
                except Exception as e:
                    logger.warning(f"[MARGIN] binance client {m} failed: {e}")
        return None

    async def _get_dynamic_risk_usd(self) -> Optional[float]:
        if not self.risk_dyn_enable:
            return None
        src = await (self._get_free_usdt() if self.risk_use_free else self._get_equity_usdt())
        if src is None:
            logger.warning("[RISK] equity/free unavailable; fallback to static RISK_USD")
            return None
        risk = float(src) * float(self.risk_equity_pct)
        risk = max(self.risk_equity_min, min(self.risk_equity_max, risk))
        return float(risk)

    # ---------------- core calc helpers ----------------
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
        vol_ok = v[i] > (sum(v[-(STRAT_VOLMA_LEN + 1) : -1]) / max(1, STRAT_VOLMA_LEN)) * STRAT_VOL_MULT
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
        return {"trend_htf_long": efast[i] > eslow[i], "trend_htf_short": efast[i] < eslow[i]}

    def _size_position(self, price: float, stop_distance: float, risk_usd: Optional[float] = None) -> float:
        if POSITION_SIZING == "RISK":
            if stop_distance <= 0:
                return 0.0
            use_risk = (risk_usd if (risk_usd is not None) else RISK_USD)
            base = use_risk / stop_distance
        else:  # FIXED_USD
            base = STRAT_QTY_USD / max(price, 1e-9)
        return max(base, MIN_BASE_QTY)

    # ---------------- main loop ----------------
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
            if hasattr(self.engine, "cancel_reduces_if_flat"):
                try:
                    self.engine.cancel_reduces_if_flat(symbol)
                except Exception:
                    pass
            return
        self.last_bar_ts[symbol] = l["ts"]

        # preview dynamic risk every closed bar
        if self.risk_dyn_enable and STRAT_LOG_EVERY_BAR:
            try:
                stop_preview = l["atr"] * STRAT_ATR_MULT
                dyn = await self._get_dynamic_risk_usd()
                if dyn is not None and stop_preview > 0:
                    est_qty = max(dyn / stop_preview, MIN_BASE_QTY)
                    logger.info(f"[RISK] {symbol} dyn={dyn:.4f} stop={stop_preview:.6f} est_qty~{est_qty:.6f}")
            except Exception as e:
                logger.warning(f"[RISK] preview failed: {e}")

        price = l["close"]
        side_now = self._get_engine_position_side(symbol)

        long_ok = (h["trend_htf_long"] and l["trend_ltf_long"] and (l["atr"] > l["atr_ma"]) and l["vol_ok"] and l["brk_long"])
        short_ok = (h["trend_htf_short"] and l["trend_ltf_short"] and (l["atr"] > l["atr_ma"]) and l["vol_ok"] and l["brk_short"])

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

            # margin check & auto adjust
            qty = base_amt
            if self.margin_check_enable:
                free = await self._get_free_usdt()
                if free is not None:
                    need = (price * qty) / max(STRAT_LEVERAGE, 1e-9) * (1.0 + self.margin_fee_buffer)
                    if free < need:
                        if self.margin_adjust_mode == "shrink":
                            cap = (free / (price * (1.0 + self.margin_fee_buffer))) * max(STRAT_LEVERAGE, 1e-9)
                            if cap < MIN_BASE_QTY:
                                logger.warning(f"[MARGIN] insufficient free={free:.4f} need~{need:.4f} -> skip entry")
                                return
                            qty = max(MIN_BASE_QTY, min(qty, cap))
                            logger.warning(f"[MARGIN] insufficient free={free:.4f} need~{need:.4f} -> shrink qty to {qty:.6f}")
                        else:
                            logger.warning(f"[MARGIN] insufficient free={free:.4f} need~{need:.4f} -> skip entry")
                            return

            try:
                self.engine.open_market(symbol, "long", qty, leverage=STRAT_LEVERAGE)
            except Exception as e:
                logger.error(f"[ENTRY] {symbol} LONG failed: {e}")
                return

            self.entry_price[symbol] = price
            self.sl_price[symbol] = price - stop_distance
            self.tp_price[symbol] = price + stop_distance * BRACKET_TP_RR

            logger.info(
                f"[ENTRY] {symbol} LONG qty={qty:.6f} entry~{price:.4f} "
                f"SL={self.sl_price[symbol]:.4f} TP={self.tp_price[symbol]:.4f} "
                f"stop={stop_distance:.4f} risk_used={(dyn_risk if dyn_risk is not None else RISK_USD):.4f} lev={STRAT_LEVERAGE}"
            )

            # place bracket (reduceOnly) + store bot tag
            if BRACKET_ENABLE and hasattr(self.engine, "place_bracket"):
                try:
                    self.engine.place_bracket(
                        symbol, "long", qty, self.sl_price[symbol], self.tp_price[symbol],
                        tp_as_market=BRACKET_TP_AS_MARKET, working_type=BRACKET_WORKING_TYPE,
                    )
                    logger.info(f"[BRACKET] {symbol} LONG placed (reduceOnly): SL={self.sl_price[symbol]:.4f}, TP={self.tp_price[symbol]:.4f}")
                except Exception as e:
                    logger.warning(f"[BRACKET]{symbol} failed: {e}")

            await self._record_bot_tag(symbol, "long", qty, price, self.sl_price[symbol], self.tp_price[symbol], stop_distance)

        elif short_ok and side_now != "short":
            if side_now == "long":
                self.engine.close_all(symbol)
            stop_distance = l["atr"] * STRAT_ATR_MULT
            dyn_risk = await self._get_dynamic_risk_usd()
            base_amt = self._size_position(price, stop_distance, risk_usd=dyn_risk)

            # margin check & auto adjust
            qty = base_amt
            if self.margin_check_enable:
                free = await self._get_free_usdt()
                if free is not None:
                    need = (price * qty) / max(STRAT_LEVERAGE, 1e-9) * (1.0 + self.margin_fee_buffer)
                    if free < need:
                        if self.margin_adjust_mode == "shrink":
                            cap = (free / (price * (1.0 + self.margin_fee_buffer))) * max(STRAT_LEVERAGE, 1e-9)
                            if cap < MIN_BASE_QTY:
                                logger.warning(f"[MARGIN] insufficient free={free:.4f} need~{need:.4f} -> skip entry")
                                return
                            qty = max(MIN_BASE_QTY, min(qty, cap))
                            logger.warning(f"[MARGIN] insufficient free={free:.4f} need~{need:.4f} -> shrink qty to {qty:.6f}")
                        else:
                            logger.warning(f"[MARGIN] insufficient free={free:.4f} need~{need:.4f} -> skip entry")
                            return

            try:
                self.engine.open_market(symbol, "short", qty, leverage=STRAT_LEVERAGE)
            except Exception as e:
                logger.error(f"[ENTRY] {symbol} SHORT failed: {e}")
                return

            self.entry_price[symbol] = price
            self.sl_price[symbol] = price + stop_distance
            self.tp_price[symbol] = price - stop_distance * BRACKET_TP_RR

            logger.info(
                f"[ENTRY] {symbol} SHORT qty={qty:.6f} entry~{price:.4f} "
                f"SL={self.sl_price[symbol]:.4f} TP={self.tp_price[symbol]:.4f} "
                f"stop={stop_distance:.4f} risk_used={(dyn_risk if dyn_risk is not None else RISK_USD):.4f} lev={STRAT_LEVERAGE}"
            )

            if BRACKET_ENABLE and hasattr(self.engine, "place_bracket"):
                try:
                    self.engine.place_bracket(
                        symbol, "short", qty, self.sl_price[symbol], self.tp_price[symbol],
                        tp_as_market=BRACKET_TP_AS_MARKET, working_type=BRACKET_WORKING_TYPE,
                    )
                    logger.info(f"[BRACKET] {symbol} SHORT placed (reduceOnly): SL={self.sl_price[symbol]:.4f}, TP={self.tp_price[symbol]:.4f}")
                except Exception as e:
                    logger.warning(f"[BRACKET]{symbol} failed: {e}")

            await self._record_bot_tag(symbol, "short", qty, price, self.sl_price[symbol], self.tp_price[symbol], stop_distance)

        else:
            if STRAT_LOG_EVERY_BAR:
                reasons = []
                if not (l["atr"] > l["atr_ma"]): reasons.append("no_ATR_exp")
                if not l["vol_ok"]: reasons.append("no_vol")
                if not (l["brk_long"] or l["brk_short"]): reasons.append("no_breakout")
                if not (h["trend_htf_long"] or h["trend_htf_short"]): reasons.append("no_HTF_trend")
                if not (l["trend_ltf_long"] or l["trend_ltf_short"]): reasons.append("no_LTF_trend")
                logger.info(f"[NOENTRY] {symbol} reasons={','.join(reasons) or 'filtered'}")

        # if flat -> clear leftover reduceOnly
        if hasattr(self.engine, "cancel_reduces_if_flat"):
            try:
                self.engine.cancel_reduces_if_flat(symbol)
            except Exception:
                pass

    async def run(self):
        self.running = True
        logger.info(f"[STRAT v1] symbols={self.symbols} tf={STRAT_TIMEFRAME} htf={CONFIRM_TF} sizing={POSITION_SIZING}")
        while self.running:
            for s in self.symbols:
                await self._maybe_eval_symbol(s)
            await asyncio.sleep(STRAT_POLL_SEC)

    def stop(self):
        self.running = False

