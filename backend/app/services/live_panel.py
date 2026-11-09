"""Read a marketplace seller panel that the user already has open in their own Chrome.

Seller Desk does this itself (not the agent), so the safety limits are enforced in code:
- only the firm's own OpenClaw browser profile is used (firms.browser_profile);
- only tabs on that marketplace's seller-panel host are read, and never account, bank, payment, tax or settings
  pages;
- it only lists tabs and takes text snapshots: it never clicks, types, navigates or opens tabs.
"""
import glob
import os
import re
import shutil
import subprocess
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from ..db import get_conn, row_to_dict

PANEL_HOST = {"meesho": "supplier.meesho.com", "flipkart": "seller.flipkart.com", "amazon": "sellercentral.amazon.in"}
BLOCKED_PATH = re.compile(r"setting|bank|payment|payout|wallet|tax|gst|invoice|password|kyc|profile|login|signin|"
                          r"/ap/|user-?management|permissions", re.I)
ANSI = re.compile(r"\x1b\[[0-9;]*m")
MAX_TABS = 4
TAB_TEXT_CHARS = 5000
CLI_TIMEOUT = 90


class LivePanelError(RuntimeError):
    pass


def _openclaw() -> list[str]:
    exe = os.environ.get("OPENCLAW_BIN") or shutil.which("openclaw")
    if not exe:  # installed with npm under nvm, not on the server's PATH
        found = sorted(glob.glob(str(Path.home() / ".nvm/versions/node/*/bin/openclaw")))
        exe = found[-1] if found else None
    if not exe:
        raise LivePanelError("The openclaw command was not found on this Mac.")
    return [exe]


def _run(args: list[str]) -> str:
    cmd = _openclaw() + args
    env = dict(os.environ)
    env["PATH"] = f"{Path(cmd[0]).parent}:{env.get('PATH', '')}"  # node lives next to openclaw under nvm
    env["NO_COLOR"] = "1"
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=CLI_TIMEOUT, env=env)
    except subprocess.TimeoutExpired:
        raise LivePanelError("Chrome took too long to answer. Check Chrome is open with remote debugging on.")
    if out.returncode != 0:
        msg = (out.stderr or out.stdout).strip().splitlines()
        err = next((l for l in msg if "Error" in l), msg[-1] if msg else "unknown error")
        err = ANSI.sub("", err)[:300]
        raise LivePanelError(f"Could not reach Chrome: {err}")
    return out.stdout


def _clean(snapshot: str) -> str:
    """Keep the page text, drop element refs and empty structure."""
    lines = []
    for line in snapshot.splitlines():
        line = re.sub(r"\s*\[ref=[^\]]*\]", "", line).rstrip()
        m = re.match(r"\s*- (\w+)(?: \"(.*)\")?", line)
        if not m or not m.group(2):
            continue
        role, text = m.group(1), m.group(2).strip()
        if role in ("image", "img") and text.lower().endswith("icon"):
            continue
        lines.append(text if role in ("statictext", "text", "paragraph") else f"[{role}] {text}")
    out, prev = [], None
    for l in lines:
        if l != prev:
            out.append(l)
        prev = l
    return "\n".join(out)


# Headline counters on the panel home pages: a label line followed by a number line.
KNOWN_FIGURES = {
    "meesho": ["Pending Orders", "Download Labels", "Out of Stock", "Low Stock", "Catalog(s) at risk",
               "Catalog(s) blocked"],
    "flipkart": ["Pending Orders", "Pending RTD", "Out of Stock", "Low Stock"],
    "amazon": ["Pending Orders", "Unshipped Orders", "Returns", "Inventory"],
}


def extract_figures(marketplace: str, text: str) -> dict:
    """Pull the panel's headline numbers out of the page text, so the agent reports only what is really there."""
    lines = text.splitlines()
    found: dict[str, str] = {}
    for i, line in enumerate(lines):
        label = re.sub(r"^\[\w+\]\s*", "", line).strip()
        m = re.match(r"^(\d[\d,]*)\s+(Catalog\(s\) (?:at risk|blocked))$", label, re.I)  # "4  Catalog(s) at risk"
        if m:
            found[m.group(2)] = m.group(1)
            continue
        if label in KNOWN_FIGURES.get(marketplace, []) and i + 1 < len(lines):
            nxt = re.sub(r"^\[\w+\]\s*", "", lines[i + 1]).strip()
            if re.fullmatch(r"\d[\d,]*", nxt) and label not in found:
                found[label] = nxt
    missing = [k for k in KNOWN_FIGURES.get(marketplace, []) if k.lower() not in {f.lower() for f in found}]
    return {"figures": found, "not_shown_on_page": missing}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def read(marketplace: str, account_id: int) -> dict:
    with get_conn() as c:
        acc = row_to_dict(c.execute(
            "SELECT a.id, a.name, a.marketplace, a.seller_id, a.store_name, a.panel_match, f.name AS firm, f.browser_profile "
            "FROM accounts a JOIN firms f ON f.id=a.firm_id WHERE a.id=?", (account_id,)).fetchone())
    if not acc or acc["marketplace"] != marketplace:
        raise ValueError(f"account {account_id} is not a {marketplace} account")
    profile = acc["browser_profile"]
    if not profile:
        raise ValueError(f"firm {acc['firm']} has no browser profile set (Seller Desk → Firms & accounts)")
    host = PANEL_HOST[marketplace]

    tabs = json.loads(_run(["browser", "--browser-profile", profile, "--json", "tabs"])).get("tabs") or []
    panel, skipped = [], 0
    for t in tabs:
        u = urlparse(t.get("url") or "")
        if u.hostname != host:
            continue  # personal tabs and other sites are never read
        if BLOCKED_PATH.search(u.path + "?" + u.query):
            skipped += 1
            continue
        panel.append(t)
    code = (acc.get("panel_match") or "").strip().lower()
    if code:  # exact: only the tab whose address carries this account's code, nothing else is read
        panel = [t for t in panel if code in (t.get("url") or "").lower()]
    if not panel:
        return {"ok": False, "account": acc["name"], "firm": acc["firm"],
                "note": f"No open {host} tab to read{' with code ' + code if code else ''}. Ask the user to open the seller panel for {acc['name']} in "
                        f"the {acc['firm']} Chrome profile (add_task)."}

    def snap(t):
        tid = t.get("suggestedTargetId") or t.get("tabId") or t.get("targetId")
        try:
            text = _clean(_run(["browser", "--browser-profile", profile, "snapshot", "--target-id", tid,
                                "--limit", "600"]))
        except LivePanelError as e:
            return {"url": t.get("url"), "error": str(e)}
        if code:
            hit = True  # chosen by its address
        else:
            names = [n for n in (acc["name"], acc.get("store_name"), acc.get("seller_id")) if n]
            hit = any(_norm(n) and _norm(n) in _norm(text) for n in names)
        return {"url": t.get("url"), "matches_account": hit, **extract_figures(marketplace, text),
                "text": text[:TAB_TEXT_CHARS]}

    with ThreadPoolExecutor(max_workers=MAX_TABS) as pool:
        pages = list(pool.map(snap, panel[:MAX_TABS]))
    matching = [p for p in pages if p.get("matches_account")]
    return {
        "ok": True, "source": "LIVE seller panel", "read_at": datetime.now().isoformat(timespec="seconds"),
        "account": acc["name"], "firm": acc["firm"],
        "note": ("Report figures from `figures` of pages with matches_account true. Anything listed in "
                 "not_shown_on_page, or not in `figures`, is NOT on the page: say 'not shown on the panel page', "
                 "never estimate it or take it from another account." if matching else
                 f"No open tab shows the account name '{acc['name']}'. Say you could not confirm which account these "
                 "pages belong to."),
        "pages": matching or pages,
        "skipped_private_pages": skipped,
    }
