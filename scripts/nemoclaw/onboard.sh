#!/bin/sh
# Create the `spraywatch` NemoClaw sandbox next to ClearFrame's, on the host. Run once.
#
# - Inference: the Qwen that NemoClaw already runs (nemoclaw-vllm), attached as an
#   existing server, so the model isn't restarted and ClearFrame keeps working.
# - Policy: the Restricted tier, plus only the `slack` preset. The sandbox reaches
#   the local model and Slack's API, nothing else.
# - Mounts, both read-only: this repo at /sandbox/spraywatch/app, and the farm's
#   inbox at /sandbox/spraywatch/inbox. State (SQLite, the queue) stays inside.
# - Slack: the bot token is registered with the OpenShell gateway as
#   SPRAYWATCH_SLACK_BOT_TOKEN. The sandbox only ever sees a placeholder; the
#   gateway puts the token in at egress. No Socket Mode and no second OpenClaw Slack
#   channel, so it doesn't clash with ClearFrame's bot.
#
# Needs ~/spraywatch-input/slack.env (chmod 600), never in git:
#   SPRAYWATCH_SLACK_BOT_TOKEN=xoxb-...
#   SLACK_CHANNEL=C...   (or the channel's name; invite the bot to it)
set -eu

# NemoClaw needs the docker group in this process (.agents/lessons in ClearFrame).
id -nG | grep -qw docker || exec sg docker -c "sh $0 $*"

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
FARM="${SPRAYWATCH_FARM:-$HOME/spraywatch-farm}"
SECRETS="${SPRAYWATCH_SECRETS:-$HOME/spraywatch-input/slack.env}"
export NODE_NO_WARNINGS=1

[ -f "$SECRETS" ] || { echo "onboard: $SECRETS is missing (SPRAYWATCH_SLACK_BOT_TOKEN, SLACK_CHANNEL)" >&2; exit 1; }
[ "$(stat -c %a "$SECRETS")" = 600 ] || { echo "onboard: chmod 600 $SECRETS first" >&2; exit 1; }
set -a; . "$SECRETS"; set +a
: "${SPRAYWATCH_SLACK_BOT_TOKEN:?not set in $SECRETS}"
: "${SLACK_CHANNEL:?not set in $SECRETS}"
# A channel ID (C0123ABCD) or a channel name (spraywatch); chat.postMessage takes either.
case "$SLACK_CHANNEL" in
    *[!A-Za-z0-9_-]*|"") echo "onboard: SLACK_CHANNEL must be a channel ID or a plain channel name" >&2; exit 1 ;;
esac

mkdir -p "$FARM/inbox"
cp ~/.nemoclaw/sandboxes.json ~/.nemoclaw/sandboxes.json.before-spraywatch
[ -f ~/.nemoclaw/onboard-session.json ] && cp ~/.nemoclaw/onboard-session.json ~/.nemoclaw/onboard-session.json.before-spraywatch

if ! nemoclaw credentials list 2>/dev/null | grep -q spraywatch-slack; then
    nemoclaw credentials add spraywatch-slack --type generic --credential SPRAYWATCH_SLACK_BOT_TOKEN
fi

NEMOCLAW_PROVIDER=vllm \
NEMOCLAW_POLICY_TIER=restricted NEMOCLAW_POLICY_MODE=custom NEMOCLAW_POLICY_PRESETS=slack \
nemoclaw onboard --non-interactive --fresh --name spraywatch --no-sandbox-gpu \
    --yes-i-accept-third-party-software \
    --host-mount "$REPO:/sandbox/spraywatch/app" \
    --host-mount "$FARM/inbox:/sandbox/spraywatch/inbox"

# The channel isn't a secret; the sandbox reads it from its state folder.
nemoclaw spraywatch exec --no-tty -- sh -c "mkdir -p /sandbox/spraywatch/state && printf '%s\n' '$SLACK_CHANNEL' > /sandbox/spraywatch/state/slack-channel"
echo "onboard: done. Start it with: nemoclaw spraywatch exec --no-tty -- sh /sandbox/spraywatch/app/scripts/nemoclaw/start.sh"
