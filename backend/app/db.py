import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DATA_DIR = Path(os.environ.get("SELLER_DESK_DATA", Path(__file__).resolve().parents[2] / "data"))
DB_PATH = DATA_DIR / "seller_desk.db"
UPLOAD_DIR = DATA_DIR / "templates"
EXPORT_DIR = DATA_DIR / "exports"

JSON_COLUMNS = {"images", "extra", "columns", "mapping", "warnings", "raw", "bullets", "issues", "value_map", "payload", "tools"}


def init_dirs():
    for d in (DATA_DIR, UPLOAD_DIR, EXPORT_DIR):
        d.mkdir(parents=True, exist_ok=True)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_conn():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    init_dirs()
    schema = (Path(__file__).parent / "schema.sql").read_text()
    with get_conn() as conn:
        conn.executescript(schema)
        migrate(conn)


# columns added after the first release: (table, column, definition)
MIGRATIONS = [
    ("accounts", "store_name", "TEXT"),
    ("firms", "pincode", "TEXT"),
    ("accounts", "return_price_less", "REAL DEFAULT 30"),
    ("form_fields", "origin", "TEXT DEFAULT 'taught'"),
    ("form_fields", "sample", "TEXT"),
    ("orders", "status_text", "TEXT"),
    ("orders", "cancel_charges", "REAL"),
    ("orders", "return_charges", "REAL"),
    ("orders", "awb", "TEXT"),
    ("orders", "source", "TEXT"),
    ("orders", "updated_at", "TEXT"),
    ("firms", "browser_profile", "TEXT"),
    ("orders", "stock_effect", "INTEGER"),     # units this order has taken out of master stock (NULL = not tracked)
    ("orders", "first_seen_at", "TEXT"),
    ("upload_jobs", "detail", "TEXT"),          # JSON: what the extension could not fill, for fixing the portal's form
    ("product_templates", "variations_dir", "TEXT"),   # folder on this PC holding the colour variations of a design
    ("sync_pages", "kind", "TEXT DEFAULT 'orders'"),   # orders = daily order read, stock = inventory page the extension pushes stock to
    ("listings", "catalog_no", "INTEGER"),     # which catalog of a design this listing sits in (Meesho allows 9 per catalog)
    ("accounts", "add_catalog_url", "TEXT"),   # the portal's add-catalog page, taught through the extension
    ("accounts", "panel_match", "TEXT"),      # text unique to this account's seller-panel address, e.g. 3ylgo   # OpenClaw browser profile signed in to this firm's seller panels
]


def migrate(conn):
    for table, col, definition in MIGRATIONS:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if col not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")


def row_to_dict(row) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    for k in JSON_COLUMNS & d.keys():
        if isinstance(d[k], str):
            try:
                d[k] = json.loads(d[k])
            except json.JSONDecodeError:
                pass
    return d


def rows_to_dicts(rows) -> list[dict]:
    return [row_to_dict(r) for r in rows]


def dump(value):
    """Serialise JSON columns before writing."""
    return json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value
