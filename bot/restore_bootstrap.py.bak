from __future__ import annotations
from typing import Optional, Tuple
from loguru import logger

try:
    from .config import (
        STRAT_RESTORE_ON_START,
        BRACKET_REPAIR_ON_START,
        RESTORE_LOG_SUMMARY,
        STRAT_TIMEFRAME, STRAT_ATR_LEN, STRAT_ATR_MULT,
        BRACKET_TP_RR, BRACKET_WORKING_TYPE, BRACKET_TP_AS_MARKET,
    )
except Exception:
    STRAT_RESTORE_ON_START = True
    BRACKET_REPAIR_ON_START = True
    RESTORE_LOG_SUMMARY = True
    STRAT_TIMEFRAME = "5m"
    STRAT_ATR_LEN = 14
    STRAT_ATR_MULT = 2.0
    BRACKET_TP_RR = 1.5
    BRACKET_WORKING_TYPE = "MARK_PRICE"
    BRACKET_TP_AS_MARKET = True

def _compute_atr(high, low, close, length: int) -> float:
    n = len(close)
    if n < max(length + 2, 20):
        return 0.0
    trs = []
    for i in range(1, n):
        h, l, pc = float(high[i]), float(low[i]), float(close[i-1])
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    return sum(trs[-length:]) / float(length)

def enable_restore_on_start():
    from .strategy_loop import StrategyLoop
    if getattr(StrategyLoop, "_restore_patched", False):
        return
    orig_init = StrategyLoop.__init__
    def patched_init(self, *args, **kwargs):
        orig_init(self, *args, **kwargs)
        try:
            if STRAT_RESTORE_ON_START:
                _restore_on_start(self)
        except Exception as e:
            logger.warning(f"[RESTORE] failed on start: {e}")
    StrategyLoop.__init__ = patched_init
    StrategyLoop._restore_patched = True
    logger.info("[RESTORE] bootstrap enabled")

def _restore_on_start(loop) -> None:
    engine = getattr(loop, "engine", None)
    data_ex = getattr(loop, "data_ex", None)
    symbols = getattr(loop, "symbols", [])
    if not engine or not data_ex or not symbols:
        logger.info("[RESTORE] missing engine/data_ex/symbols; skip.")
        return
    for sym in symbols:
        side, size, entry = _get_position_detail(engine, sym)
        if not side or size == 0:
            if RESTORE_LOG_SUMMARY:
                logger.info(f"[RESTORE]{sym} no position; nothing to restore.")
            if hasattr(engine, "cancel_reduces_if_flat"):
                try: engine.cancel_reduces_if_flat(sym)
                except Exception: pass
            continue
        loop.pos_side[sym] = side
        loop.entry_price[sym] = entry
        cur_sl, cur_tp = _get_reduce_only_orders(engine, sym)
        def _px(o):
            if not o: return None
            try: return float(o.get("stopPrice") or o.get("triggerPrice") or 0.0) or None
            except Exception: return None
        loop.sl_price[sym] = _px(cur_sl)
        loop.tp_price[sym] = _px(cur_tp)
        if BRACKET_REPAIR_ON_START and (loop.sl_price[sym] is None or loop.tp_price[sym] is None):
            try:
                ohlcv = data_ex.fetch_ohlcv(sym, timeframe=STRAT_TIMEFRAME, limit=300)
                ts, op, hi, lo, cl, vo = zip(*ohlcv)
                atr = _compute_atr(hi, lo, cl, int(STRAT_ATR_LEN))
                last = float(cl[-2])
                stop_dist = atr * float(STRAT_ATR_MULT)
                sl = loop.sl_price[sym] if loop.sl_price[sym] is not None else (last - stop_dist if side=="long" else last + stop_dist)
                tp = loop.tp_price[sym] if loop.tp_price[sym] is not None else (last + stop_dist*BRACKET_TP_RR if side=="long" else last - stop_dist*BRACKET_TP_RR)
                _ensure_bracket_if_missing(engine, sym, side, size, sl, tp)
                loop.sl_price[sym] = sl
                loop.tp_price[sym] = tp
            except Exception as e:
                logger.warning(f"[RESTORE]{sym} bracket repair failed: {e}")
        if RESTORE_LOG_SUMMARY:
            logger.info(f"[RESTORE]{sym} side={side} size={size} entry={entry} SL={loop.sl_price.get(sym)} TP={loop.tp_price.get(sym)}")

def _get_position_detail(engine, symbol: str):
    """
    return: (side in {'long','short',None}, size_abs, entry_price_or_None)
    """
    # 엔진 헬퍼 우선
    if hasattr(engine, "get_position_detail"):
        try:
            return engine.get_position_detail(symbol)
        except Exception:
            pass

    ex = getattr(engine, "ex", None)
    if ex is None:
        return None, 0.0, None

    # 1) 전체 포지션 조회 (심볼 필터가 빈 배열을 줄 수 있어 보강)
    try:
        pos_list = ex.fetch_positions()
    except Exception as e:
        from loguru import logger
        logger.warning(f"[RESTORE]{symbol} fetch_positions(all) failed: {e}")
        return None, 0.0, None

    target = None

    # 2) 우선 ccxt unified symbol로 매칭
    for p in pos_list or []:
        try:
            contracts = float(p.get("contracts") or 0)
        except Exception:
            contracts = 0.0
        if p.get("symbol") == symbol and abs(contracts) > 0:
            target = p
            break

    # 3) 그래도 못 찾으면 marketId(id) 기반 fallback
    if not target:
        try:
            m = ex.market(symbol)
            market_id = m.get('id')
            for p in pos_list or []:
                try:
                    contracts = float(p.get("contracts") or 0)
                except Exception:
                    contracts = 0.0
                info = p.get("info") or {}
                if info.get("symbol") == market_id and abs(contracts) > 0:
                    target = p
                    break
        except Exception:
            pass

    if not target:
        return None, 0.0, None

    amt = float(target.get("contracts") or 0.0)
    side = target.get("side") or ("long" if amt > 0 else ("short" if amt < 0 else None))
    try:
        entry = float(target.get("entryPrice") or 0.0) or None
    except Exception:
        entry = None
    return side, abs(amt), entry

def _get_reduce_only_orders(engine, symbol: str):
    if hasattr(engine, "get_reduce_only_orders"):
        try: return engine.get_reduce_only_orders(symbol)
        except Exception: pass
    ex = getattr(engine, "ex", None)
    if ex is None: return None, None
    try:
        orders = ex.fetch_open_orders(symbol)
    except Exception as e:
        logger.warning(f"[RESTORE]{symbol} fetch_open_orders failed: {e}")
        return None, None
    if not orders: return None, None
    def is_reduce(o):
        if o.get("reduceOnly") is True: return True
        info = o.get("info") or {}
        return str(info.get("reduceOnly")).lower() in ("true", "1")
    ros = [o for o in orders if is_reduce(o)]
    if not ros: return None, None
    def typ(o): return (o.get("type") or "").upper()
    def trig(o):
        try: return float(o.get("stopPrice") or o.get("triggerPrice") or 0.0)
        except Exception: return 0.0
    sls = [o for o in ros if typ(o) in ("STOP", "STOP_MARKET")]
    tps = [o for o in ros if typ(o) in ("TAKE_PROFIT", "TAKE_PROFIT_MARKET")]
    sl = min(sls, key=lambda o: trig(o) or float("inf"), default=None)
    tp = min(tps, key=lambda o: trig(o) or float("inf"), default=None)
    return sl, tp

def _ensure_bracket_if_missing(engine, symbol: str, side: str, amount: float, sl_price: Optional[float], tp_price: Optional[float]):
    if not BRACKET_REPAIR_ON_START: return
    if hasattr(engine, "ensure_bracket_if_missing"):
        try:
            engine.ensure_bracket_if_missing(symbol, side, amount, sl_price, tp_price)
            return
        except Exception: pass
    ex = getattr(engine, "ex", None)
    if ex is None: return
    cur_sl, cur_tp = _get_reduce_only_orders(engine, symbol)
    need_sl = (sl_price is not None) and (cur_sl is None)
    need_tp = (tp_price is not None) and (cur_tp is None)
    if not (need_sl or need_tp): return
    params = {"reduceOnly": True, "workingType": BRACKET_WORKING_TYPE}
    try:
        if need_sl:
            ex.create_order(symbol, "STOP_MARKET", "sell" if side=="long" else "buy", amount, None, {**params, "stopPrice": sl_price})
            logger.info(f"[RESTORE]{symbol} placed missing SL @ {sl_price}")
        if need_tp:
            tp_type = "TAKE_PROFIT_MARKET" if BRACKET_TP_AS_MARKET else "TAKE_PROFIT"
            ex.create_order(symbol, tp_type, "sell" if side=="long" else "buy", amount, None, {**params, "stopPrice": tp_price})
            logger.info(f"[RESTORE]{symbol} placed missing TP @ {tp_price}")
    except Exception as e:
        logger.warning(f"[RESTORE]{symbol} bracket repair failed: {e}")
