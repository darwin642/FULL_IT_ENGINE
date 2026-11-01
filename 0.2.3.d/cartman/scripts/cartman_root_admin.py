#!/usr/bin/env python3
"""Manage Cartman ROOT principals from the local project console."""
import getpass, json, sqlite3, sys, uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "app" / "cartman.db"

def main():
    if not DB.is_file() or DB.is_symlink():
        raise SystemExit("Cartman database missing or unsafe.")
    if len(sys.argv) < 2 or sys.argv[1] not in {"list", "grant", "revoke"}:
        raise SystemExit("Usage: python scripts/cartman_root_admin.py list | grant <existing-admin-username> | revoke <root-username>")
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS cartman_root_principals (username TEXT PRIMARY KEY COLLATE NOCASE, granted_at TEXT NOT NULL, granted_by TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)))")
        action = sys.argv[1]
        if action == "list":
            for row in conn.execute("SELECT username,granted_at,granted_by,enabled FROM cartman_root_principals ORDER BY username"):
                print(dict(row))
            return
        if len(sys.argv) < 3 or not sys.argv[2].strip():
            raise SystemExit("A username is required.")
        username = sys.argv[2].strip()
        now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        grant_actor = "local console:" + getpass.getuser()
        if action == "grant":
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "auth_accounts" not in tables:
                raise SystemExit("auth_accounts table not found.")
            cols = {r[1] for r in conn.execute("PRAGMA table_info(auth_accounts)")}
            user_col = next((x for x in ("username", "login", "email", "account_name") if x in cols), None)
            role_col = next((x for x in ("role", "role_name") if x in cols), None)
            if not user_col or not role_col:
                raise SystemExit("Could not identify account username/role columns.")
            row = conn.execute(f'SELECT * FROM auth_accounts WHERE "{user_col}"=? COLLATE NOCASE', (username,)).fetchone()
            if not row:
                raise SystemExit("Account does not exist.")
            role = str(row[role_col] or "").strip().lower().replace("-", "_").replace(" ", "_")
            if role not in {"admin", "administrator", "it_admin", "it_administrator"}:
                raise SystemExit("Only an existing administrator can be granted ROOT.")
            keys = set(row.keys())
            for flag in ("is_active", "active", "enabled"):
                if flag in keys and row[flag] in (0, False, "0", "false", "False"):
                    raise SystemExit("Cannot grant ROOT to a disabled account.")
            if "status" in keys and str(row["status"] or "").strip().lower() not in {"active", "enabled", "1", "true"}:
                raise SystemExit("Cannot grant ROOT to an inactive account.")
            print("Grant ROOT access to:", username)
            if input("Type GRANT ROOT to confirm: ").strip() != "GRANT ROOT":
                raise SystemExit("Cancelled.")
            conn.execute("INSERT INTO cartman_root_principals(username,granted_at,granted_by,enabled) VALUES(?,?,?,1) ON CONFLICT(username) DO UPDATE SET granted_at=excluded.granted_at,granted_by=excluded.granted_by,enabled=1", (username, now, grant_actor))
            action_name = "iam.root.granted"
        else:
            active_count = conn.execute("SELECT COUNT(*) FROM cartman_root_principals WHERE enabled=1").fetchone()[0]
            row = conn.execute("SELECT enabled FROM cartman_root_principals WHERE username=? COLLATE NOCASE", (username,)).fetchone()
            if not row or not row[0]:
                raise SystemExit("ROOT principal not found or already disabled.")
            if active_count <= 1:
                raise SystemExit("Cannot revoke the last ROOT principal.")
            if input("Type REVOKE ROOT to confirm: ").strip() != "REVOKE ROOT":
                raise SystemExit("Cancelled.")
            conn.execute("UPDATE cartman_root_principals SET enabled=0 WHERE username=? COLLATE NOCASE", (username,))
            action_name = "iam.root.revoked"
        conn.execute("CREATE TABLE IF NOT EXISTS iam_audit_events (id TEXT PRIMARY KEY,actor TEXT NOT NULL DEFAULT 'Unattributed',action TEXT NOT NULL,resource_type TEXT NOT NULL,resource_id TEXT NOT NULL DEFAULT '',details_json TEXT NOT NULL DEFAULT '{}',occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("INSERT INTO iam_audit_events (id,actor,action,resource_type,resource_id,details_json,occurred_at) VALUES (?,?,?,?,?,?,?)", (uuid.uuid4().hex, grant_actor, action_name, "auth_account", username, json.dumps({"source":"local console"}), now))
        conn.commit()
        print("ROOT updated. Restart Cartman to refresh authenticated sessions.")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
