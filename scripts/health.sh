#!/usr/bin/env bash
set -e
curl -sS http://127.0.0.1:8000/health | jq . || curl -sS http://127.0.0.1:8000/health
