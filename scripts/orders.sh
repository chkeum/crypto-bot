#!/usr/bin/env bash
sym="${1:-ETH/USDT:USDT}"
curl -sS "http://127.0.0.1:8000/orders?symbol=${sym}" | jq . || curl -sS "http://127.0.0.1:8000/orders?symbol=${sym}"
