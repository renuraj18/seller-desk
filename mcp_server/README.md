# Seller Desk MCP server

Lets Claude (Claude Desktop or Claude Code) do the groundwork for a new saree catalog: research the marketplace with
its own web tools, then record keywords, product attributes, SEO drafts and template mappings in Seller Desk.

It runs on your Mac and talks only to Seller Desk at `http://127.0.0.1:8000` (override with `SELLER_DESK_URL`).
Seller Desk must be running (`./start.sh`).

## Install

The MCP package is already in the project's `.venv`. On a fresh machine:

```bash
.venv/bin/pip install -r mcp_server/requirements.txt
```

## Connect

Claude Code (run in the project folder):

```bash
claude mcp add seller-desk -- /Users/renuraj/Desktop/mywork/seller-desk/.venv/bin/python /Users/renuraj/Desktop/mywork/seller-desk/mcp_server/server.py
```

Claude Desktop: add this under `mcpServers` in `~/Library/Application Support/Claude/claude_desktop_config.json`, then restart it.

```json
"seller-desk": {
  "command": "/Users/renuraj/Desktop/mywork/seller-desk/.venv/bin/python",
  "args": ["/Users/renuraj/Desktop/mywork/seller-desk/mcp_server/server.py"]
}
```

## Use

Ask Claude, for example: *"Use the new_saree_catalog prompt for Meesho: maroon Kanjivaram silk, zari border, MRP 4999."*
Claude then researches top sellers, saves a keyword set with sources, creates the product, writes and checks the SEO
content for each marketplace, maps the Excel template columns (dropdown values included) and dry-runs the fill.

## What Claude can and cannot do

| Can | Cannot |
| --- | --- |
| Read products, rules, blocked words, templates, mappings | Approve content (you do, in Seller Desk) |
| Scan a template's saved variations folder and add every new colour as a saree (photos copied, originals untouched) | Read any other folder on your Mac |
| Create sarees, and edit sarees that are not live anywhere | Edit sarees that are live or exported |
| Save keyword sets, save content as unapproved drafts | Queue or submit uploads, mark anything exported |
| Map template columns and form fields, and fill the Excel template (file saved in exports, not marked exported) | Change stock, orders or payments |
| Preview what the extension would type | Delete anything, read credentials or API keys |

Content is trimmed to marketplace limits and blocked words are swapped by Seller Desk itself when saving, so the
limits hold even if Claude gets them wrong. Field and column mappings are shared settings: check them on the
Templates page after a session.
