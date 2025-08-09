from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import FastAPI
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
