from __future__ import annotations
from typing import Any, Dict, List, Optional
from fastapi import Depends, FastAPI, Header, HTTPException
from loguru import logger

# 기존 .env에서 쓰는 토큰 재사용 (없으면 None)
try:
    from .config import WEBHOOK_TOKEN
except Exception:
    WEBHOOK_TOKEN = None

def _auth_guard(x_token: Optional[str] = Header(default=None)) -> None:
    """
    간단 보호: .env에 WEBHOOK_TOKEN이 설정돼 있으면, 헤더 X-Token과 같아야 접근 허용
    없으면(빈값/None) 누구나 접근 가능(로컬에서만 쓰는 용도 가정)
    """
    if WEBHOOK_TOKEN:
        if not x_token or x_token != WEBHOOK_TOKEN:
            raise HTTPException(status_code=401, detail="Unauthorized")

def _clean_float(v, default: Optional[float]=None) -> Optional[float]:
    try:
        if v is None:
            return default
        f = float(v)
        return f
    except Exception:
        return default

def mount_debug(app: FastAPI, engine: Any) -> None:
    """
    /debug/positions : 현재 오픈 포지션(심볼/사이즈/사이드/엔트리/SL,TP 등)
    """
    if engine is None or getattr(engine, "ex", None) is None:
        logger.warning("[DEBUG] engine/ex missing; debug endpoints limited")

    @app.get("/debug/positions")
    def debug_positions(_: None = Depends(_auth_guard)) -> Dict[str, Any]:
        ex = getattr(engine, "ex", None)
        resp: Dict[str, Any] = {"positions": [], "note": ""}

        if ex is None:
            resp["note"] = "engine.ex not available"
            return resp

        try:
            # ccxt 전체 포지션
            pos_list = ex.fetch_positions()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"fetch_positions failed: {e}")

        # 오픈 포지션만 추림
        open_pos = [p for p in pos_list or [] if abs(_clean_float(p.get("contracts"), 0.0) or 0.0) > 0.0]

        # 심볼별 reduceOnly SL/TP도 확인
        def is_reduce(o: Dict[str, Any]) -> bool:
            if o.get("reduceOnly") is True:
                return True
            info = o.get("info") or {}
            return str(info.get("reduceOnly")).lower() in ("true", "1")

        for p in open_pos:
            sym = p.get("symbol")
            amt = _clean_float(p.get("contracts"), 0.0) or 0.0
            side = p.get("side") or ("long" if amt > 0 else ("short" if amt < 0 else None))
            entry = _clean_float(p.get("entryPrice"))

            # 기본 결과
            item = {
                "symbol": sym,
                "contracts": abs(amt),
                "side": side,
                "entryPrice": entry,
                "unrealizedPnl": _clean_float(p.get("unrealizedPnl")),
                "leverage": _clean_float(p.get("leverage")),
                "raw": p,  # 원본도 같이
            }

            # reduceOnly 주문 조사
            sl_px, tp_px = None, None
            try:
                orders = ex.fetch_open_orders(sym)
                ro = [o for o in orders or [] if is_reduce(o)]
                # 타입 구분
                def typ(o): return (o.get("type") or "").upper()
                def trig(o):
                    return _clean_float(o.get("stopPrice") or o.get("triggerPrice"))
                sls = [o for o in ro if typ(o) in ("STOP", "STOP_MARKET")]
                tps = [o for o in ro if typ(o) in ("TAKE_PROFIT", "TAKE_PROFIT_MARKET")]
                # 가장 가까운 가격 하나만 요약
                if sls:
                    sls_sorted = sorted(sls, key=lambda o: trig(o) or 0.0)
                    sl_px = trig(sls_sorted[0])
                if tps:
                    tps_sorted = sorted(tps, key=lambda o: trig(o) or 0.0)
                    tp_px = trig(tps_sorted[0])
            except Exception as e:
                logger.warning(f"[DEBUG] fetch_open_orders({sym}) failed: {e}")

            item["reduceOnly"] = {"SL": sl_px, "TP": tp_px}
            resp["positions"].append(item)

        resp["note"] = "attach X-Token header if WEBHOOK_TOKEN is set in .env"
        return resp
