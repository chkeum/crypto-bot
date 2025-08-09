# bot/main.py
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
    WEBHOOK_TOKEN,  # 사용은 debug_endpoints에서 인증에 활용
)

from .exchange_paper import PaperExchange
from .exchange_binance import BinanceUSDMExchange
from .strategy_loop import StrategyLoop

# restore 부트스트랩/워처
from .restore_bootstrap import (
    enable_restore_on_start,
    maybe_run_restore_on_start,
    setup_restore_watch,
)

# 선택적: 디버그 엔드포인트 마운트
try:
    from .debug_endpoints import mount_debug
except Exception as _e:
    mount_debug = None
    logger.warning(f"[DEBUG] debug_endpoints not available: {_e}")


# -------------------------
# FastAPI 앱 & 엔진 초기화
# -------------------------
enable_restore_on_start()  # 부트스트랩 플래그 ON (한 번만)

app = FastAPI(title="Crypto Bot")

# 거래소 엔진 생성 (Paper 또는 Binance USDM)
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

# 디버그 엔드포인트 1회만 마운트
if mount_debug is not None:
    try:
        mount_debug(app, engine)
    except Exception as _e:
        logger.warning(f"[DEBUG] mount failed: {_e}")


# -------------------------
# 헬스체크
# -------------------------
@app.get("/health")
def health():
    return {"ok": True}


# -------------------------
# 전략 루프 관리
# -------------------------
_strat: Optional[StrategyLoop] = None
_strat_task: Optional[asyncio.Task] = None


@app.on_event("startup")
async def _on_startup():
    global _strat, _strat_task

    # 재기동시 포지션 복원 점검 (한 번)
    try:
        maybe_run_restore_on_start(app, engine)
    except Exception as e:
        logger.warning(f"[RESTORE] bootstrap call failed: {e}")

    # 주기 감시 워처 등록 (RESTORE_WATCH_INTERVAL 이 설정되어 있으면 동작)
    try:
        setup_restore_watch(app, engine)
    except Exception as e:
        logger.warning(f"[RESTORE] watch setup failed: {e}")

    # 전략 루프 시작
    if STRAT_ENABLE:
        _strat = StrategyLoop(engine=engine, symbols=STRAT_SYMBOLS)
        _strat_task = asyncio.create_task(_strat.run())
        logger.info("[MAIN] strategy loop started")
    else:
        logger.info("[MAIN] strategy disabled (STRAT_ENABLE=false)")


@app.on_event("shutdown")
async def _on_shutdown():
    global _strat, _strat_task

    # 전략 루프 정리
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

