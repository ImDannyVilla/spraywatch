#!/bin/sh
# Start SprayWatch inside the `spraywatch` sandbox: the watcher (inbox, then the check, every 10 s)
# and the local page on 127.0.0.1:8091. Run it again after a `git pull` on the host.
#   nemoclaw spraywatch exec --no-tty -- sh /sandbox/spraywatch/app/scripts/nemoclaw/start.sh
# Then, on the host: openshell forward start --background 8091 spraywatch
set -eu

APP=/sandbox/spraywatch/app
STATE=/sandbox/spraywatch/state
mkdir -p "$STATE"

export SPRAYWATCH_DB="$STATE/spraywatch.db"
export SPRAYWATCH_QUEUE="$STATE/queue"
export SPRAYWATCH_INBOX=/sandbox/spraywatch/inbox
export PYTHONDONTWRITEBYTECODE=1   # the app mount is read-only
# NemoClaw's route to the shared Qwen; the token is the gateway's placeholder, resolved at egress.
export MODEL_URL="${MODEL_URL:-http://host.openshell.internal:8000/v1}"
export MODEL_NAME="${MODEL_NAME:-nvidia/Qwen3.6-35B-A3B-NVFP4}"
export MODEL_API_KEY="${NEMOCLAW_LOCAL_INFERENCE_TOKEN:-}"
# A placeholder too: the real token never enters the sandbox.
export SLACK_BOT_TOKEN="${SPRAYWATCH_SLACK_BOT_TOKEN:-}"
SLACK_CHANNEL="$(cat "$STATE/slack-channel" 2>/dev/null || true)"
export SLACK_CHANNEL

for name in watch server; do
    pid="$STATE/$name.pid"
    if [ -f "$pid" ] && kill -0 "$(cat "$pid")" 2>/dev/null; then
        kill "$(cat "$pid")"
        sleep 1
    fi
done
nohup python3 "$APP/agent/watch.py" >> "$STATE/watch.log" 2>&1 &
echo $! > "$STATE/watch.pid"
nohup python3 "$APP/evidence/server.py" >> "$STATE/page.log" 2>&1 &
echo $! > "$STATE/server.pid"
sleep 2
tail -n 3 "$STATE/watch.log" "$STATE/page.log"
[ -n "$SLACK_BOT_TOKEN" ] && [ -n "$SLACK_CHANNEL" ] || echo "start: Slack isn't set; cards wait until it is"
