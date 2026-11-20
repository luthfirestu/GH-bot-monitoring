cd C:\Users\ASUS\Documents\gh_bot

$startSh = @"
#!/usr/bin/env bash
set -e

uvicorn web_app:app --host 0.0.0.0 --port 7860 &
python bot.py &

wait -n
exit `$?
"@ -replace "`r`n", "`n"

[System.IO.File]::WriteAllText("$PWD\start.sh", $startSh, [System.Text.UTF8Encoding]::new($false))