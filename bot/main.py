from __future__ import annotations

import os
import asyncio
import inspect
from typing import Optional

from fastapi import FastAPI, Request, Depends, Header, Query, HTTPException, APIRouter
from loguru import logger
from .colored_logging import setup as _setup_logging
_setup_logging()

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

# --- optional debug endpoints -------------------------------------------------
try:
    from .debug_endpoints import mount_debug
except Exception as _e:
    mount_debug = None
    logger.warning(f"[DEBUG] debug_endpoints not available: {_e}")

# --- one-time bootstrap toggles ----------------------------------------------
enable_restore_on_start()  # once

# --- FastAPI ------------------------------------------------------------------
app = FastAPI(title="Crypto Bot")

# --- trading engine -----------------------------------------------------------
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

# --- health -------------------------------------------------------------------
@app.get("/health")
def health():
    return {"ok": True}

# --- strategy loop lifecycle --------------------------------------------------
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

# =============================================================================
# Compat endpoints (/status, /orders, /positions)
# =============================================================================

# --- auth guard ---------------------------------------------------------------
try:
    WEBHOOK_TOKEN  # type: ignore  # may already be imported
except NameError:
    try:
        from .config import WEBHOOK_TOKEN  # noqa: F401
    except Exception:
        WEBHOOK_TOKEN = None  # type: ignore


def _compat_auth_guard(
    request: Request,
    x_token: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> None:
    """
    Auth policy:
      - WEBHOOK_TOKEN 비어있으면 모두 허용
      - ALLOW_LOCAL_NOAUTH=1 이고 클라이언트가 로컬/사설 IP면 허용
      - 아니면 X-Token 헤더 또는 ?token= 값이 WEBHOOK_TOKEN 과 같아야 허용
    """
    try:
        from .config import WEBHOOK_TOKEN  # prefer config
    except Exception:
        # fallback to env
        WEBHOOK_TOKEN = os.getenv("WEBHOOK_TOKEN")  # type: ignore

    allow_local = os.getenv("ALLOW_LOCAL_NOAUTH", "1").lower() in ("1", "true", "yes", "y")

    host = request.client.host if request and request.client else None

    def _is_local(h: str | None) -> bool:
        if not h:
            return False
        if h in ("127.0.0.1", "::1", "localhost"):
            return True
        parts = h.split(".")
        if len(parts) == 4:
            a, b, *_ = parts
            if a == "10":
                return True
            if a == "192" and b == "168":
                return True
            if a == "172":
                try:
                    b = int(b)
                    if 16 <= b <= 31:
                        return True
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


def _as_list_symbols(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, (list, tuple, set)):
        return list(v)
    if isinstance(v, str):
        return [v]
    return [str(v)]


def _parse_symbols(symbols: str | None, symbol: str | None) -> list[str]:
    raw = symbols or symbol or ""
    items = [s.strip() for s in raw.split(",") if s.strip()]
    if items:
        return items
    # fallback to config default as list
    return _as_list_symbols(STRAT_SYMBOLS)


@router.get("/status")
def http_status(
    symbols: str | None = Query(None),
    symbol: str | None = Query(None),  # alias
    _: None = Depends(_compat_auth_guard),
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


async def _maybe_call(func, *args, **kwargs):
    res = func(*args, **kwargs)
    if inspect.isawaitable(res):
        res = await res
    return res


@router.get("/orders")
async def http_orders(
    symbol: str = Query(..., description="e.g. ETH/USDT:USDT"),
    _: None = Depends(_compat_auth_guard),
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

# ---- positions (all) ---------------------------------------------------------

def _sym_to_binance(sym: str) -> str:
    # "XRP/USDT:USDT" -> "XRPUSDT"
    if not sym:
        return sym
    return sym.split(":")[0].replace("/", "")


def _norm_usdm_symbol(sym: str | None) -> str | None:
    if not sym:
        return sym
    # "XRPUSDT" -> "XRP/USDT:USDT"
    if sym.endswith("USDT") and "/" not in sym:
        base = sym[:-4]
        return f"{base}/USDT:USDT"
    return sym


def _normalize_binance_position(p: dict) -> dict:
    # Binance USD-M futures typical fields
    sym_raw = p.get("symbol")
    sym = _norm_usdm_symbol(sym_raw)

    # size
    amt_str = p.get("positionAmt") or p.get("contracts") or "0"
    try:
        amt = float(amt_str)
    except Exception:
        amt = 0.0

    # entry price
    entry = 0.0
    for k in ("entryPrice", "avgEntryPrice"):
        if p.get(k) not in (None, "", "0", 0):
            try:
                entry = float(p[k])
                break
            except Exception:
                pass

    # side
    side = None
    if "positionSide" in p and p["positionSide"]:
        ps = str(p["positionSide"]).upper()
        if ps in ("LONG", "SHORT"):
            side = ps.lower()
    if side is None:
        side = "long" if amt > 0 else ("short" if amt < 0 else None)

    return {
        "symbol": sym,
        "size": abs(amt),
        "side": side,
        "entry": entry,
        "raw": {
            "symbol": sym_raw,
            "positionAmt": amt_str,
            "entryPrice": p.get("entryPrice"),
            "positionSide": p.get("positionSide"),
        },
    }


async def _ensure_positions_fresh():
    # 엔진에 캐시 리프레시류 메서드가 있으면 한 번 호출
    for name in ("refresh_positions", "load_positions", "sync_positions", "update_positions"):
        if hasattr(engine, name):
            try:
                await _maybe_call(getattr(engine, name))
                return
            except Exception as e:
                logger.warning(f"[POSITIONS] refresh via {name} failed: {e}")


async def _fetch_all_positions():
    await _ensure_positions_fresh()

    # 1) 엔진의 bulk 메서드 시도
    for name in ("get_positions", "fetch_positions", "positions", "list_positions"):
        if hasattr(engine, name):
            try:
                res = await _maybe_call(getattr(engine, name))
                if res is not None:
                    return res
            except Exception as e:
                logger.warning(f"[POSITIONS] bulk call {name} failed: {e}")

    # 2) CCXT 스타일: engine.exchange.fetch_positions()
    ex = getattr(engine, "exchange", None)
    if ex and hasattr(ex, "fetch_positions"):
        try:
            res = await _maybe_call(ex.fetch_positions)
            if res is not None:
                return res
        except Exception as e:
            logger.warning(f"[POSITIONS] ccxt fetch_positions failed: {e}")

    # 3) Binance python client 직접 호출
    client = getattr(engine, "client", None)
    for method_name in ("futures_position_information", "fapiPrivateGetPositionRisk", "futures_account"):
        if client and hasattr(client, method_name):
            try:
                if method_name == "futures_account":
                    acc = await _maybe_call(getattr(client, method_name))
                    res = acc.get("positions", []) if isinstance(acc, dict) else []
                else:
                    res = await _maybe_call(getattr(client, method_name))
                return res
            except Exception as e:
                logger.warning(f"[POSITIONS] binance client {method_name} failed: {e}")

    # 4) 마지막 폴백: 심볼별 단건 메서드
    syms = _as_list_symbols(STRAT_SYMBOLS)
    out = []
    for s in syms:
        for name in ("get_position", "position", "fetch_position"):
            if hasattr(engine, name):
                try:
                    p = await _maybe_call(getattr(engine, name), s)
                    if p:
                        out.append(p)
                    break
                except Exception as e:
                    logger.warning(f"[POSITIONS] {name}({s}) failed: {e}")
    return out


@router.get("/positions")
async def http_positions(
    raw: bool = Query(False, description="원본 payload 포함 여부"),
    _: None = Depends(_compat_auth_guard),
):
    data = await _fetch_all_positions()

    out = []
    raw_payload = None

    if isinstance(data, list) and data and isinstance(data[0], dict) and ("symbol" in data[0]):
        raw_payload = data if raw else None
        # Binance 원본 추정: positionAmt/positionSide/entryPrice 존재
        if "positionAmt" in data[0] or "contracts" in data[0] or "positionSide" in data[0]:
            out = [
                _normalize_binance_position(p)
                for p in data
                if str(p.get("positionAmt") or p.get("contracts") or "0") not in ("0", "0.0", "", None)
            ]
        else:
            # 이미 엔진 정규화 형식이라면 size!=0만 필터
            for p in data:
                try:
                    sz = float(p.get("size", 0))
                except Exception:
                    sz = 0.0
                if sz != 0:
                    out.append(p)

    elif isinstance(data, dict):
        raw_payload = data if raw else None
        # {"XRPUSDT": {...}, ...} 형태
        for k, v in data.items():
            if not isinstance(v, dict):
                continue
            v2 = v.copy()
            v2["symbol"] = v2.get("symbol") or _norm_usdm_symbol(k)
            try:
                sz = float(v2.get("size") or v2.get("positionAmt") or v2.get("contracts") or 0)
            except Exception:
                sz = 0.0
            if sz != 0:
                out.append(v2)

    else:
        out = []

    return {"ok": True, "positions": out, **({"raw": raw_payload} if raw else {})}

# --- mount compat router ------------------------------------------------------
app.include_router(router)

