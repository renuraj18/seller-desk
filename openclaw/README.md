# OpenClaw marketplace agents

Seller Desk has one OpenClaw agent per marketplace: `meesho`, `flipkart` and `amazon`. Each agent has its own
workspace, memory and playbook skill, and only sees its own marketplace's data.

```
Seller Desk (Agents page)
   │  POST /api/agents/{marketplace}/chat
   ▼
Seller Desk backend ── app/services/agents.py
   │  POST http://127.0.0.1:18789/v1/chat/completions   model = openclaw/<marketplace>
   │  + Seller Desk tools (get_overview, get_orders, ..., propose_*)
   ▼
OpenClaw gateway ── agent workspace-<marketplace> (AGENTS.md, SOUL.md, skills/<marketplace>-seller)
   │  model: openrouter/openrouter/free
   ▲
   └─ tool calls come back to Seller Desk, which runs them on its own database and returns the results
```

## Setup

```bash
./openclaw/setup.sh
```

The script copies the files in this folder into `~/.openclaw/workspace-<marketplace>`, creates any agent that
is missing, enables the gateway's chat endpoint and restarts the gateway. Run it again after editing the files
here. It keeps each agent's `memory/` and `USER.md`.

Seller Desk reads the gateway token from `~/.openclaw/openclaw.json` at request time and does not store it.
Override with `OPENCLAW_GATEWAY_URL`, `OPENCLAW_GATEWAY_TOKEN` or `OPENCLAW_CONFIG` if needed.

## What agents can do

- **Read** (scoped to their marketplace): overview, orders, stock mismatches, listings, products.
- **Propose**: master stock, listing status, listing content, or a to-do for the user. Proposals wait on the
  Agents page; nothing changes until the user approves. Content proposals are trimmed to the marketplace limits
  and blocked words are removed, both when proposed and again when approved.
- **Check live** (read only): ask Seller Desk to read the account's seller-panel tab open in your Chrome, when you
  ask for live figures or Seller Desk data is more than a day old. They have no browser of their own and never
  handle passwords, OTPs or customer details.

## Live checks in your real Chrome

The agents read each firm's seller panels in your own Chrome, using the Chrome profile you already sign in with
for that firm (Shanthi Tex → Chrome "Shanthi Tex", Key2Global Exim → Chrome "key2global").

1. Create one OpenClaw profile per firm that attaches to your Chrome (already done for these two firms):

   ```bash
   openclaw browser create-profile --name chrome-shanthi-tex --driver existing-session --user-data-dir "$HOME/Library/Application Support/Google/Chrome"
   openclaw browser create-profile --name chrome-key2global --driver existing-session --user-data-dir "$HOME/Library/Application Support/Google/Chrome"
   ```

2. In Chrome open `chrome://inspect/#remote-debugging` and switch on **Allow remote debugging for this browser
   instance**. Approve Chrome's prompt when an agent attaches.
3. In each firm's Chrome profile, sign in to every account's seller panel and leave those tabs open.
4. In Seller Desk → Firms & accounts → Edit firm, set **Agent browser profile** to `chrome-shanthi-tex` or
   `chrome-key2global`.

The agents have no browser. When they need live figures they call Seller Desk's `read_live_panel` tool, and
Seller Desk reads the panel itself (`backend/app/services/live_panel.py`). That code:

- uses only the firm's own profile and only tabs on the marketplace's seller-panel host;
- skips account, bank, payment, tax and settings pages;
- only lists tabs and takes text snapshots: no clicks, typing, navigation or new tabs;
- marks which page shows the account's name, so figures from another account are not reported as this one's.

Both profiles reach the same Chrome, so pages are matched to accounts by the account name on the page. Remote
debugging still gives OpenClaw access to all of Chrome: switch it off when you are not using live checks.

Do not delete these profiles with `openclaw browser delete-profile`: they point at your real Chrome data folder.
Remove them from `browser.profiles` in `~/.openclaw/openclaw.json` instead.

## Files

| File | Becomes |
| --- | --- |
| `shared/AGENTS.md` | `AGENTS.md` in every agent workspace: tools, red lines, answer style |
| `agents/<mp>/IDENTITY.md`, `SOUL.md` | The agent's identity and tone |
| `agents/<mp>/skills/<mp>-seller/SKILL.md` | Marketplace playbook: daily check, content rules |
