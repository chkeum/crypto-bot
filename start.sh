cd ~/crypto-bot
source .venv/bin/activate
uvicorn bot.main:app --host 127.0.0.1 --port 8000
