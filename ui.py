import tkinter as tk
from tkinter import ttk
import logging

from bot import BinanceFuturesBot, BotConfig
from logger import setup_logger


class TextHandler(logging.Handler):
    """Logging handler that outputs to a Tkinter Text widget."""
    def __init__(self, text_widget: tk.Text):
        super().__init__()
        self.text = text_widget
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        def append():
            self.text.configure(state="normal")
            self.text.insert(tk.END, msg + "\n")
            self.text.configure(state="disabled")
            self.text.yview(tk.END)
        self.text.after(0, append)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Crypto Bot")
        self.logger = setup_logger()
        config = BotConfig()
        self.bot = BinanceFuturesBot(config, self.logger)

        self._build_ui()

    def _build_ui(self):
        controls = ttk.Frame(self)
        controls.pack(padx=10, pady=10)

        start_btn = ttk.Button(controls, text="Start", command=self.bot.start)
        start_btn.grid(row=0, column=0, padx=5)

        stop_btn = ttk.Button(controls, text="Stop", command=self.bot.stop)
        stop_btn.grid(row=0, column=1, padx=5)

        ttk.Label(controls, text="Symbol:").grid(row=1, column=0, sticky="e")
        self.symbol_var = tk.StringVar(value=self.bot.config.symbol)
        symbol_entry = ttk.Entry(controls, textvariable=self.symbol_var, width=10)
        symbol_entry.grid(row=1, column=1, padx=5, sticky="w")

        change_btn = ttk.Button(controls, text="Change", command=self.change_symbol)
        change_btn.grid(row=1, column=2, padx=5)

        log_frame = ttk.Frame(self)
        log_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.log_text = tk.Text(log_frame, state="disabled", height=20, width=80)
        self.log_text.pack(fill="both", expand=True)

        handler = TextHandler(self.log_text)
        handler.setLevel(logging.INFO)
        self.logger.addHandler(handler)

    def change_symbol(self):
        symbol = self.symbol_var.get().upper()
        self.bot.set_symbol(symbol)


if __name__ == "__main__":
    app = App()
    app.mainloop()
