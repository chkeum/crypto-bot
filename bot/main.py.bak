from bot.restore_bootstrap import enable_restore_on_start
enable_restore_on_start()
import asyncio
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from typing import Optional, Literal
from loguru import logger
from .restore_bootstrap import enable_restore_on_start

from .config import (
  START_MODE, WEBHOOK_TOKEN, EXCHANGE_ID, IS_TESTNET,
  API_KEY, API_SECRET, DEFAULT_LEVERAGE, STRAT_ENABLE, STRAT_SYMBOLS
)
from .exchange_paper import PaperExchange
from .exchange_binance import BinanceUSDMExchange
from .strategy_loop import StrategyLoop
from typing import List
from fastapi import Query

app = FastAPI(title="Crypto Bot")
engine = PaperExchange() if START_MODE=="PAPER" else BinanceUSDMExchange(API_KEY, API_SECRET, is_testnet=IS_TESTNET, default_leverage=DEFAULT_LEVERAGE)

# --- debug & restore mounts ---
try:
    from .debug_endpoints import mount_debug
    mount_debug(app, engine)
except Exception as _e:
    from loguru import logger as _logger
    _logger.warning(f"[DEBUG] mount failed: {_e}")
try:
    from .restore_bootstrap import maybe_run_restore_on_start
    maybe_run_restore_on_start(app, engine)
except Exception as _e:
    from loguru import logger as _logger
    _logger.warning(f"[RESTORE] bootstrap call failed: {_e}")
# --------------------------------

class Signal(BaseModel):
    action: Literal["open","close"]
    symbol: str
    side: Optional[Literal["long","short"]] = None
    qty_usd: Optional[float] = None
    leverage: Optional[int] = None
    strategy: Optional[str] = None

@app.get("/health")
def health(): 
    return {"ok": True, "mode": START_MODE, "exchange": EXCHANGE_ID}

@app.post("/signal")
def signal(payload: Signal, x_auth_token: Optional[str] = Header(None)):
    # 외부 웹훅을 쓸 때만 사용 (내부전략에선 필요 X)
    if WEBHOOK_TOKEN and x_auth_token != WEBHOOK_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if payload.action=="open":
        if not payload.side: raise HTTPException(400, "side required")
        if not payload.qty_usd or payload.qty_usd<=0: raise HTTPException(400, "qty_usd > 0 required")
        price = engine.fetch_price(payload.symbol)
        base = payload.qty_usd / max(price, 1e-9)
        res = engine.open_market(payload.symbol, payload.side, base, leverage=payload.leverage)
        return {"ok":True, "price":price, "base_amount":base, "exchange":res}
    elif payload.action=="close":
        res = engine.close_all(payload.symbol); return {"ok":True, "exchange":res}
    else:
        raise HTTPException(400, "invalid action")

strategy_task=None
strategy_loop=None

@app.on_event("startup")
async def _startup():
    global strategy_task, strategy_loop
    if STRAT_ENABLE:
        strategy_loop = StrategyLoop(engine)
        strategy_task = asyncio.create_task(strategy_loop.run())

@app.on_event("shutdown")
async def _shutdown():
    global strategy_task, strategy_loop
    if strategy_loop: await strategy_loop.stop()


def _get_side_and_size(engine, symbol: str):
    side, size = None, 0.0
    # PAPER
    if hasattr(engine, "positions"):
        pos = getattr(engine, "positions", {}).get(symbol) or {}
        amt = float(pos.get("amount", 0.0))
        size = abs(amt)
        side = "long" if amt > 0 else ("short" if amt < 0 else None)
        return side, size
    # BINANCE
    if hasattr(engine, "_get_position_size"):
        try:
            s = engine._get_position_size(symbol)
            size = abs(s)
            side = "long" if s > 0 else ("short" if s < 0 else None)
        except Exception:
            pass
    return side, size

@app.get("/status")
def status(symbols: Optional[str] = None):
    # 예: /status?symbols=BTC/USDT,ETH/USDT  (없으면 STRAT_SYMBOLS 사용)
    syms = [s.strip() for s in (symbols or STRAT_SYMBOLS).split(",") if s.strip()]
    out = []
    for sym in syms:
        side, size = _get_side_and_size(engine, sym)
        out.append({"symbol": sym, "side": side, "size": size})
    return {"positions": out}

@app.get("/orders")
def orders(symbol: str = Query(..., description="e.g., BTC/USDT")):
    # BINANCE 모드에서 미체결 주문(특히 reduceOnly 브래킷) 확인
    if not hasattr(engine, "exchange"):
        return {"open_orders": []}
    try:
        opens = engine.exchange.fetch_open_orders(symbol)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"fetch_open_orders failed: {e}")
    res = []
    for o in opens:
        info = o.get("info", {})
        reduce_only = str(info.get("reduceOnly", info.get("reduce_only", ""))).lower() in ["true", "1"]
        res.append({
            "id": o.get("id"),
            "type": o.get("type"),
            "side": o.get("side"),
            "status": o.get("status"),
            "price": o.get("price"),
            "stopPrice": info.get("stopPrice"),
            "reduceOnly": reduce_only,
        })
    return {"open_orders": res}

# --- debug endpoints mount ---
try:
    from .debug_endpoints import mount_debug
    mount_debug(app, engine)
except Exception as _e:
    from loguru import logger
from .restore_bootstrap import enable_restore_on_start as _logger
    _logger.warning(f"[DEBUG] mount failed: {_e}")
# -----------------------------
