from pathlib import Path
from datetime import datetime
import shutil
import os
import re
import py_compile

ROOT = Path.cwd()
API = ROOT / "app" / "reports_api.py"
HTML = ROOT / "app" / "static" / "pages" / "reports" / "index.html"
JS = ROOT / "app" / "static" / "js" / "modules" / "reports-live.js"
CSS = ROOT / "app" / "static" / "css" / "modules" / "reports-live.css"
FILES = [API, HTML, JS, CSS]
for path in FILES:
    if not path.is_file():
        raise SystemExit(f"DURDURULDU: Gerekli dosya bulunamadı: {path}")

original = {p: p.read_text(encoding="utf-8") for p in FILES}
api, html, js, css = (original[p] for p in FILES)


def once(text, old, new, label):
    # Match the same source lines while tolerating optional blank lines and CRLF.
    # The first patch assumed blank lines between every statement, but the active
    # Cartman files use compact single-newline formatting in several sections.
    lines = [line.rstrip() for line in old.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(f"{label}: empty match pattern")
    separator = r"\r?\n(?:[ \t]*\r?\n)*"
    pattern = re.compile(separator.join(re.escape(line) for line in lines))
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise RuntimeError(f"{label}: tam bir eşleşme bekleniyordu, {len(matches)} bulundu")
    match = matches[0]
    return text[:match.start()] + new + text[match.end():]


# ---------------------------------------------------------------------------
# API: the active Cartman _meta() already exposes IAM groups and users.
# Validate this and reuse the existing metadata instead of adding duplicates.
# ---------------------------------------------------------------------------
meta_start = api.find("def _meta(")
meta_end = api.find("\ndef ", meta_start + 5)
if meta_start < 0 or meta_end < 0:
    raise RuntimeError("Could not locate the active _meta() function")
meta_block = api[meta_start:meta_end]
for required in ("groups = _rows(", "users = _rows(", '"groups": groups', '"users": users'):
    if required not in meta_block:
        raise RuntimeError("_meta() does not expose existing IAM users and groups; no files changed")

# Insert scope resolver before _report_schema.
anchor = '\ndef _report_schema(connection):\n'
resolver = r'''
def _resolve_report_scope(connection, payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Choose a report type and target.")
    scope_type = str(payload.get("type") or "").strip().lower()
    scope_id = str(payload.get("id") or "").strip()[:120]
    if scope_type not in {"user", "group", "department"} or not scope_id:
        raise HTTPException(status_code=422, detail="Choose a User, Group, or Department target.")

    if scope_type == "user":
        if not _has(connection, "iam_users", "id", "name", "username", "status"):
            raise HTTPException(status_code=503, detail="Cartman's IAM user directory is unavailable.")
        row = connection.execute(
            "SELECT id, COALESCE(NULLIF(TRIM(name),''),username) AS name, username "
            "FROM iam_users WHERE CAST(id AS TEXT)=? AND lower(COALESCE(status,'')) NOT IN ('disabled','inactive')",
            (scope_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Selected IAM user was not found or is disabled.")
        return {"type": "user", "id": str(row["id"]), "name": str(row["name"]),
                "usernames": [str(row["username"]).strip().lower()], "user_ids": [str(row["id"])], "member_count": 1}

    if scope_type == "group":
        if not _has(connection, "iam_groups", "id", "name", "status"):
            raise HTTPException(status_code=503, detail="Cartman's IAM group directory is unavailable.")
        row = connection.execute(
            "SELECT id, name FROM iam_groups WHERE CAST(id AS TEXT)=? AND lower(COALESCE(status,'')) <> 'disabled'",
            (scope_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Selected IAM group was not found or is disabled.")
        members = []
        if _has(connection, "iam_group_members", "group_id", "user_id") and _has(connection, "iam_users", "id", "username", "status"):
            members = _rows(connection,
                "SELECT DISTINCT u.id, u.username FROM iam_group_members gm "
                "JOIN iam_users u ON CAST(u.id AS TEXT)=CAST(gm.user_id AS TEXT) "
                "WHERE CAST(gm.group_id AS TEXT)=? AND lower(COALESCE(u.status,'')) NOT IN ('disabled','inactive')",
                (scope_id,),
            )
        usernames = sorted({str(item.get("username") or "").strip().lower() for item in members if str(item.get("username") or "").strip()})
        user_ids = sorted({str(item.get("id") or "") for item in members if str(item.get("id") or "")})
        return {"type": "group", "id": str(row["id"]), "name": str(row["name"]),
                "usernames": usernames, "user_ids": user_ids, "member_count": len(usernames)}

    if not _has(connection, "departments", "id", "name"):
        raise HTTPException(status_code=503, detail="Cartman's department directory is unavailable.")
    row = connection.execute("SELECT id, name FROM departments WHERE CAST(id AS TEXT)=?", (scope_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Selected department was not found.")
    return {"type": "department", "id": str(row["id"]), "name": str(row["name"]),
            "usernames": [], "user_ids": [], "member_count": None}

'''
api = once(api, anchor, resolver + anchor, "Insert report scope resolver")

# Ticket scoping by assigned/requester/creator IAM username.
api = once(
    api,
    'def _ticket_report(connection, start: str, end: str, department_id: str, department_name: str, team: str) -> Dict[str, Any]:\n',
    'def _ticket_report(connection, start: str, end: str, department_id: str, department_name: str, team: str, scope_usernames: Optional[List[str]] = None) -> Dict[str, Any]:\n',
    "Ticket report signature",
)
api = once(
    api,
    '    joins = ""\n\n    base_where = ["t.deleted_at IS NULL"]\n\n    department_scope_applied = not bool(department_id)\n',
    '    joins = ""\n\n    base_where = ["t.deleted_at IS NULL"]\n\n'
    '    scope_columns = [column for column in ("assigned_to_username", "requester_username", "created_by_username") if column in _columns(connection, "tickets")]\n'
    '    scope_clause = ""\n    scope_values: List[str] = []\n'
    '    if scope_usernames is not None:\n'
    '        normalized_users = sorted({str(value).strip().lower() for value in scope_usernames if str(value).strip()})\n'
    '        if not normalized_users or not scope_columns:\n'
    '            scope_clause = "0=1"\n'
    '        else:\n'
    '            placeholders = ",".join("?" for _ in normalized_users)\n'
    '            scope_clause = "(" + " OR ".join("lower(trim(COALESCE(t." + column + ",\'\'))) IN (" + placeholders + ")" for column in scope_columns) + ")"\n'
    '            for _column in scope_columns:\n'
    '                scope_values.extend(normalized_users)\n'
    '    department_scope_applied = not bool(department_id)\n',
    "Ticket report user/group filters",
)
api = once(
    api,
    '    if team:\n        base_where.append("t.team = ?")\n',
    '    if team:\n        base_where.append("t.team = ?")\n\n    if scope_clause:\n        base_where.append(scope_clause)\n',
    "Append ticket scope after department/team",
)
api = once(
    api,
    '        if team:\n            params.append(team)\n\n        params.extend(extra_params)\n',
    '        if team:\n            params.append(team)\n\n        params.extend(scope_values)\n\n        params.extend(extra_params)\n',
    "Ticket row query parameters",
)
api = once(
    api,
    '    if team:\n        backlog_params.append(team)\n\n    backlog_params.extend([end, end])\n',
    '    if team:\n        backlog_params.append(team)\n\n    backlog_params.extend(scope_values)\n\n    backlog_params.extend([end, end])\n',
    "Ticket backlog parameters",
)
api = once(
    api,
    '    if team:\n        created_params.append(team)\n\n    created_params.extend([start, end])\n',
    '    if team:\n        created_params.append(team)\n\n    created_params.extend(scope_values)\n\n    created_params.extend([start, end])\n',
    "Ticket chart parameters",
)
api = once(
    api,
    '        if team:\n            response_where.append("t.team = ?")\n            response_params.append(team)\n\n        response_rows = _rows(connection, """\n',
    '        if team:\n            response_where.append("t.team = ?")\n            response_params.append(team)\n\n'
    '        if scope_clause:\n            response_where.append(scope_clause)\n            response_params.extend(scope_values)\n\n'
    '        response_rows = _rows(connection, """\n',
    "Ticket response scope",
)
api = once(
    api,
    '        if team:\n            audit_where.append("t.team = ?")\n            audit_params.append(team)\n\n        sla_wait_started = _scalar(connection, "SELECT COUNT(*) FROM ticket_audit_events e" + audit_join + " WHERE " + " AND ".join(audit_where), tuple(audit_params), 0)\n',
    '        if team:\n            audit_where.append("t.team = ?")\n            audit_params.append(team)\n\n'
    '        if scope_clause:\n            audit_where.append(scope_clause)\n            audit_params.extend(scope_values)\n\n'
    '        sla_wait_started = _scalar(connection, "SELECT COUNT(*) FROM ticket_audit_events e" + audit_join + " WHERE " + " AND ".join(audit_where), tuple(audit_params), 0)\n',
    "Ticket audit scope",
)

# Work item scoping by assigned user id or creator username.
api = once(
    api,
    'def _workload_report(connection, start: str, end: str, department_id: str, department_name: str) -> Dict[str, Any]:\n',
    'def _workload_report(connection, start: str, end: str, department_id: str, department_name: str, scope_user_ids: Optional[List[str]] = None, scope_usernames: Optional[List[str]] = None) -> Dict[str, Any]:\n',
    "Workload signature",
)
api = once(
    api,
    '    work_columns = _columns(connection, "work_items")\n\n    user_join = " LEFT JOIN iam_users u ON CAST(u.id AS TEXT)=CAST(w.assigned_user_id AS TEXT)" if _has(connection, "iam_users", "id", "department") and "assigned_user_id" in work_columns else ""\n',
    '    work_columns = _columns(connection, "work_items")\n\n'
    '    scope_parts: List[str] = []\n    scope_params: List[str] = []\n'
    '    if scope_usernames is not None:\n'
    '        normalized_users = sorted({str(value).strip().lower() for value in scope_usernames if str(value).strip()})\n'
    '        normalized_ids = sorted({str(value).strip() for value in (scope_user_ids or []) if str(value).strip()})\n'
    '        if normalized_ids and "assigned_user_id" in work_columns:\n'
    '            scope_parts.append("CAST(w.assigned_user_id AS TEXT) IN (" + ",".join("?" for _ in normalized_ids) + ")")\n'
    '            scope_params.extend(normalized_ids)\n'
    '        if normalized_users and "created_by_username" in work_columns:\n'
    '            scope_parts.append("lower(trim(COALESCE(w.created_by_username,\'\'))) IN (" + ",".join("?" for _ in normalized_users) + ")")\n'
    '            scope_params.extend(normalized_users)\n'
    '    scope_clause = "(" + " OR ".join(scope_parts) + ")" if scope_usernames is not None and scope_parts else ("0=1" if scope_usernames is not None else "")\n\n'
    '    user_join = " LEFT JOIN iam_users u ON CAST(u.id AS TEXT)=CAST(w.assigned_user_id AS TEXT)" if _has(connection, "iam_users", "id", "department") and "assigned_user_id" in work_columns else ""\n',
    "Work item scope filter",
)
api = once(
    api,
    '    base_from = "work_items w" + user_join + target_join\n\n    filter_sql = " AND " + target_clause if target_clause else ""\n\n    select_dept = "COALESCE(u.department,\'\') AS assigned_department" if user_join else "\'\' AS assigned_department"\n\n    base_params = tuple(dept_params)\n\n    period_rows = _rows(connection, "SELECT DISTINCT w.*, " + select_dept + " FROM " + base_from + " WHERE julianday(w.created_at) >= julianday(?) AND julianday(w.created_at) <= julianday(?)" + filter_sql, (start, end) + base_params)\n\n    completed_rows = _rows(connection, "SELECT DISTINCT w.*, " + select_dept + " FROM " + base_from + " WHERE julianday(w.completed_at) >= julianday(?) AND julianday(w.completed_at) <= julianday(?)" + filter_sql, (start, end) + base_params) if "completed_at" in work_columns else []\n\n    current_rows = _rows(connection, "SELECT DISTINCT w.*, " + select_dept + " FROM " + base_from + (" WHERE " + target_clause if target_clause else ""), base_params)\n',
    '    base_from = "work_items w" + user_join + target_join\n\n'
    '    filter_parts = [part for part in (target_clause, scope_clause) if part]\n'
    '    filter_sql = " AND " + " AND ".join("(" + part + ")" for part in filter_parts) if filter_parts else ""\n\n'
    '    select_dept = "COALESCE(u.department,\'\') AS assigned_department" if user_join else "\'\' AS assigned_department"\n\n'
    '    base_params = tuple(dept_params)\n    all_params = base_params + tuple(scope_params)\n\n'
    '    period_rows = _rows(connection, "SELECT DISTINCT w.*, " + select_dept + " FROM " + base_from + " WHERE julianday(w.created_at) >= julianday(?) AND julianday(w.created_at) <= julianday(?)" + filter_sql, (start, end) + all_params)\n\n'
    '    completed_rows = _rows(connection, "SELECT DISTINCT w.*, " + select_dept + " FROM " + base_from + " WHERE julianday(w.completed_at) >= julianday(?) AND julianday(w.completed_at) <= julianday(?)" + filter_sql, (start, end) + all_params) if "completed_at" in work_columns else []\n\n'
    '    current_where = " WHERE " + " AND ".join("(" + part + ")" for part in filter_parts) if filter_parts else ""\n'
    '    current_rows = _rows(connection, "SELECT DISTINCT w.*, " + select_dept + " FROM " + base_from + current_where, all_params)\n',
    "Workload scoped queries",
)

# User activity / login/session scoping.
api = once(
    api,
    'def _activity_report(connection, start_epoch: int, end_epoch: int, department_name: str = "") -> Dict[str, Any]:\n',
    'def _activity_report(connection, start_epoch: int, end_epoch: int, department_name: str = "", scope_usernames: Optional[List[str]] = None) -> Dict[str, Any]:\n',
    "Activity report signature",
)
api = once(
    api,
    '        if has_iam_department:\n            sql += " JOIN iam_users u ON lower(trim(u.username))=lower(trim(a.username))"\n\n            where.append("lower(trim(COALESCE(u.department,\'\')))=lower(trim(?))")\n\n            params.append(department_name)\n\n        row = connection.execute(sql + " WHERE " + " AND ".join(where), tuple(params)).fetchone()\n',
    '        if has_iam_department:\n            sql += " JOIN iam_users u ON lower(trim(u.username))=lower(trim(a.username))"\n\n            where.append("lower(trim(COALESCE(u.department,\'\')))=lower(trim(?))")\n\n            params.append(department_name)\n\n'
    '        if scope_usernames is not None:\n            normalized = sorted({str(value).strip().lower() for value in scope_usernames if str(value).strip()})\n            if normalized:\n                where.append("lower(trim(a.username)) IN (" + ",".join("?" for _ in normalized) + ")")\n                params.extend(normalized)\n            else:\n                where.append("0=1")\n\n'
    '        row = connection.execute(sql + " WHERE " + " AND ".join(where), tuple(params)).fetchone()\n',
    "Activity sample scope",
)
api = once(
    api,
    '        if has_iam_department:\n            login_from += " JOIN iam_users u ON lower(trim(u.username))=lower(trim(a.username_norm))"\n\n            login_where.append("lower(trim(COALESCE(u.department,\'\')))=lower(trim(?))")\n\n            login_params.append(department_name)\n\n        result["login_attempts"] = int(_scalar(connection, "SELECT COUNT(*) FROM " + login_from + " WHERE " + " AND ".join(login_where), tuple(login_params), 0))\n',
    '        if has_iam_department:\n            login_from += " JOIN iam_users u ON lower(trim(u.username))=lower(trim(a.username_norm))"\n\n            login_where.append("lower(trim(COALESCE(u.department,\'\')))=lower(trim(?))")\n\n            login_params.append(department_name)\n\n'
    '        if scope_usernames is not None:\n            normalized = sorted({str(value).strip().lower() for value in scope_usernames if str(value).strip()})\n            if normalized:\n                login_where.append("lower(trim(a.username_norm)) IN (" + ",".join("?" for _ in normalized) + ")")\n                login_params.extend(normalized)\n            else:\n                login_where.append("0=1")\n\n'
    '        result["login_attempts"] = int(_scalar(connection, "SELECT COUNT(*) FROM " + login_from + " WHERE " + " AND ".join(login_where), tuple(login_params), 0))\n',
    "Login attempt scope",
)
api = once(
    api,
    '        if has_iam_department and _has(connection, "auth_accounts", "id", "username"):\n            session_from += " JOIN auth_accounts a ON a.id=s.account_id JOIN iam_users u ON lower(trim(u.username))=lower(trim(a.username))"\n\n            session_where.append("lower(trim(COALESCE(u.department,\'\')))=lower(trim(?))")\n\n            session_params.append(department_name)\n\n        result["sessions_created"] = int(_scalar(connection, "SELECT COUNT(*) FROM " + session_from + " WHERE " + " AND ".join(session_where), tuple(session_params), 0))\n',
    '        if (has_iam_department or scope_usernames is not None) and _has(connection, "auth_accounts", "id", "username"):\n            session_from += " JOIN auth_accounts a ON a.id=s.account_id"\n            if has_iam_department:\n                session_from += " JOIN iam_users u ON lower(trim(u.username))=lower(trim(a.username))"\n                session_where.append("lower(trim(COALESCE(u.department,\'\')))=lower(trim(?))")\n                session_params.append(department_name)\n\n'
    '        if scope_usernames is not None and _has(connection, "auth_accounts", "id", "username"):\n            normalized = sorted({str(value).strip().lower() for value in scope_usernames if str(value).strip()})\n            if normalized:\n                session_where.append("lower(trim(a.username)) IN (" + ",".join("?" for _ in normalized) + ")")\n                session_params.extend(normalized)\n            else:\n                session_where.append("0=1")\n\n'
    '        if scope_usernames is not None and not _has(connection, "auth_accounts", "id", "username"):\n            result["sessions_created"] = None\n        else:\n            result["sessions_created"] = int(_scalar(connection, "SELECT COUNT(*) FROM " + session_from + " WHERE " + " AND ".join(session_where), tuple(session_params), 0))\n',
    "Auth session scope",
)

# Build summary accepts validated report scope; user/group reports omit organization-wide sections.
api = once(
    api,
    'def _build_summary(connection, start: str, end: str, start_epoch: int, end_epoch: int, department_id: str = "", team: str = "") -> Dict[str, Any]:\n',
    'def _build_summary(connection, start: str, end: str, start_epoch: int, end_epoch: int, department_id: str = "", team: str = "", report_scope: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:\n',
    "Summary builder signature",
)
api = once(
    api,
    '    department_name = _department_name(connection, department_id) if department_id else ""\n\n    result = {\n',
    '    department_name = _department_name(connection, department_id) if department_id else ""\n\n'
    '    scope_kind = str((report_scope or {}).get("type") or "")\n'
    '    scoped_usernames = (report_scope or {}).get("usernames") if scope_kind in {"user", "group"} else None\n'
    '    scoped_user_ids = (report_scope or {}).get("user_ids") if scope_kind in {"user", "group"} else None\n\n'
    '    result = {\n',
    "Summary scope context",
)
api = once(
    api,
    '        "tickets": _ticket_report(connection, start, end, department_id, department_name, team),\n\n        "workload": _workload_report(connection, start, end, department_id, department_name),\n',
    '        "tickets": _ticket_report(connection, start, end, department_id, department_name, team, scoped_usernames),\n\n'
    '        "workload": _workload_report(connection, start, end, department_id, department_name, scoped_user_ids, scoped_usernames),\n',
    "Pass scope into ticket/workload reports",
)
api = once(
    api,
    '        "activity": _activity_report(connection, start_epoch, end_epoch, department_name),\n',
    '        "activity": _activity_report(connection, start_epoch, end_epoch, department_name, scoped_usernames),\n',
    "Pass scope into activity report",
)
api = once(
    api,
    '    result["coverage"] = {key: bool(value.get("available")) for key, value in result.items() if isinstance(value, dict) and "available" in value}\n\n    return result\n',
    '    if report_scope:\n'
    '        result["report_scope"] = {"type": report_scope.get("type"), "id": report_scope.get("id"), "name": report_scope.get("name"), "member_count": report_scope.get("member_count")}\n'
    '    if scope_kind in {"user", "group"}:\n'
    '        excluded = {"devices", "inventory", "monitoring", "network_vpn", "deployment", "automation", "remote_access", "software", "platform_activity", "system_metrics"}\n'
    '        reason = "Omitted from this User/Group report because the source records do not contain a reliable user or group-member relationship."\n'
    '        for section_name in excluded:\n'
    '            section_data = result.get(section_name)\n'
    '            if isinstance(section_data, dict):\n'
    '                section_data["available"] = False\n'
    '                section_data["scope_excluded"] = True\n'
    '                section_data["reason"] = reason\n'
    '        for metric in result.get("kpis", []):\n'
    '            if metric.get("key") in {"devices", "alerts_open"}:\n'
    '                metric["value"] = None\n'
    '    result["coverage"] = {key: bool(value.get("available")) for key, value in result.items() if isinstance(value, dict) and "available" in value}\n\n'
    '    return result\n',
    "Report scope coverage and safe exclusions",
)

# PDF includes the chosen scope and distinguishes filtered-out sources from missing data.
api = once(
    api,
    '    heading("Report scope")\n\n    line("Department: " + str(summary["filters"].get("department") or "All departments"))\n',
    '    heading("Report scope")\n\n'
    '    report_scope = summary.get("report_scope") or {}\n'
    '    scope_labels = {"user": "User", "group": "Group", "department": "Department"}\n'
    '    line("Report target: {} · {}".format(scope_labels.get(report_scope.get("type"), "Organization"), report_scope.get("name") or "Entire organization"))\n'
    '    if report_scope.get("type") == "group":\n        line("Active IAM group members included: {}".format(report_scope.get("member_count", 0)))\n'
    '    line("Department filter: " + str(summary["filters"].get("department") or "All departments"))\n',
    "PDF scope heading",
)
api = once(
    api,
    '            unavailable.append(mapped[1])\n',
    '            unavailable.append((mapped[1], mapped[0]))\n',
    "Retain section key in unavailable list",
)
api = once(
    api,
    '        for item in unavailable:\n',
    '        for item, source_key in unavailable:\n',
    "Unpack unavailable section keys",
)
api = once(
    api,
    '            line(item + ": No stored source data was available for this period.")\n',
    '            source_data = summary.get(source_key, {})\n'
    '            line(item + ": " + str(source_data.get("reason") or "No stored source data was available for this period."))\n',
    "PDF unavailable source explanations",
)

# Create endpoint: validate target, apply department target, persist scope metadata.
api = once(
    api,
    '    if not sections:\n        raise HTTPException(status_code=422, detail="Select at least one report section.")\n\n    with _connect() as connection:\n        summary = _build_summary(connection, sql_start, sql_end, start_epoch, end_epoch, department_id, team)\n',
    '    if not sections:\n        raise HTTPException(status_code=422, detail="Select at least one report section.")\n\n'
    '    with _connect() as connection:\n'
    '        report_scope = _resolve_report_scope(connection, payload.get("report_scope"))\n'
    '        if report_scope["type"] == "department":\n'
    '            if department_id and department_id != report_scope["id"]:\n'
    '                raise HTTPException(status_code=422, detail="The PDF report target Department must match the Department filter above.")\n'
    '            department_id = report_scope["id"]\n'
    '        summary = _build_summary(connection, sql_start, sql_end, start_epoch, end_epoch, department_id, team, report_scope)\n',
    "PDF validate and apply target scope",
)
api = once(
    api,
    '        json.dumps({"department_id": department_id, "team": team, "sections": sections}, ensure_ascii=False)))\n\n    return {"id": report_id, "filename": filename, "status": "completed", "view_url": "/api/reports/pdf/" + report_id}\n',
    '        json.dumps({"department_id": department_id, "team": team, "sections": sections, "report_scope": {"type": report_scope["type"], "id": report_scope["id"], "name": report_scope["name"], "member_count": report_scope.get("member_count")}}, ensure_ascii=False)))\n\n'
    '    return {"id": report_id, "filename": filename, "status": "completed", "report_scope": {"type": report_scope["type"], "id": report_scope["id"], "name": report_scope["name"], "member_count": report_scope.get("member_count")}, "view_url": "/api/reports/pdf/" + report_id, "download_url": "/api/reports/pdf/" + report_id + "/download"}\n',
    "Persist and return report target",
)

# Insert history and download routes immediately before the inline PDF view route.
route_pattern = re.compile(r'\n@router\.get\("/pdf/\{report_id\}"\)\n+def view_report_pdf\(report_id: str, request: Request\):\n')
new_routes = r'''
@router.get("/history")
def reports_history(request: Request, limit: int = 100):
    _require_admin(request)
    limit = max(1, min(int(limit), 500))
    with _connect() as connection:
        _report_schema(connection)
        rows = connection.execute(
            "SELECT id, filename, created_by_username, period_start, period_end, filters_json, created_at "
            "FROM cartman_generated_reports ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        items = []
        for row in rows:
            try:
                filters = json.loads(row["filters_json"] or "{}")
                if not isinstance(filters, dict):
                    filters = {}
            except (TypeError, ValueError):
                filters = {}
            scope = filters.get("report_scope") if isinstance(filters.get("report_scope"), dict) else None
            if not scope:
                legacy_department = str(filters.get("department_id") or "")
                if legacy_department:
                    try:
                        legacy_name = _department_name(connection, legacy_department)
                    except HTTPException:
                        legacy_name = "Previously selected department"
                    scope = {"type": "department", "id": legacy_department, "name": legacy_name, "legacy": True}
                else:
                    scope = {"type": "organization", "id": "", "name": "Organization-wide (legacy)", "legacy": True}
            report_id = str(row["id"])
            items.append({
                "id": report_id,
                "filename": str(row["filename"]),
                "created_by_username": str(row["created_by_username"] or ""),
                "created_at": str(row["created_at"] or ""),
                "period_start": str(row["period_start"] or ""),
                "period_end": str(row["period_end"] or ""),
                "report_scope": scope,
                "filters": filters,
                "view_url": "/api/reports/pdf/" + report_id,
                "download_url": "/api/reports/pdf/" + report_id + "/download",
            })
    return {"items": items, "source": "database"}


@router.get("/pdf/{report_id}/download")
def download_report_pdf(report_id: str, request: Request):
    _require_admin(request)
    if not re.fullmatch(r"[0-9a-f]{32}", str(report_id or "")):
        raise HTTPException(status_code=404, detail="Report not found.")
    with _connect() as connection:
        if "cartman_generated_reports" not in _tables(connection):
            raise HTTPException(status_code=404, detail="Report not found.")
        row = connection.execute("SELECT filename, stored_path FROM cartman_generated_reports WHERE id=?", (report_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Report not found.")
    report_dir = REPORT_DIR.resolve()
    stored = Path(str(row["stored_path"])).resolve()
    if stored.parent != report_dir or not stored.is_file():
        raise HTTPException(status_code=404, detail="Generated PDF is no longer available.")
    return FileResponse(str(stored), media_type="application/pdf", filename=row["filename"], content_disposition_type="attachment")
'''
route_matches = list(route_pattern.finditer(api))
if len(route_matches) != 1:
    raise RuntimeError(f"PDF view route anchor: one match expected, {len(route_matches)} found")
route_match = route_matches[0]
api = api[:route_match.start()] + "\n" + new_routes + "\n" + api[route_match.start():]

# ---------------------------------------------------------------------------
# HTML: Create / History tabs, target selector and report history list.
# ---------------------------------------------------------------------------
pdf_start = html.find('            <section class="rp-pdf-panel" aria-label="PDF report creation">')
if pdf_start < 0:
    raise RuntimeError("PDF reports panel opening tag not found")
pdf_end_token = '            </section>'
# PDF panel is the final report section before workspace closing; use exact last occurrence before footer.
footer_pos = html.find('        <footer class="app-footer cartman-version-footer"')
if footer_pos < 0:
    raise RuntimeError("Reports page footer anchor not found")
panel_end = html.rfind(pdf_end_token, pdf_start, footer_pos)
if panel_end < 0:
    raise RuntimeError("PDF reports panel closing tag not found")
panel_end += len(pdf_end_token)
old_panel = html[pdf_start:panel_end]
if old_panel.count('data-rp-create-pdf') != 1 or 'data-rp-pdf-section="tickets"' not in old_panel:
    raise RuntimeError("Unexpected PDF panel structure; HTML not patched")

new_panel = '''            <section class="rp-pdf-panel" aria-label="PDF reports">
                <div class="rp-report-tabs" role="tablist" aria-label="PDF reports">
                    <button type="button" class="rp-report-tab is-active" data-rp-tab="create" role="tab" aria-selected="true">Create</button>
                    <button type="button" class="rp-report-tab" data-rp-tab="history" role="tab" aria-selected="false">History</button>
                </div>
                <div class="rp-report-pane" data-rp-pane="create">
                    <div class="rp-pdf-heading"><div><span class="rp-overline">EXPORT</span><h2>PDF reports</h2><p>Choose the report target and sections. Existing date, department and support-team filters are preserved.</p></div><span class="rp-pdf-icon">PDF</span></div>
                    <div class="rp-scope-grid" aria-label="Report target">
                        <label class="rp-field"><span>Report for</span><select data-rp-scope-type><option value="">Choose target type</option><option value="user">User</option><option value="group">Group</option><option value="department">Department</option></select></label>
                        <label class="rp-field"><span>Target</span><select data-rp-scope-target disabled><option value="">Choose target type first</option></select></label>
                    </div>
                    <p class="rp-scope-note" data-rp-scope-note>Select whether this PDF is for one IAM user, an existing IAM group, or a department.</p>
                    <div class="rp-pdf-sections">
                        <label><input type="checkbox" data-rp-pdf-section="tickets" checked> Tickets</label>
                        <label><input type="checkbox" data-rp-pdf-section="sla" checked> SLA &amp; response timing</label>
                        <label><input type="checkbox" data-rp-pdf-section="workload" checked> Workload</label>
                        <label><input type="checkbox" data-rp-pdf-section="devices" checked> Devices &amp; inventory</label>
                        <label><input type="checkbox" data-rp-pdf-section="monitoring" checked> Monitoring</label>
                        <label><input type="checkbox" data-rp-pdf-section="network_vpn" checked> Network &amp; VPN</label>
                        <label><input type="checkbox" data-rp-pdf-section="deployment" checked> Deployment</label>
                        <label><input type="checkbox" data-rp-pdf-section="automation" checked> Automation</label>
                        <label><input type="checkbox" data-rp-pdf-section="activity" checked> User activity</label>
                        <label><input type="checkbox" data-rp-pdf-section="remote_access" checked> Remote access</label>
                        <label><input type="checkbox" data-rp-pdf-section="software" checked> Software catalogue</label>
                        <label><input type="checkbox" data-rp-pdf-section="platform_activity" checked> Platform audit</label>
                        <label><input type="checkbox" data-rp-pdf-section="system_metrics" checked> System metrics</label>
                    </div>
                    <div class="rp-pdf-actions"><button type="button" class="io-btn primary" data-rp-create-pdf>Create PDF</button><span class="rp-pdf-status" data-rp-pdf-status aria-live="polite">PDF has not been generated yet.</span><button type="button" class="io-btn rp-view-pdf hidden" data-rp-view-pdf>View PDF</button></div>
                </div>
                <div class="rp-report-pane hidden" data-rp-pane="history" role="tabpanel">
                    <div class="rp-history-heading"><div><span class="rp-overline">GENERATED FILES</span><h2>PDF history</h2><p>Previously generated reports are stored in Cartman's database and can be opened or downloaded again.</p></div><button type="button" class="io-btn" data-rp-refresh-history>Refresh history</button></div>
                    <div class="rp-history-list" data-rp-history-list><div class="rp-history-empty">Loading report history…</div></div>
                </div>
            </section>'''
html = html[:pdf_start] + new_panel + html[panel_end:]
html = html.replace('reports-live.css?v=cartman-reports-demo-layout-v1', 'reports-live.css?v=cartman-reports-history-scope-v3')
html = html.replace('reports-live.js?v=cartman-reports-demo-layout-v1', 'reports-live.js?v=cartman-reports-history-scope-v3')

# ---------------------------------------------------------------------------
# JS: load targets, create scoped reports, browse history.
# ---------------------------------------------------------------------------
js = once(
    js,
    '    const state = { meta: null, summary: null, pdfUrl: "", activePreset: "week" };\n',
    '    const state = { meta: null, summary: null, pdfUrl: "", activePreset: "week", activeReportTab: "create" };\n',
    "JS state",
)
js = once(
    js,
    '    async function loadMeta() {\n',
    '''    function setReportTab(tab) {
        state.activeReportTab = tab;
        $$('[data-rp-tab]').forEach(button => {
            const active = button.dataset.rpTab === tab;
            button.classList.toggle("is-active", active);
            button.setAttribute("aria-selected", active ? "true" : "false");
        });
        $$('[data-rp-pane]').forEach(pane => pane.classList.toggle("hidden", pane.dataset.rpPane !== tab));
        if (tab === "history") loadHistory();
    }

    function updateScopeTargets() {
        const type = $("[data-rp-scope-type]").value;
        const target = $("[data-rp-scope-target]");
        const note = $("[data-rp-scope-note]");
        const config = {
            user: { items: state.meta && state.meta.users || [], placeholder: "Choose a user", empty: "No active IAM users found", note: "The report includes records reliably linked to the selected IAM user." },
            group: { items: state.meta && state.meta.groups || [], placeholder: "Choose a group", empty: "No active IAM groups found", note: "The report includes records linked to active members of the selected IAM group. Sources without a reliable member relationship are omitted." },
            department: { items: state.meta && state.meta.departments || [], placeholder: "Choose a department", empty: "No departments found", note: "The report uses Cartman's existing department relationships. Sources without a department relationship are identified in the PDF." }
        }[type];
        if (!config) {
            target.innerHTML = '<option value="">Choose target type first</option>';
            target.disabled = true;
            note.textContent = "Select whether this PDF is for one IAM user, an existing IAM group, or a department.";
            return;
        }
        target.value = "";
        fillSelect(target, config.items, config.items.length ? config.placeholder : config.empty);
        target.value = "";
        target.disabled = !config.items.length;
        note.textContent = config.note;
    }

    function getReportScope() {
        const type = $("[data-rp-scope-type]").value;
        const id = $("[data-rp-scope-target]").value;
        if (!["user", "group", "department"].includes(type) || !id) {
            throw new Error("Choose a User, Group, or Department and select its target before creating the PDF.");
        }
        return { type, id };
    }

    function formatDate(value) {
        if (!value) return "—";
        const date = new Date(String(value).replace(" ", "T") + (String(value).endsWith("Z") ? "" : "Z"));
        return Number.isFinite(date.getTime()) ? date.toLocaleString() : String(value);
    }

    async function loadHistory() {
        const list = $("[data-rp-history-list]");
        if (!list) return;
        list.innerHTML = '<div class="rp-history-empty">Loading report history…</div>';
        try {
            const result = await api("/api/reports/history?limit=200");
            const items = Array.isArray(result.items) ? result.items : [];
            if (!items.length) {
                list.innerHTML = '<div class="rp-history-empty">No PDF reports have been generated yet.</div>';
                return;
            }
            const scopeLabel = item => {
                const scope = item.report_scope || {};
                const type = ({ user: "User", group: "Group", department: "Department", organization: "Organization" })[scope.type] || "Report";
                return `${type} · ${scope.name || "Unknown target"}`;
            };
            list.innerHTML = items.map(item => `<article class="rp-history-item">
                <div class="rp-history-file-icon">PDF</div>
                <div class="rp-history-details"><strong>${esc(item.filename)}</strong><span>${esc(scopeLabel(item))}</span><small>Generated ${esc(formatDate(item.created_at))} · By ${esc(item.created_by_username || "Unknown")} · ${esc(formatDate(item.period_start))} — ${esc(formatDate(item.period_end))}</small></div>
                <div class="rp-history-actions"><a class="io-btn rp-history-view" href="${esc(item.view_url)}" target="_blank" rel="noopener">View</a><a class="io-btn" href="${esc(item.download_url)}">Download</a></div>
            </article>`).join("");
        } catch (error) {
            list.innerHTML = `<div class="rp-history-empty is-error">Could not load PDF history: ${esc(error.message || "Unknown error")}</div>`;
        }
    }

    async function loadMeta() {
''',
    "Insert JS tab/scope/history helpers",
)
js = once(
    js,
    '        fillSelect($("[data-rp-team]"), meta.teams || [], "All support teams");\n',
    '        fillSelect($("[data-rp-team]"), meta.teams || [], "All support teams");\n'
    '        updateScopeTargets();\n',
    "Initialize scope targets",
)
js = once(
    js,
    '            const result = await api("/api/reports/pdf", {\n\n                method: "POST",\n\n                body: JSON.stringify({ ...getFilters(), sections })\n\n            });\n',
    '            const reportScope = getReportScope();\n'
    '            const result = await api("/api/reports/pdf", {\n\n                method: "POST",\n\n                body: JSON.stringify({ ...getFilters(), sections, report_scope: reportScope })\n\n            });\n',
    "Send report target to PDF API",
)
# Add history refresh after success status without relying on whitespace-sensitive adjacent formatting.
js = once(
    js,
    '            $("[data-rp-view-pdf]").classList.remove("hidden");\n',
    '            $("[data-rp-view-pdf]").classList.remove("hidden");\n            loadHistory();\n',
    "Refresh history after PDF creation",
)
js = once(
    js,
    '            button.textContent = "Create report in PDF";\n',
    '            button.textContent = "Create PDF";\n',
    "Update create button label",
)
js = once(
    js,
    '    $("[data-rp-create-pdf]").addEventListener("click", createPdf);\n',
    '    $("[data-rp-create-pdf]").addEventListener("click", createPdf);\n'
    '    $$("[data-rp-tab]").forEach(button => button.addEventListener("click", () => setReportTab(button.dataset.rpTab)));\n'
    '    $("[data-rp-scope-type]").addEventListener("change", updateScopeTargets);\n'
    '    $("[data-rp-refresh-history]").addEventListener("click", loadHistory);\n',
    "Wire new controls",
) if '    $("[data-rp-create-pdf]").addEventListener("click", createPdf);\n' in js else js
# ---------------------------------------------------------------------------
# CSS additions.
# ---------------------------------------------------------------------------
css_marker = "/* CARTMAN_REPORT_HISTORY_SCOPE_V3 */"
if css_marker not in css:
    css += r'''

/* CARTMAN_REPORT_HISTORY_SCOPE_V3 */
.rp-report-tabs{display:flex;gap:7px;margin:-2px 0 20px;padding:4px;width:max-content;max-width:100%;border:1px solid rgba(145,163,207,.2);border-radius:11px;background:rgba(7,13,27,.32)}
.rp-report-tab{min-width:104px;min-height:36px;padding:8px 16px;border:1px solid transparent;border-radius:8px;background:transparent;color:#aab6cf;font:inherit;font-size:11px;font-weight:800;cursor:pointer}
.rp-report-tab:hover{color:#fff;background:rgba(139,124,255,.11)}
.rp-report-tab.is-active{color:#fff;background:linear-gradient(135deg,#8878ff,#6558d7);border-color:rgba(197,189,255,.45);box-shadow:0 5px 16px rgba(105,89,222,.25)}
.rp-scope-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px;margin-top:20px;padding:15px;border:1px solid rgba(145,163,207,.18);border-radius:11px;background:rgba(7,13,27,.24)}
.rp-scope-note{margin:9px 0 0;font-size:10px;line-height:1.55;color:#aab6cf}
.rp-history-heading{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:17px}
.rp-history-heading h2{font-size:24px;letter-spacing:-.55px;margin:7px 0 8px;color:var(--text-primary);font-weight:760}
.rp-history-heading p{font-size:12px;line-height:1.6;color:var(--text-secondary,#97a5c2);margin:0;max-width:760px}
.rp-history-list{display:grid;gap:10px}
.rp-history-empty{padding:28px 18px;border:1px dashed rgba(145,163,207,.24);border-radius:12px;color:#aab6cf;font-size:11px;text-align:center;background:rgba(7,13,27,.2)}
.rp-history-empty.is-error{color:#f0a0ac;border-color:rgba(240,127,145,.35)}
.rp-history-item{display:grid;grid-template-columns:46px minmax(0,1fr) auto;align-items:center;gap:14px;padding:14px;border:1px solid rgba(145,163,207,.19);border-radius:12px;background:rgba(7,13,27,.25)}
.rp-history-file-icon{display:grid;place-items:center;width:42px;height:46px;border:1px solid rgba(240,127,145,.45);border-radius:9px;background:rgba(240,127,145,.1);color:#ff9dac;font-size:10px;font-weight:950}
.rp-history-details{min-width:0;display:grid;gap:5px}
.rp-history-details strong{color:var(--text-primary,#e8edf8);font-size:11px;overflow-wrap:anywhere}
.rp-history-details span{color:#a99fff;font-size:10px;font-weight:750}
.rp-history-details small{color:var(--text-secondary,#97a5c2);font-size:9px;line-height:1.5;overflow-wrap:anywhere}
.rp-history-actions{display:flex;gap:7px;flex-wrap:wrap;justify-content:flex-end}
.rp-history-actions .io-btn{display:inline-flex;align-items:center;justify-content:center;min-height:34px;padding:7px 11px;text-decoration:none;font-size:10px;white-space:nowrap}
.rp-history-view{border-color:rgba(57,197,154,.5)!important;color:#76e0bd!important}
.light-theme .rp-report-tabs,.light-theme .rp-scope-grid,.light-theme .rp-history-item{background:rgba(65,83,125,.035);border-color:rgba(65,83,125,.15)}
.light-theme .rp-report-tab{color:#52617e}.light-theme .rp-report-tab.is-active{color:#fff}
.light-theme .rp-scope-note,.light-theme .rp-history-empty{color:#5e6d88}
.light-theme .rp-history-details strong{color:#263451}.light-theme .rp-history-details small{color:#687793}
@media(max-width:700px){.rp-scope-grid{grid-template-columns:1fr}.rp-history-heading{align-items:stretch;flex-direction:column}.rp-history-item{grid-template-columns:42px minmax(0,1fr)}.rp-history-actions{grid-column:1/-1;justify-content:flex-start}.rp-report-tabs{width:100%}.rp-report-tab{flex:1}}
/* END CARTMAN_REPORT_HISTORY_SCOPE_V3 */
'''

# JS cleanup/checks: handlers and labels are exact, ensure not duplicated.
if 'Create report in PDF' in js:
    js = js.replace('Create report in PDF', 'Create PDF')
if 'data-rp-tab="create"' not in html or 'data-rp-pane="history"' not in html:
    raise RuntimeError("Create/History HTML controls missing")
if 'data-rp-scope-type' not in html or 'data-rp-scope-target' not in html:
    raise RuntimeError("Report target selectors missing")
if 'function loadHistory()' not in js or 'report_scope: reportScope' not in js:
    raise RuntimeError("Report history or scope JavaScript missing")
if '@router.get("/history")' not in api or 'def download_report_pdf' not in api:
    raise RuntimeError("History/download endpoints missing")
if 'def _resolve_report_scope' not in api:
    raise RuntimeError("Report scope resolver missing")

# Ensure JS event wiring is present exactly once and the UI selectors exist.
if js.count('setReportTab(button.dataset.rpTab)') != 1:
    raise RuntimeError("Create/History tab event binding missing or duplicated")
if js.count('updateScopeTargets);') < 1:
    raise RuntimeError("Scope target change binding missing")

# Compile patched Python in-memory before touching files.
compile(api, str(API), "exec")

# Back up all files first, then write atomically. Roll back on any failure.
backup_dir = ROOT / ".backups" / ("reports-history-scope-v3-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
backup_dir.mkdir(parents=True, exist_ok=False)
changed = {API: api, HTML: html, JS: js, CSS: css}
for path in FILES:
    shutil.copy2(path, backup_dir / (path.name + ".bak"))
written = []
try:
    for path, content in changed.items():
        temp = path.with_name(path.name + ".tmp")
        temp.write_text(content, encoding="utf-8")
        os.chmod(temp, path.stat().st_mode)
        os.replace(temp, path)
        written.append(path)
    py_compile.compile(str(API), doraise=True)
except Exception:
    for path in reversed(written):
        shutil.copy2(backup_dir / (path.name + ".bak"), path)
    raise

print("OK: PDF Reports Create/History UI eklendi.")
print("OK: User / Group / Department hedef seçimi eklendi.")
print("OK: User/Group scope için desteklenen kaynaklar filtreleniyor; ilişkisiz organization-wide bölümler PDF'den çıkarılıyor.")
print("OK: PDF geçmişi SQLite kayıtlarından listeleniyor; View ve Download uçları eklendi.")
print("OK: Eski rapor kayıtları ve mevcut PDF dosyaları korunuyor.")
print("Python syntax: OK")
print("Backup:", backup_dir)
print("Changed:")
for path in FILES:
    print(" -", path.relative_to(ROOT))
