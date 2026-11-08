-- Seller Desk schema. Phase 1: listings. Phase 2 tables (orders, settlements, expenses) are created now
-- so P&L can be added without migrations of existing data.

CREATE TABLE IF NOT EXISTS firms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    gstin TEXT,
    state TEXT,
    address TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    firm_id INTEGER NOT NULL REFERENCES firms(id) ON DELETE CASCADE,
    marketplace TEXT NOT NULL CHECK (marketplace IN ('amazon', 'flipkart', 'meesho')),
    name TEXT NOT NULL,
    seller_id TEXT,
    brand TEXT,                      -- brand used on this account (falls back to product brand)
    sku_prefix TEXT DEFAULT '',      -- prepended to product SKU when no marketplace SKU is set
    price_markup_pct REAL DEFAULT 0, -- default listing price = selling_price * (1 + pct/100) + price_add
    price_add REAL DEFAULT 0,
    price_round_to INTEGER DEFAULT 0,-- 0 = no rounding, 9 = end in 9 (e.g. 1249), 10 = nearest 10
    active INTEGER DEFAULT 1,
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE (firm_id, marketplace, name)
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL UNIQUE,
    parent_sku TEXT,
    name TEXT,
    brand TEXT,
    fabric TEXT,
    saree_type TEXT,
    color TEXT,
    secondary_color TEXT,
    pattern TEXT,
    work TEXT,
    border TEXT,
    pallu TEXT,
    occasion TEXT,
    saree_length_m REAL,
    blouse_piece TEXT,
    blouse_length_m REAL,
    blouse_fabric TEXT,
    blouse_color TEXT,
    wash_care TEXT,
    net_weight_g REAL,
    pkg_weight_g REAL,
    pkg_length_cm REAL,
    pkg_breadth_cm REAL,
    pkg_height_cm REAL,
    hsn TEXT,
    gst_rate REAL,
    mrp REAL,
    selling_price REAL,
    cost_price REAL,
    packaging_cost REAL,
    stock_qty INTEGER,
    country_of_origin TEXT DEFAULT 'India',
    manufacturer_details TEXT,
    packer_details TEXT,
    description TEXT,
    keywords TEXT,
    images TEXT DEFAULT '[]',        -- JSON list of image URLs
    extra TEXT DEFAULT '{}',         -- JSON for anything else
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    marketplace_sku TEXT,
    listing_ref TEXT,                -- ASIN / FSN / Meesho catalog or product id
    price REAL,                      -- override; NULL = use account price rule
    mrp REAL,
    stock_qty INTEGER,
    title_override TEXT,
    status TEXT DEFAULT 'draft' CHECK (status IN ('draft', 'exported', 'live', 'inactive', 'rejected')),
    last_exported_at TEXT,
    notes TEXT,
    UNIQUE (product_id, account_id)
);

CREATE TABLE IF NOT EXISTS template_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    marketplace TEXT NOT NULL CHECK (marketplace IN ('amazon', 'flipkart', 'meesho')),
    original_filename TEXT,
    stored_path TEXT NOT NULL,
    sheet_name TEXT,
    header_row INTEGER,
    data_start_row INTEGER,
    columns TEXT DEFAULT '[]',       -- JSON: [{index, letter, header, allowed:[...]}]
    mapping TEXT DEFAULT '{}',       -- JSON: {letter: {source, value, value_map}}
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS exports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER REFERENCES template_profiles(id) ON DELETE SET NULL,
    account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
    product_count INTEGER,
    file_path TEXT,
    warnings TEXT DEFAULT '[]',
    created_at TEXT DEFAULT (datetime('now'))
);

-- ---------- Connections, inventory sync, SEO content ----------
CREATE TABLE IF NOT EXISTS account_credentials (
    account_id INTEGER PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
    secret TEXT NOT NULL,            -- Fernet-encrypted JSON (client id/secret/refresh token)
    last_test_at TEXT,
    last_test_ok INTEGER,
    last_test_message TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT,                      -- encrypted when the key ends with _secret
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Raw listings as they exist on the marketplace (from API or downloaded file)
CREATE TABLE IF NOT EXISTS remote_listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    remote_sku TEXT NOT NULL,
    listing_ref TEXT,                -- ASIN / FSN / Meesho catalog or product id
    listing_id TEXT,                 -- Amazon listing-id / Flipkart listingId
    title TEXT,
    price REAL,
    mrp REAL,
    stock INTEGER,
    status TEXT,
    image TEXT,
    raw TEXT DEFAULT '{}',
    product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
    match_method TEXT,               -- exact / prefix / manual / created
    source TEXT,                     -- api / file
    synced_at TEXT DEFAULT (datetime('now')),
    UNIQUE (account_id, remote_sku)
);

CREATE TABLE IF NOT EXISTS sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER REFERENCES accounts(id) ON DELETE CASCADE,
    kind TEXT,                       -- inventory_api / inventory_file
    status TEXT,                     -- running / done / failed
    message TEXT,
    row_count INTEGER,
    started_at TEXT DEFAULT (datetime('now')),
    finished_at TEXT
);

-- Keyword sets per saree type, reused for every product of that type
CREATE TABLE IF NOT EXISTS keyword_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,       -- e.g. "Kanjivaram silk"
    match_terms TEXT,                -- comma list matched against fabric/type, e.g. "kanjivaram,kanchipuram"
    primary_keywords TEXT,
    secondary_keywords TEXT,
    long_tail TEXT,
    notes TEXT
);

-- Saved listing content per product + marketplace (AI draft or rules), editable before export
CREATE TABLE IF NOT EXISTS content_drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    marketplace TEXT NOT NULL,
    title TEXT,
    highlights TEXT,
    bullets TEXT DEFAULT '[]',
    description TEXT,
    search_terms TEXT,
    source TEXT,                     -- ai / rules / manual
    approved INTEGER DEFAULT 0,
    score INTEGER,
    issues TEXT DEFAULT '[]',
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE (product_id, marketplace)
);

-- Fields taught in the browser extension, per marketplace form (shared by all accounts/firms)
CREATE TABLE IF NOT EXISTS form_fields (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    marketplace TEXT NOT NULL,
    label_norm TEXT NOT NULL,        -- normalised label text of the form field
    label TEXT,
    source TEXT,                     -- '' = ignore this field
    value TEXT,                      -- for const.custom
    value_map TEXT DEFAULT '{}',
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE (marketplace, label_norm)
);

-- Words a marketplace rejects (brand / restricted look-alikes), swapped or removed in generated listing text
CREATE TABLE IF NOT EXISTS blocked_terms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    marketplace TEXT NOT NULL DEFAULT 'all',     -- amazon / flipkart / meesho / all
    term TEXT NOT NULL,
    replacement TEXT DEFAULT '',                 -- '' = just remove the word
    note TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE (marketplace, term)
);

-- One row per "learn from a live listing" session (the one-time mapping activity, repeated when a form changes)
CREATE TABLE IF NOT EXISTS learn_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    marketplace TEXT NOT NULL,
    product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
    account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
    fields_seen INTEGER DEFAULT 0,
    fields_saved INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

-- ---------- Phase 2: payments and P&L ----------
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    order_id TEXT NOT NULL,
    sub_order_id TEXT,
    order_date TEXT,
    sku TEXT,
    product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
    qty INTEGER DEFAULT 1,
    sale_amount REAL,
    status TEXT,                     -- delivered / rto / customer_return / cancelled / ...
    raw TEXT,
    UNIQUE (account_id, order_id, sub_order_id)
);

CREATE TABLE IF NOT EXISTS settlements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    order_id TEXT,
    sub_order_id TEXT,
    settlement_date TEXT,
    txn_type TEXT,
    gross_amount REAL DEFAULT 0,
    commission REAL DEFAULT 0,
    shipping_fee REAL DEFAULT 0,
    fixed_fee REAL DEFAULT 0,
    other_fees REAL DEFAULT 0,
    gst_on_fees REAL DEFAULT 0,
    tcs REAL DEFAULT 0,
    tds REAL DEFAULT 0,
    net_payout REAL DEFAULT 0,
    source_file TEXT,
    raw TEXT
);

CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    firm_id INTEGER REFERENCES firms(id) ON DELETE CASCADE,
    account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
    expense_date TEXT NOT NULL,
    category TEXT NOT NULL,          -- ads, packaging, salary, rent, photoshoot, ...
    amount REAL NOT NULL,
    note TEXT
);

CREATE INDEX IF NOT EXISTS idx_listings_account ON listings(account_id);
CREATE INDEX IF NOT EXISTS idx_orders_account_date ON orders(account_id, order_date);
CREATE INDEX IF NOT EXISTS idx_settlements_account_date ON settlements(account_id, settlement_date);
