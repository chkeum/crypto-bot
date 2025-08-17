from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional

from binance.client import Client
from binance.exceptions import BinanceAPIException

from logger import setup_logger


@dataclass
class BotConfig:
    api_key: str = ""
    api_secret: str = ""
    symbol: str = "BTCUSDT"
    entry_intensity: float = 0.001  # Quantity multiplier
    leverage: int = 20
    poll_interval: float = 1.0  # seconds
    testnet: bool = True


class BinanceFuturesBot:
    def __init__(self, config: BotConfig, logger=None):
        self.config = config
        self.logger = logger or setup_logger()
        self.client: Optional[Client] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def _ensure_client(self):
        if self.client is None:
            self.client = Client(self.config.api_key, self.config.api_secret, testnet=self.config.testnet)
            try:
                self.client.futures_change_leverage(symbol=self.config.symbol, leverage=self.config.leverage)
            except BinanceAPIException as exc:
                self.logger.warning("Failed to set leverage: %s", exc)

    def set_symbol(self, symbol: str):
        self.logger.info("Changing symbol to %s", symbol)
        self.config.symbol = symbol.upper()
        if self.client:
            try:
                self.client.futures_change_leverage(symbol=self.config.symbol, leverage=self.config.leverage)
            except BinanceAPIException as exc:
                self.logger.warning("Failed to set leverage on new symbol: %s", exc)

    def set_entry_intensity(self, intensity: float):
        self.logger.info("Setting entry intensity to %.4f", intensity)
        self.config.entry_intensity = intensity

    def start(self):
        if self._running:
            return
        self.logger.info("Starting bot")
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        if not self._running:
            return
        self.logger.info("Stopping bot")
        self._running = False
        if self._thread:
            self._thread.join()

    def _run_loop(self):
        self._ensure_client()
        while self._running:
            try:
                price = float(self.client.futures_symbol_ticker(symbol=self.config.symbol)["price"])
                qty = max(self.config.entry_intensity * 1, 0.001)
                self.logger.debug("Price %.2f, qty %.4f", price, qty)
                # Example trivial strategy: buy when price is even, sell when odd
                side = "BUY" if int(price) % 2 == 0 else "SELL"
                order = self.client.futures_create_order(
                    symbol=self.config.symbol,
                    side=side,
                    type="MARKET",
                    quantity=qty,
                )
                self.logger.info("%s order placed: %s", side, order.get("orderId"))
            except BinanceAPIException as exc:
                self.logger.error("Binance API error: %s", exc)
            except Exception as exc:
                self.logger.error("Unexpected error: %s", exc)
            time.sleep(self.config.poll_interval)
