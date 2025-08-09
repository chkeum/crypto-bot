from loguru import logger
from typing import Dict, Any
import time

class PaperExchange:
    def __init__(self, equity_usd: float = 10000.0):
        self.equity_usd = equity_usd
        self.positions = {}  # symbol -> dict(side, amount, entry)

    def fetch_price(self, symbol: str) -> float:
        return 50000.0 + (time.time() % 60)

    def open_market(self, symbol: str, side: str, base_amount: float, leverage: int = 1) -> Dict[str, Any]:
        price = self.fetch_price(symbol)
        pos = self.positions.get(symbol, {"side": None, "amount": 0.0, "entry": 0.0})
        signed_amount = base_amount if side.lower() == "long" else -base_amount
        new_amount = pos["amount"] + signed_amount
        if new_amount != 0:
            pos["entry"] = (pos.get("entry", 0.0) * pos["amount"] + price * signed_amount) / new_amount if pos["amount"] != 0 else price
        else:
            pos["entry"] = 0.0
        pos["amount"] = new_amount
        pos["side"] = "long" if new_amount > 0 else ("short" if new_amount < 0 else None)
        self.positions[symbol] = pos
        logger.info(f"[PAPER] Open {side} {symbol} {base_amount:.6f}@~{price:.2f} lev={leverage}")
        return {"status": "filled", "symbol": symbol, "price": price, "amount": base_amount, "side": side, "leverage": leverage}

    def close_all(self, symbol: str) -> Dict[str, Any]:
        pos = self.positions.get(symbol, {"side": None, "amount": 0.0, "entry": 0.0})
        closed = abs(pos["amount"])
        if closed == 0:
            return {"status":"no_position","symbol":symbol}
        self.positions[symbol] = {"side": None, "amount": 0.0, "entry": 0.0}
        logger.info(f"[PAPER] Close ALL {symbol}, closed_amount={closed:.6f}")
        return {"status": "closed", "symbol": symbol, "closed_amount": closed}
