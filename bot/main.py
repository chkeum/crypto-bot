from __future__ import annotations
import os

import asyncio
from typing import Optional

from fastapi import FastAPI, Request
from loguru import logger

from .config import (
    START_MODE,
    API_KEY,
    API_SECRET,
    IS_TESTNET,
    DEFAULT_LEVERAGE,
    STRAT_ENABLE,
    STRAT_SYMBOLS,
)

from .exchange_paper import PaperExchange
from .exchange_binance import BinanceUSDMExchange
from .strategy_loop import StrategyLoop

from .restore_bootstrap import (
    enable_restore_on_start,
    maybe_run_restore_on_start,
    setup_restore_watch,
)

try:
    from .debug_endpoints import mount_debug
except Exception as _e:
    mount_debug = None
    logger.warning(f"[DEBUG] debug_endpoints not available: {_e}")

enable_restore_on_start()  # once

app = FastAPI(title="Crypto Bot")

engine = (
    PaperExchange()
    if START_MODE == "PAPER"
    else BinanceUSDMExchange(
        api_key=API_KEY,
        api_secret=API_SECRET,
        is_testnet=IS_TESTNET,
        default_leverage=DEFAULT_LEVERAGE,
    )
)

if mount_debug is not None:
    try:
        mount_debug(app, engine)
    except Exception as _e:
        logger.warning(f"[DEBUG] mount failed: {_e}")


@app.get("/health")
def health():
    return {"ok": True}


_strat: Optional[StrategyLoop] = None
_strat_task: Optional[asyncio.Task] = None


@app.on_event("startup")
async def _on_startup():
    global _strat, _strat_task
    try:
        maybe_run_restore_on_start(app, engine)
    except Exception as e:
        logger.warning(f"[RESTORE] bootstrap call failed: {e}")

    try:
        setup_restore_watch(app, engine)
    except Exception as e:
        logger.warning(f"[RESTORE] watch setup failed: {e}")

    if STRAT_ENABLE:
        _strat = StrategyLoop(engine=engine)
        _strat_task = asyncio.create_task(_strat.run())
        logger.info("[MAIN] strategy loop started")
    else:
        logger.info("[MAIN] strategy disabled (STRAT_ENABLE=false)")


@app.on_event("shutdown")
async def _on_shutdown():
    global _strat, _strat_task
    if _strat_task:
        try:
            if _strat and hasattr(_strat, "stop"):
                _strat.stop()
            _strat_task.cancel()
        except Exception:
            pass
        _strat_task = None
        _strat = None
        logger.info("[MAIN] strategy loop stopped")

# --- compat endpoints: /status, /orders (for existing scripts) ---
from fastapi import Query, HTTPException
from fastapi import Depends, Header, Query, HTTPException

try:
    WEBHOOK_TOKEN  # may already be imported
except NameError:
    try:
        from .config import WEBHOOK_TOKEN  # noqa
    except Exception:
        WEBHOOK_TOKEN = None  # type: ignore

def _compat_auth_guard(x_token: str | None = Header(default=None)) -> None:
    if WEBHOOK_TOKEN and x_token != WEBHOOK_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

# 내부 로직 재사용: 현재 포지션 파악
from .restore_bootstrap import _get_position_detail as _pos_detail  # noqa

@app.get("/status")
def http_status(symbols: str | None = Query(None), _: None = Depends(_compat_auth_guard)):
    ex = getattr(engine, "ex", None)
    if ex is None:
        raise HTTPException(500, "exchange not ready")
    syms = [s.strip() for s in (symbols or STRAT_SYMBOLS).split(",") if s.strip()]
    data = []
    for sym in syms:
        side, size, entry = _pos_detail(engine, sym)
        data.append({"symbol": sym, "side": side, "contracts": size, "entryPrice": entry})
    return {"symbols": syms, "positions": data}

@app.get("/orders")
def http_orders(symbol: str = Query(...), _: None = Depends(_compat_auth_guard)):
    ex = getattr(engine, "ex", None)
    if ex is None:
        raise HTTPException(500, "exchange not ready")
    try:
        ods = ex.fetch_open_orders(symbol)
    except Exception as e:
        raise HTTPException(500, f"fetch_open_orders failed: {e}")
    return {"symbol": symbol, "orders": ods}
# --- end compat endpoints ---

@app.middleware("http")
async def _log_http(request: Request, call_next):
    import time
    t0 = time.time()
    resp = await call_next(request)
    dt = (time.time() - t0) * 1000
    logger.info(f"[HTTP] {request.method} {request.url.path} -> {resp.status_code} ({dt:.1f}ms)")
    return resp
