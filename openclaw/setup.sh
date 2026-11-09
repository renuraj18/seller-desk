#!/usr/bin/env bash
# Set up the Meesho, Flipkart and Amazon OpenClaw agents for Seller Desk.
#
# Safe to run again: it refreshes the agents' instructions and skills, keeps their memory and USER.md, and only
# creates agents that do not exist yet.
#
#   ./openclaw/setup.sh                 # uses the default model (openrouter/openrouter/free)
#   MODEL=openrouter/auto ./openclaw/setup.sh
set -euo pipefail
cd "$(dirname "$0")"

MODEL="${MODEL:-openrouter/openrouter/free}"
STATE="${OPENCLAW_STATE_DIR:-$HOME/.openclaw}"
MARKETPLACES=(meesho flipkart amazon)

if ! command -v openclaw >/dev/null 2>&1; then
  # Installed with npm under nvm but not on this shell's PATH
  for d in "$HOME"/.nvm/versions/node/*/bin; do [ -x "$d/openclaw" ] && PATH="$d:$PATH"; done
fi
command -v openclaw >/dev/null 2>&1 || { echo "openclaw is not installed or not on PATH." >&2; exit 1; }

existing="$(openclaw agents list --json)"

for mp in "${MARKETPLACES[@]}"; do
  ws="$STATE/workspace-$mp"
  mkdir -p "$ws/skills" "$ws/memory"
  cp shared/AGENTS.md "$ws/AGENTS.md"
  cp "agents/$mp/IDENTITY.md" "agents/$mp/SOUL.md" "$ws/"
  cp -R "agents/$mp/skills/." "$ws/skills/"
  rm -f "$ws/BOOTSTRAP.md"   # the identity is set here, so skip OpenClaw's first-run ritual

  if grep -q "\"id\": \"$mp\"" <<<"$existing"; then
    echo "• $mp agent exists: instructions and skills refreshed"
  else
    openclaw agents add "$mp" --workspace "$ws" --model "$MODEL" --non-interactive
    rm -f "$ws/BOOTSTRAP.md"
    echo "• $mp agent created (model $MODEL)"
  fi
  openclaw agents set-identity --agent "$mp" --workspace "$ws" --from-identity >/dev/null
  # Work only through the Seller Desk tools. Live seller-panel reads go through Seller Desk's read_live_panel tool,
  # which enforces the limits in code, so the agents get no browser, shell, file edits or background processes.
  openclaw config set "agents.entries.$mp.tools" \
    '{"profile":"minimal","deny":["browser","exec","process","apply_patch","edit","write","gateway"]}' --strict-json >/dev/null
done

# Seller Desk talks to the agents through the gateway's OpenAI-compatible endpoint (loopback only).
openclaw config set gateway.http.endpoints.chatCompletions.enabled true --strict-json
openclaw gateway restart

echo
echo "Done. Open Seller Desk → Agents. The gateway token is read from $STATE/openclaw.json."
