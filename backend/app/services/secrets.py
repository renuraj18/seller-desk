"""Local encryption for marketplace credentials and API keys.

A key is generated on first run at data/secret.key (keep it out of git and back it up with the
database). SELLER_DESK_KEY env var overrides it.
"""

import json
import os

from cryptography.fernet import Fernet, InvalidToken

from ..db import DATA_DIR, get_conn

KEY_FILE = DATA_DIR / "secret.key"


def _fernet() -> Fernet:
    key = os.environ.get("SELLER_DESK_KEY")
    if not key:
        if not KEY_FILE.exists():
            KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
            KEY_FILE.write_bytes(Fernet.generate_key())
            try:
                os.chmod(KEY_FILE, 0o600)
            except OSError:
                pass
        key = KEY_FILE.read_bytes().strip()
    return Fernet(key if isinstance(key, bytes) else key.encode())


def encrypt(data: dict | str) -> str:
    raw = json.dumps(data) if isinstance(data, dict) else data
    return _fernet().encrypt(raw.encode()).decode()


def decrypt(token: str):
    try:
        raw = _fernet().decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise RuntimeError("Could not decrypt saved credentials — was data/secret.key changed?") from e
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def mask(value: str | None) -> str:
    if not value:
        return ""
    v = str(value)
    return "•" * 6 + v[-4:] if len(v) > 6 else "•" * len(v)


# ---- account credentials

def save_credentials(account_id: int, creds: dict):
    existing = get_credentials(account_id) or {}
    # empty fields in the form mean "keep what's saved"
    merged = {**existing, **{k: v for k, v in creds.items() if v not in (None, "")}}
    with get_conn() as c:
        c.execute("INSERT INTO account_credentials (account_id, secret) VALUES (?,?) "
                  "ON CONFLICT(account_id) DO UPDATE SET secret=excluded.secret", (account_id, encrypt(merged)))


def get_credentials(account_id: int) -> dict | None:
    with get_conn() as c:
        row = c.execute("SELECT secret FROM account_credentials WHERE account_id=?", (account_id,)).fetchone()
    return decrypt(row["secret"]) if row else None


def delete_credentials(account_id: int):
    with get_conn() as c:
        c.execute("DELETE FROM account_credentials WHERE account_id=?", (account_id,))


def record_test(account_id: int, ok: bool, message: str):
    with get_conn() as c:
        c.execute("UPDATE account_credentials SET last_test_at=datetime('now'), last_test_ok=?, "
                  "last_test_message=? WHERE account_id=?", (int(ok), message[:500], account_id))


# ---- app settings (e.g. Anthropic API key)

def set_setting(key: str, value: str | None):
    stored = encrypt(value) if (value and key.endswith("_secret")) else value
    with get_conn() as c:
        c.execute("INSERT INTO settings (key, value, updated_at) VALUES (?,?,datetime('now')) "
                  "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at", (key, stored))


def get_setting(key: str, default=None):
    with get_conn() as c:
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    if not row or row["value"] in (None, ""):
        return default
    return decrypt(row["value"]) if key.endswith("_secret") else row["value"]
