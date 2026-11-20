#!/bin/sh
set -e

APP_PORT="${PORT:-7860}"
uvicorn web_app:app --host 0.0.0.0 --port "$APP_PORT" &
python bot.py &

wait -n