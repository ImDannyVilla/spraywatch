#!/bin/sh
# Create the `spraywatch` NemoClaw sandbox, on the host. Run once.
#
# - Inference: the Qwen that NemoClaw already runs (nemoclaw-vllm), attached as an
#   existing server, so the model isn't restarted.
# - Policy: the Restricted tier with no optional presets, plus our own
#   `spraywatch-slack-post`: Python may POST chat.postMessage (and auth.test) to
#   slack.com, nothing else on Slack. The stock `slack` preset is left off: it's
#   for OpenClaw's Socket Mode, and OpenShell refuses two rules for slack.com:443.
# - Mounts, both read-only: this repo at /sandbox/spraywatch/app, and the farm's
#   inbox at /sandbox/spraywatch/inbox. State (SQLite, the queue) stays inside, in
#   /sandbox/spraywatch-state (the mounts' parent folder isn't writable).
# - Slack: the bot token is registered with the OpenShell gateway as
#   SPRAYWATCH_SLACK_BOT_TOKEN. The sandbox only ever sees a placeholder; the
#   gateway puts the token in at egress. No Socket Mode and no second OpenClaw Slack
#   channel: one sandbox per gateway may hold a bot's Socket Mode connection.
#
# Needs ~/spraywatch-input/slack.env (chmod 600), never in git:
#   SPRAYWATCH_SLACK_BOT_TOKEN=xoxb-...
#   SLACK_CHANNEL=C...   (or the channel's name; invite the bot to it)
set -eu

# Run as group docker, not only with it as a supplementary group: the gateway runs as
# group docker, and preflight can only see its listener on port 8080 from a process
# with the same group (.agents/lessons/2026-10-25_onboard-needs-sg-docker.md).
[ "${SPRAYWATCH_UNDER_SG:-}" = 1 ] || SPRAYWATCH_UNDER_SG=1 exec sg docker -c "SPRAYWATCH_UNDER_SG=1 sh $0 $*"

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
    # NemoClaw's endpointless placeholder profile (the one its Slack bridges use): resolved at egress.
    nemoclaw credentials add spraywatch-slack --type nemoclaw-mcp-v1 --credential SPRAYWATCH_SLACK_BOT_TOKEN
fi

NEMOCLAW_PROVIDER=vllm \
NEMOCLAW_POLICY_TIER=restricted NEMOCLAW_POLICY_MODE=custom NEMOCLAW_POLICY_PRESETS= \
nemoclaw onboard --non-interactive --fresh --name spraywatch --no-sandbox-gpu \
    --yes-i-accept-third-party-software \
    --host-mount "$REPO:/sandbox/spraywatch/app" \
    --host-mount "$FARM/inbox:/sandbox/spraywatch/inbox"

# The token placeholder comes from this provider, and only for slack.com via our preset.
openshell sandbox provider attach spraywatch spraywatch-slack || true
nemoclaw spraywatch policy add --from-file "$REPO/scripts/nemoclaw/spraywatch-slack-post.yaml" --yes
# A restart puts the placeholder in the sandbox's environment.
nemoclaw spraywatch stop && nemoclaw spraywatch start

# The channel isn't a secret; the sandbox reads it from its state folder.
nemoclaw spraywatch exec --no-tty -- sh -c "mkdir -p /sandbox/spraywatch-state && printf '%s\n' '$SLACK_CHANNEL' > /sandbox/spraywatch-state/slack-channel"
echo "onboard: done. Start it with: nemoclaw spraywatch exec --no-tty -- sh /sandbox/spraywatch/app/scripts/nemoclaw/start.sh"
