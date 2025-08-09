#!/usr/bin/env bash
curl -sS "http://127.0.0.1:8000/status" | jq . || curl -sS "http://127.0.0.1:8000/status"
