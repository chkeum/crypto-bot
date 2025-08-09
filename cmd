cd ~/crypto-bot
source .venv/bin/activate
uvicorn bot.main:app --host 127.0.0.1 --port 8000

# 헬스
curl -s http://127.0.0.1:8000/health

# 포지션(기본 STRAT_SYMBOLS)
curl -s "http://127.0.0.1:8000/status"

# 포지션(지정 심볼)
curl -s "http://127.0.0.1:8000/status?symbols=BTC/USDT,ETH/USDT"

# 미체결 주문
curl -s "http://127.0.0.1:8000/orders?symbol=BTC/USDT"

# ip 확인
curl ifconfig.me
