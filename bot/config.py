import os
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

START_MODE = os.getenv("START_MODE", "PAPER").upper()
WEBHOOK_TOKEN = os.getenv("WEBHOOK_TOKEN", "")
EXCHANGE_ID = os.getenv("EXCHANGE_ID", "binanceusdm")
IS_TESTNET = os.getenv("IS_TESTNET", "true").lower() in ["1", "true", "yes"]
API_KEY = os.getenv("API_KEY", "")
API_SECRET = os.getenv("API_SECRET", "")
DEFAULT_LEVERAGE = int(os.getenv("DEFAULT_LEVERAGE", "5"))


def _b(v, default=False):
    if v is None:
        return default
    return str(v).lower() in ["1", "true", "yes", "y", "on"]


# 내부전략
STRAT_ENABLE = _b(os.getenv("STRAT_ENABLE", "false"))
DATA_EXCHANGE_ID = os.getenv("DATA_EXCHANGE_ID", "binanceusdm")
DATA_IS_TESTNET = _b(os.getenv("DATA_IS_TESTNET", "false"))
STRAT_SYMBOLS = os.getenv("STRAT_SYMBOLS", "BTC/USDT")
STRAT_TIMEFRAME = os.getenv("STRAT_TIMEFRAME", "5m")
STRAT_QTY_USD = float(os.getenv("STRAT_QTY_USD", "100"))
STRAT_LEVERAGE = int(os.getenv("STRAT_LEVERAGE", "5"))
STRAT_EMA_FAST = int(os.getenv("STRAT_EMA_FAST", "20"))
STRAT_EMA_SLOW = int(os.getenv("STRAT_EMA_SLOW", "60"))
STRAT_ATR_LEN = int(os.getenv("STRAT_ATR_LEN", "14"))
STRAT_ATR_MA_LEN = int(os.getenv("STRAT_ATR_MA_LEN", "20"))
STRAT_ATR_MULT = float(os.getenv("STRAT_ATR_MULT", "1.5"))
STRAT_BREAKOUT_LEN = int(os.getenv("STRAT_BREAKOUT_LEN", "20"))
STRAT_VOLMA_LEN = int(os.getenv("STRAT_VOLMA_LEN", "5"))
STRAT_VOL_MULT = float(os.getenv("STRAT_VOL_MULT", "1.5"))
STRAT_POLL_SEC = int(os.getenv("STRAT_POLL_SEC", "5"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
STRAT_LOG_EVERY_BAR = _b(os.getenv("STRAT_LOG_EVERY_BAR", "false"))

# 상위 타임프레임/추세 필터
CONFIRM_TF = os.getenv("CONFIRM_TF", "1h")
HTF_EMA_FAST = int(os.getenv("HTF_EMA_FAST", "50"))
HTF_EMA_SLOW = int(os.getenv("HTF_EMA_SLOW", "200"))

# 사이징
POSITION_SIZING = os.getenv("POSITION_SIZING", "RISK").upper()  # RISK / FIXED_USD
RISK_USD = float(os.getenv("RISK_USD", "10"))
MIN_BASE_QTY = float(os.getenv("MIN_BASE_QTY", "0.0001"))

# 브래킷(OCO 에뮬)
BRACKET_ENABLE = _b(os.getenv("BRACKET_ENABLE", "true"))
BRACKET_TP_RR = float(os.getenv("BRACKET_TP_RR", "2.0"))
BRACKET_TP_AS_MARKET = _b(os.getenv("BRACKET_TP_AS_MARKET", "true"))
BRACKET_WORKING_TYPE = os.getenv("BRACKET_WORKING_TYPE", "MARK_PRICE")

# 로거
logger.remove()
logger.add(lambda msg: print(msg, end=""), level=LOG_LEVEL)
