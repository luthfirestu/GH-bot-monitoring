cd C:\Users\ASUS\Documents\gh_bot

$startSh = @"
#!/bin/sh
set -e

APP_PORT="${PORT:-7860}"
uvicorn web_app:app --host 0.0.0.0 --port "$APP_PORT" &
python bot.py &

wait -n
"@ -replace "`r`n", "`n"

[System.IO.File]::WriteAllText("$PWD\start.sh", $startSh, [System.Text.UTF8Encoding]::new($false))