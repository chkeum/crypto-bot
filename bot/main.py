import asyncio
from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, Literal, List
from loguru import logger

from .config import (
    START_MODE, WEBHOOK_TOKEN, EXCHANGE_ID, IS_TESTNET,
    API_KEY, API_SECRET, DEFAULT_LEVERAGE, STRAT_ENABLE, STRAT_SYMBOLS
)
from .exchange_paper import PaperExchange
from .exchange_binance import BinanceUSDMExchange
from .strategy_loop import StrategyLoop

# restore 기능 활성화
from .restore_bootstrap import enable_restore_on_start
enable_restore_on_start()

app = FastAPI(title="Crypto Bot")

# 엔진 초기화
engine = PaperExchange() if START_MODE == "PAPER" else BinanceUSDMExchange(
    API_KEY, API_SECRET,
    is_testnet=IS_TESTNET,
    default_leverage=DEFAULT_LEVERAGE
)

# debug endpoints mount
try:
    from .debug_endpoints import mount_debug
    mount_debug(app, engine)
except Exception as _e:
    from loguru import logger as _logger
    _logger.warning(f"[DEBUG] mount failed: {_e}")

# restore 부트스트랩 실행
try:
    from .restore_bootstrap import maybe_run_restore_on_start
    maybe_run_restore_on_start(app, engine)
except Exception as _e:
    from loguru import logger as _logger
    _logger.warning(f"[RESTORE] bootstrap call failed: {_e}")


# ======================
# Webhook Signal Schema
# ======================
class Signal(BaseModel):
    action: Literal["buy", "sell", "close"]
    symbol: str
    size: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None


# ======================
# Routes
# ======================
@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/status")
def status(symbols: Optional[str] = None):
    syms = [s.strip() for s in (symbols or STRAT_SYMBOLS).split(",") if s.strip()]
    positions = []
    for sym in syms:
        side, size, entry = (None, 0.0, None)
        if hasattr(engine, "get_position_detail"):
            try:
                side, size, entry = engine.get_position_detail(sym)
            except Exception as e:
                logger.warning(f"[STATUS] get_position_detail({sym}) failed: {e}")
        positions.append({"symbol": sym, "side": side, "size": size, "entry": entry})
    return {"positions": positions}


@app.post("/webhook")
def webhook(signal: Signal, x_token: Optional[str] = Header(default=None)):
    if WEBHOOK_TOKEN and (not x_token or x_token != WEBHOOK_TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized")

    symbol = signal.symbol
    action = signal.action.lower()
    size = signal.size

    if action in ["buy", "sell"]:
        side = "long" if action == "buy" else "short"
        return engine.open_market(symbol, side, size)
    elif action == "close":
        return engine.close_all(symbol)
    else:
        raise HTTPException(status_code=400, detail="Invalid action")


# ======================
# 전략 루프
# ======================
@app.on_event("startup")
async def start_strategy():
    if STRAT_ENABLE:
        loop = StrategyLoop(app, engine, symbols=STRAT_SYMBOLS)
        asyncio.create_task(loop.run())


@app.on_event("shutdown")
async def shutdown():
    logger.info("Shutting down...")

