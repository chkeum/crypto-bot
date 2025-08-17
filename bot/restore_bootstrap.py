from __future__ import annotations
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Optional, Tuple
from loguru import logger
from .config import STRAT_SYMBOLS, BRACKET_ENABLE, BRACKET_TP_AS_MARKET, BRACKET_WORKING_TYPE

_enabled: bool = False
_watch_task: Optional[asyncio.Task] = None

# -------- env knobs (safe defaults) --------
def _tag_file_path() -> Path:
    return Path(os.getenv("RESTORE_TAG_FILE", str((Path(__file__).resolve().parents[1] / "state" / "bot_positions.json"))))

def _restore_enabled() -> bool:
    return str(os.getenv("BRACKET_RESTORE_ENABLE", "0")).lower() in ("1","true","yes","y","on")

def _restore_only_bot() -> bool:
    return str(os.getenv("RESTORE_ONLY_BOT", "1")).lower() in ("1","true","yes","y","on")

def _tag_ttl_sec() -> int:
    try:
        return int(os.getenv("RESTORE_TAG_TTL_SEC", "172800"))  # 48h
    except Exception:
        return 172800

def _size_tol_pct() -> float:
    try:
        return float(os.getenv("RESTORE_SIZE_TOL_PCT", "0.20"))  # 20%
    except Exception:
        return 0.20

# ------------- public toggles -------------
def enable_restore_on_start() -> None:
    global _enabled
    _enabled = True
    logger.info("[RESTORE] bootstrap enabled")

# ------------- position introspection -------------
def _get_position_detail(engine, symbol: str) -> Tuple[Optional[str], float, Optional[float]]:
    # fast path if engine has helper
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
        ro = str(info.get("reduceOnly", info.get("reduce_only", ""))).lower() in ("true", "1")
        if ro:
            return True
    return False

# ------------- tags -------------
def _load_tags() -> dict:
    p = _tag_file_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8") or "{}")
    except Exception:
        return {}

def _get_valid_tag_for(symbol: str) -> Optional[dict]:
    tags = _load_tags()
    tag = tags.get(symbol)
    if not tag:
        return None
    ttl = _tag_ttl_sec()
    now_ms = int(time.time() * 1000)
    if ttl > 0 and (now_ms - int(tag.get("ts", 0))) > ttl * 1000:
        return None
    return tag

# ------------- core restore -------------
def _restore_once(engine) -> None:
    ex = getattr(engine, "ex", None)
    if not ex:
        logger.warning("[RESTORE] engine.ex missing; skip restore")
        return

    syms = [s.strip() for s in STRAT_SYMBOLS.split(",") if s.strip()]
    only_bot = _restore_only_bot()
    for sym in syms:
        side, size, entry = _get_position_detail(engine, sym)
        if not side or size <= 0:
            logger.info(f"[RESTORE]{sym} no position; nothing to restore.")
            continue
        has_ro = _has_reduce_only_orders(ex, sym)
        if has_ro:
            logger.info(f"[RESTORE]{sym} reduceOnly SL/TP already exists; skip.")
            continue

        logger.info(f"[RESTORE]{sym} side={side} size={size} entry={entry} reduceOnly_exists=False")

        if not _restore_enabled():
            logger.warning(f"[RESTORE]{sym} restore disabled (BRACKET_RESTORE_ENABLE=0). Manual check recommended.")
            continue

        if not BRACKET_ENABLE or not hasattr(engine, "place_bracket"):
            logger.warning(f"[RESTORE]{sym} engine cannot place bracket; skip.")
            continue

        tag = _get_valid_tag_for(sym)
        if only_bot and not tag:
            logger.info(f"[RESTORE]{sym} ONLY_BOT=1 and no valid tag -> skip touching manual positions.")
            continue

        if tag:
            tag_side = tag.get("side")
            tag_qty  = float(tag.get("qty", 0.0) or 0.0)
            tag_sl   = float(tag.get("sl")) if tag.get("sl") is not None else None
            tag_tp   = float(tag.get("tp")) if tag.get("tp") is not None else None

            if tag_side and tag_side != side:
                logger.warning(f"[RESTORE]{sym} tag side={tag_side} != pos side={side}; skip for safety.")
                continue

            use_qty = min(size, tag_qty) if tag_qty > 0 else size
            # size tolerance log
            try:
                tol = _size_tol_pct()
                if size > 0 and abs(size - use_qty) / size > tol:
                    logger.warning(f"[RESTORE]{sym} size diff tag={tag_qty} vs pos={size} (> {tol*100:.0f}%); capping to {use_qty}")
            except Exception:
                pass

            if tag_sl is None or tag_tp is None:
                logger.warning(f"[RESTORE]{sym} tag missing sl/tp; skip.")
                continue

            try:
                engine.place_bracket(
                    sym, side, use_qty, tag_sl, tag_tp,
                    tp_as_market=BRACKET_TP_AS_MARKET,
                    working_type=BRACKET_WORKING_TYPE,
                )
                logger.info(f"[BRACKET] {sym} restored from tag: side={side} qty={use_qty} SL={tag_sl} TP={tag_tp}")
            except Exception as e:
                logger.warning(f"[RESTORE]{sym} bracket restore failed: {e}")
        else:
            # no tag, ONLY_BOT=0 => we could compute generic SL/TP, but safer to log only
            logger.warning(f"[RESTORE]{sym} no tag and ONLY_BOT=0; for safety, not restoring blindly.")

# ------------- lifecycle hooks -------------
def maybe_run_restore_on_start(app, engine) -> None:
    if _enabled:
        try:
            _restore_once(engine)
        except Exception as e:
            logger.warning(f"[RESTORE] failed: {e}")

def setup_restore_watch(app, engine, interval_sec: int = 60) -> None:
    if interval_sec <= 0:
        logger.info("[RESTORE] periodic watch disabled (interval<=0)")
        return

    async def _startup():
        if not _enabled:
            return
        global _watch_task
        if _watch_task and not _watch_task.done():
            return

        async def _loop():
            while True:
                try:
                    await asyncio.to_thread(_restore_once, engine)
                    await asyncio.sleep(interval_sec)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.warning(f"[RESTORE] periodic failed: {e}")

        _watch_task = asyncio.create_task(_loop(), name="restore_watch")

    async def _shutdown():
        global _watch_task
        if _watch_task:
            _watch_task.cancel()
            try:
                await _watch_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            _watch_task = None

    app.add_event_handler("startup", _startup)
    app.add_event_handler("shutdown", _shutdown)

