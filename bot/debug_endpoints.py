from __future__ import annotations
from typing import Any, Dict, Optional
from fastapi import Depends, FastAPI, Header, HTTPException
from loguru import logger

try:
    from .config import WEBHOOK_TOKEN
except Exception:
    WEBHOOK_TOKEN = None

def _auth_guard(x_token: Optional[str] = Header(default=None)) -> None:
    if WEBHOOK_TOKEN:
        if not x_token or x_token != WEBHOOK_TOKEN:
            raise HTTPException(status_code=401, detail="Unauthorized")

def _f(v, default=None):
    try:
        if v is None: return default
        return float(v)
    except Exception:
        return default

def mount_debug(app: FastAPI, engine: Any) -> None:
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
            pos_list = ex.fetch_positions()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"fetch_positions failed: {e}")

        def is_reduce(o: Dict[str, Any]) -> bool:
            info = (o or {}).get("info") or {}
            ro = str(info.get("reduceOnly", info.get("reduce_only",""))).lower()
            return ro in ("true","1") or (o.get("reduceOnly") is True)

        opens_cache: Dict[str, Any] = {}

        for p in pos_list or []:
            try:
                amt = float(p.get("contracts") or 0.0)
            except Exception:
                amt = 0.0
            if abs(amt) <= 0:
                continue
            sym = p.get("symbol")
            side = p.get("side") or ("long" if amt > 0 else ("short" if amt < 0 else None))
            item = {
                "symbol": sym,
                "contracts": abs(amt),
                "side": side,
                "entryPrice": _f(p.get("entryPrice")),
                "unrealizedPnl": _f(p.get("unrealizedPnl")),
                "leverage": _f(p.get("leverage")),
                "reduceOnly": {"SL": None, "TP": None},
                "raw": p,
            }
            try:
                if sym not in opens_cache:
                    opens_cache[sym] = ex.fetch_open_orders(sym)
                ro = [o for o in opens_cache[sym] or [] if is_reduce(o)]
                def trig(o): return _f(o.get("stopPrice") or o.get("triggerPrice"))
                sls = [o for o in ro if (o.get("type","").upper() in ("STOP","STOP_MARKET"))]
                tps = [o for o in ro if (o.get("type","").upper() in ("TAKE_PROFIT","TAKE_PROFIT_MARKET"))]
                if sls:
                    sls.sort(key=lambda o: trig(o) or 0.0)
                    item["reduceOnly"]["SL"] = trig(sls[0])
                if tps:
                    tps.sort(key=lambda o: trig(o) or 0.0)
                    item["reduceOnly"]["TP"] = trig(tps[0])
            except Exception as e:
                logger.warning(f"[DEBUG] fetch_open_orders({sym}) failed: {e}")
            resp["positions"].append(item)

        resp["note"] = "attach X-Token if WEBHOOK_TOKEN is set"
        return resp
