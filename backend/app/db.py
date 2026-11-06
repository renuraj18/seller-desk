import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DATA_DIR = Path(os.environ.get("SELLER_DESK_DATA", Path(__file__).resolve().parents[2] / "data"))
DB_PATH = DATA_DIR / "seller_desk.db"
UPLOAD_DIR = DATA_DIR / "templates"
EXPORT_DIR = DATA_DIR / "exports"

JSON_COLUMNS = {"images", "extra", "columns", "mapping", "warnings", "raw", "bullets", "issues"}


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
