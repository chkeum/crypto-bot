from __future__ import annotations
import os

import asyncio
from typing import Optional

from fastapi import FastAPI, Request, Depends, Header, Query, HTTPException, APIRouter
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

try:
    WEBHOOK_TOKEN  # may already be imported
except NameError:
    try:
        from .config import WEBHOOK_TOKEN  # noqa
    except Exception:
        WEBHOOK_TOKEN = None  # type: ignore


def _compat_auth_guard(request: Request,
                       x_token: str | None = Header(default=None),
                       token: str | None = Query(default=None)) -> None:
    """
    Auth policy:
      - WEBHOOK_TOKEN 비어있으면 모두 허용
      - ALLOW_LOCAL_NOAUTH=1 이고 클라이언트가 로컬/사설 IP면 허용
      - 아니면 X-Token 헤더 또는 ?token= 값이 WEBHOOK_TOKEN 과 같아야 허용
    """
    import os
    try:
        from .config import WEBHOOK_TOKEN  # 있으면 사용
    except Exception:
        WEBHOOK_TOKEN = os.getenv("WEBHOOK_TOKEN")  # 없으면 env

    allow_local = os.getenv("ALLOW_LOCAL_NOAUTH", "1").lower() in ("1","true","yes","y")  # 기본 허용

    host = request.client.host if request and request.client else None
    def _is_local(h: str | None) -> bool:
        if not h: return False
        if h in ("127.0.0.1","::1","localhost"): return True
        parts = h.split(".")
        if len(parts)==4:
            a,b,*_ = parts
            if a=="10": return True
            if a=="192" and b=="168": return True
            if a=="172":
                try:
                    b=int(b)
                    if 16<=b<=31: return True
                except Exception:
                    pass
        return False

    if not WEBHOOK_TOKEN:
        return
    if allow_local and _is_local(host):
        return

    supplied = x_token or token
    if supplied != WEBHOOK_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

router = APIRouter()

def _parse_symbols(symbols: str | None, symbol: str | None) -> list[str]:
    raw = symbols or symbol or ""
    return [s.strip() for s in raw.split(",") if s.strip()] or STRAT_SYMBOLS

@router.get("/status")
def http_status(
    symbols: str | None = Query(None),
    symbol: str | None = Query(None),  # alias
    _ : None = Depends(_compat_auth_guard),
):
    syms = _parse_symbols(symbols, symbol)
    return {
        "ok": True,
        "engine": type(engine).__name__,
        "mode": START_MODE,
        "strategy": {
            "enabled": bool(STRAT_ENABLE),
            "running": bool(_strat_task and not _strat_task.cancelled()),
        },
        "symbols": syms,
    }

import inspect
async def _maybe_call(func, *args, **kwargs):
    res = func(*args, **kwargs)
    if inspect.isawaitable(res):
        res = await res
    return res

@router.get("/orders")
async def http_orders(
    symbol: str = Query(..., description="e.g. ETH/USDT:USDT"),
    _ : None = Depends(_compat_auth_guard),
):
    # Try a few common method names; fallback to []
    orders = []
    for name in ("get_open_orders", "open_orders", "fetch_open_orders", "list_open_orders"):
        if hasattr(engine, name):
            try:
                orders = await _maybe_call(getattr(engine, name), symbol)
            except Exception as e:
                logger.warning(f"[ORDERS] call {name} failed: {e}")
            break
    return {"ok": True, "symbol": symbol, "orders": orders}

@router.get("/positions")
async def http_positions(
    symbols: str | None = Query(None),
    symbol: str | None = Query(None),
    _ : None = Depends(_compat_auth_guard),
):
    syms = _parse_symbols(symbols, symbol)
    out = {}
    for s in syms:
        pos = None
        for name in ("get_position", "position", "fetch_position"):
            if hasattr(engine, name):
                try:
                    pos = await _maybe_call(getattr(engine, name), s)
                    break
                except Exception as e:
                    logger.warning(f"[POSITIONS] {name}({s}) failed: {e}")
        if pos is None:
            for name in ("get_positions", "fetch_positions", "positions", "list_positions"):
                if hasattr(engine, name):
                    try:
                        bulk = await _maybe_call(getattr(engine, name))
                        if isinstance(bulk, list):
                            pos = next((p for p in bulk if p.get("symbol") == s), None)
                        elif isinstance(bulk, dict):
                            pos = bulk.get(s) or bulk.get(s.replace("/", ""))
                    except Exception as e:
                        logger.warning(f"[POSITIONS] bulk {name} failed: {e}")
                    break
        out[s] = pos
    return {"ok": True, "positions": out}

# 라우터 등록
app.include_router(router)
