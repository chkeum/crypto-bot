from __future__ import annotations
from typing import Optional, Tuple
from loguru import logger
from .config import STRAT_SYMBOLS

_enabled = False


def enable_restore_on_start() -> None:
    global _enabled
    _enabled = True
    logger.info("[RESTORE] bootstrap enabled")


def _get_position_detail(
    engine, symbol: str
) -> Tuple[Optional[str], float, Optional[float]]:
    """
    Prefer engine.get_position_detail if present; otherwise, read all positions via ccxt
    and match by symbol/market id.
    """
    if hasattr(engine, "get_position_detail"):
        try:
            return engine.get_position_detail(symbol)
        except Exception:
            pass

    ex = getattr(engine, "ex", None)
    if ex is None:
        return None, 0.0, None

    try:
        pos_list = ex.fetch_positions()
    except Exception as e:
        logger.warning(f"[RESTORE]{symbol} fetch_positions(all) failed: {e}")
        return None, 0.0, None

    target = None
    for p in pos_list or []:
        try:
            contracts = float(p.get("contracts") or 0.0)
        except Exception:
            contracts = 0.0
        if p.get("symbol") == symbol and abs(contracts) > 0:
            target = p
            break

    if not target:
        try:
            m = ex.market(symbol)
            market_id = m.get("id")
            for p in pos_list or []:
                info = p.get("info") or {}
                try:
                    contracts = float(p.get("contracts") or 0.0)
                except Exception:
                    contracts = 0.0
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


def _has_reduce_only_orders(ex, symbol: str) -> bool:
    try:
        ods = ex.fetch_open_orders(symbol)
    except Exception as e:
        logger.warning(f"[RESTORE]{symbol} fetch_open_orders failed: {e}")
        return False
    for o in ods or []:
        info = o.get("info") or {}
        ro = str(info.get("reduceOnly", info.get("reduce_only", ""))).lower() in (
            "true",
            "1",
        )
        if ro:
            return True
    return False


def _restore_on_start(engine) -> None:
    """
    On restart, log current positions and warn if no reduceOnly SL/TP exist.
    """
    ex = getattr(engine, "ex", None)
    if not ex:
        logger.warning("[RESTORE] engine.ex missing; skip restore")
        return

    syms = [s.strip() for s in STRAT_SYMBOLS.split(",") if s.strip()]
    for sym in syms:
        side, size, entry = _get_position_detail(engine, sym)
        if not side or size <= 0:
            logger.info(f"[RESTORE]{sym} no position; nothing to restore.")
            continue
        has_ro = _has_reduce_only_orders(ex, sym)
        logger.info(
            f"[RESTORE]{sym} side={side} size={size} entry={entry} reduceOnly_exists={has_ro}"
        )
        if not has_ro:
            logger.warning(
                f"[RESTORE]{sym} reduceOnly SL/TP not found. (manual check recommended)"
            )


def maybe_run_restore_on_start(app, engine) -> None:
    if _enabled:
        try:
            _restore_on_start(engine)
        except Exception as e:
            logger.warning(f"[RESTORE] failed: {e}")
