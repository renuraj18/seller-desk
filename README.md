# Seller Desk

Listing manager for saree sellers on **Amazon.in, Flipkart and Meesho**. It handles several firms and accounts from one saree product master.

- **Connections**: Amazon SP-API (private app, self-authorized) and Flipkart Seller API v3 (Self Access Application). Meesho works with file downloads and uploads, since it has no self-service API.
- **Inventory sync & SKU matching**: pull every listing (Amazon *All Listings* report, Flipkart listing search) or upload the panel downloads. Each listing is linked to a master product automatically (exact SKU / account prefix), by hand, or turned into a new product.
- **SEO listing content**: AI-drafted (Claude) or rule-based title, Item Highlights, bullets, description and keywords per marketplace. Amazon's 75-character title + 125-character Item Highlights limits are enforced, and an SEO score lists what to fix.
- **Keyword sets** per saree type (Kanjivaram, Banarasi, cotton…) feed the drafts.
- **Template filler**: upload the blank category template from each seller panel once. Seller Desk detects the header, maps the columns, reads the dropdown lists, fills rows for any account (SKU prefix, brand, price rule) and flags values that don't match a dropdown.
- **Per-account pricing**: markup %, add ₹, round to …9.
- Payments & P&L: next phase (database tables already exist).

Everything runs on your own PC. Data and encrypted credentials stay in the `data/` folder.

## Run it on your PC

Requirements: **Python 3.11+** ([python.org](https://www.python.org/downloads/), on Windows tick "Add Python to PATH").
Node.js is only needed if you change the screens; a built copy of the screens is included.

**Windows**: double-click `start.bat`
**Mac / Linux**: `./start.sh`

Then open http://localhost:8000. The first run installs the Python packages into a local `.venv` folder.

## First-time setup

1. **Firms & accounts**: add both firms and all six accounts. Set a SKU prefix and price rule per account if they differ.
2. **Connections & sync**:
   - *Amazon*: Seller Central (Primary User) → Apps and Services → Develop Apps → register as a private developer → add an app client with roles *Product Listing*, *Inventory and Order Tracking* (and *Finance and Accounting* for P&L later) → copy the LWA client ID and secret → **Authorize app** for each Amazon account and copy the refresh token. Paste these into Seller Desk, then click **Sync inventory**. The Amazon report takes a few minutes.
   - *Flipkart*: Seller Hub → Manage Profile → Developer Access → Create New Access → Self Access Application → paste the Application ID and secret → **Sync inventory**.
   - *Meesho*: Supplier Panel → Inventory → download → **Upload inventory file**.
3. **SKU matching**: link what didn't match automatically, or create products from those listings.
4. **Settings**: add your Anthropic API key (console.anthropic.com) for AI drafting.
5. **SEO keywords**: add a keyword set for each saree type you sell.
6. **Products**: complete attributes and images, select products → **AI draft listings** → review each marketplace tab → **Approve**.
7. **Upload templates**: upload the blank saree template from each panel → check the mapping → **Fill** → upload the file in the seller panel.

## Backups and security

- Back up the whole `data/` folder (`seller_desk.db`, `secret.key`, templates, exports).
- `secret.key` decrypts your saved marketplace credentials. Keep it with the database, never commit it. `.gitignore` already excludes `data/`.
- The app listens on `127.0.0.1` only. It has no login, so don't expose it to the internet as it is.

## Developing

```bash
# backend
cd backend && pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
python -m pytest -q

# frontend (hot reload on :5173, proxies /api to :8000)
cd frontend && npm install && npm run dev
npm run build   # writes frontend/dist, served by the backend
```

Layout:

```
backend/app/
  main.py                FastAPI app, serves frontend/dist
  schema.sql             SQLite schema (incl. phase-2 orders / settlements / expenses)
  fields.py              saree fields + template-header synonyms used for auto-mapping
  routers/               setup, products, listings, templates, connections, content
  services/
    marketplaces.py      Amazon SP-API + Flipkart API clients
    inventory.py         inventory files, remote listings, SKU matching
    content.py           rule-based content, marketplace limits, SEO check
    ai_writer.py         Claude drafting + rule enforcement + saved drafts
    template_filler.py   template analysis, dropdown reading, filling
    pricing.py           per-account price / SKU
    secrets.py           Fernet encryption of credentials and API key
frontend/src/            React + TypeScript screens
```
