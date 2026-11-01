"""Cartman live operational reporting API.

All report figures are read from the active Cartman SQLite database. Missing
sources are reported as unavailable; the API never seeds report/demo rows.
"""
# CARTMAN_REPORTS_API_V1
from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

DATABASE = Path(__file__).resolve().parent / "cartman.db"
REPORT_DIR = Path(__file__).resolve().parent / "generated_reports"
router = APIRouter(prefix="/api/reports", tags=["Reports"])


def _connect():
    connection = sqlite3.connect(str(DATABASE), timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 15000")
    return connection


def _require_admin(request: Request) -> Dict[str, Any]:
    user = getattr(request.state, "auth_user", None)
    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="Authentication required.")
    if str(user.get("role") or "").strip().lower() != "admin":
        raise HTTPException(status_code=403, detail="Organization-wide reports require an administrator account.")
    return user


def _tables(connection) -> set:
    return {str(row[0]) for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}


def _columns(connection, table: str) -> set:
    if table not in _tables(connection):
        return set()
    safe = '"' + table.replace('"', '""') + '"'
    return {str(row[1]) for row in connection.execute("PRAGMA table_info(" + safe + ")").fetchall()}


def _has(connection, table: str, *columns: str) -> bool:
    present = _columns(connection, table)
    return bool(present) and all(item in present for item in columns)


def _parse_stamp(value: str, label: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise HTTPException(status_code=422, detail="Both start and end date/time are required.")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=label + " must be a valid ISO date/time.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _period(start: str, end: str) -> Tuple[str, str, int, int, str, str]:
    start_dt = _parse_stamp(start, "Start")
    end_dt = _parse_stamp(end, "End")
    if end_dt <= start_dt:
        raise HTTPException(status_code=422, detail="End date/time must be after start date/time.")
    if (end_dt - start_dt) > timedelta(days=3660):
        raise HTTPException(status_code=422, detail="A report range cannot exceed 10 years.")
    sql_start = start_dt.strftime("%Y-%m-%d %H:%M:%S")
    sql_end = end_dt.strftime("%Y-%m-%d %H:%M:%S")
    return sql_start, sql_end, int(start_dt.timestamp()), int(end_dt.timestamp()), start_dt.isoformat(), end_dt.isoformat()


def _between(column: str) -> str:
    # julianday accepts both SQLite CURRENT_TIMESTAMP values (space separator)
    # and ISO-8601 values emitted by CartmanClient (T separator / optional Z).
    return "julianday(" + column + ") >= julianday(?) AND julianday(" + column + ") <= julianday(?)"


def _count(connection, table: str, where: str = "1=1", params: tuple = ()) -> Optional[int]:
    if table not in _tables(connection):
        return None
    try:
        return int(connection.execute("SELECT COUNT(*) FROM \"" + table + "\" WHERE " + where, params).fetchone()[0])
    except sqlite3.Error:
        return None


def _rows(connection, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    try:
        return [dict(row) for row in connection.execute(sql, params).fetchall()]
    except sqlite3.Error:
        return []


def _scalar(connection, sql: str, params: tuple = (), default: Any = 0) -> Any:
    try:
        row = connection.execute(sql, params).fetchone()
        return row[0] if row and row[0] is not None else default
    except sqlite3.Error:
        return default


def _department_name(connection, department_id: str) -> str:
    if not department_id:
        return ""
    if "departments" not in _tables(connection):
        raise HTTPException(status_code=404, detail="Cartman's department directory is not available.")
    row = connection.execute("SELECT name FROM departments WHERE CAST(id AS TEXT)=?", (department_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Selected department does not exist in Cartman's department directory.")
    return str(row[0])


def _meta(connection) -> Dict[str, Any]:
    departments = _rows(connection, "SELECT id, name FROM departments ORDER BY name COLLATE NOCASE") if "departments" in _tables(connection) else []
    teams = _rows(connection, "SELECT DISTINCT TRIM(team) AS name FROM tickets WHERE TRIM(COALESCE(team,''))<>'' AND deleted_at IS NULL ORDER BY name COLLATE NOCASE") if _has(connection, "tickets", "team", "deleted_at") else []
    groups = _rows(connection, "SELECT id, name FROM iam_groups WHERE status <> 'Disabled' ORDER BY name COLLATE NOCASE") if _has(connection, "iam_groups", "id", "name", "status") else []
    users = _rows(connection, "SELECT id, COALESCE(NULLIF(TRIM(name),''), username) || ' · ' || username AS name, username FROM iam_users WHERE lower(COALESCE(status,'')) NOT IN ('disabled', 'inactive') ORDER BY name COLLATE NOCASE") if _has(connection, "iam_users", "id", "name", "username", "status") else []

    sources = {
        "tickets": "tickets" in _tables(connection),
        "ticket_comments": "ticket_comments" in _tables(connection),
        "workload": "work_items" in _tables(connection),
        "departments": "departments" in _tables(connection),
        "devices": "devices" in _tables(connection),
        "inventory": "inventory_assets" in _tables(connection),
        "monitoring": any(t in _tables(connection) for t in ("monitoring_metrics", "monitoring_events", "monitoring_alerts", "availability_checks", "service_checks")),
        "network": any(t in _tables(connection) for t in ("network_devices", "network_subnets", "network_ip_addresses", "network_dns_records", "network_dhcp_scopes", "network_dhcp_leases")),
        "vpn": "vpn_audit_logs" in _tables(connection) or "vpn_networks" in _tables(connection),
        "deployment": "device_tasks" in _tables(connection),
        "automation": any(t in _tables(connection) for t in ("automation_executions", "cartman_workflow_runs")),
        "activity": any(t in _tables(connection) for t in ("cartman_user_activity_minutes", "auth_login_attempts")),
        "remote_access": "remote_access_sessions" in _tables(connection),
        "software": "software_catalog" in _tables(connection) or "software_audit_history" in _tables(connection),
        "platform_activity": any(t in _tables(connection) for t in ("iam_audit_events", "cartman_api_key_access_logs", "cartman_connector_logs", "knowledge_article_audit", "device_connection_requests")),
        "system_metrics": "cartman_process_metric_samples" in _tables(connection),
    }
    return {"departments": departments, "teams": [r["name"] for r in teams], "groups": groups, "users": users, "sources": sources}



def _ticket_report(connection, start: str, end: str, department_id: str, department_name: str, team: str, scope_usernames: Optional[List[str]] = None) -> Dict[str, Any]:

    if not _has(connection, "tickets", "id", "created_at", "status", "priority", "team", "deleted_at"):
        return {"available": False, "reason": "Ticket table or required columns are not available."}

    joins = ""

    base_where = ["t.deleted_at IS NULL"]

    scope_columns = [column for column in ("assigned_to_username", "requester_username", "created_by_username") if column in _columns(connection, "tickets")]
    scope_clause = ""
    scope_values: List[str] = []
    if scope_usernames is not None:
        normalized_users = sorted({str(value).strip().lower() for value in scope_usernames if str(value).strip()})
        if not normalized_users or not scope_columns:
            scope_clause = "0=1"
        else:
            placeholders = ",".join("?" for _ in normalized_users)
            scope_clause = "(" + " OR ".join("lower(trim(COALESCE(t." + column + ",''))) IN (" + placeholders + ")" for column in scope_columns) + ")"
            for _column in scope_columns:
                scope_values.extend(normalized_users)
    department_scope_applied = not bool(department_id)

    if department_id and _has(connection, "iam_users", "username", "department") and _has(connection, "tickets", "assigned_to_username"):
        joins = " LEFT JOIN iam_users iu ON lower(trim(iu.username))=lower(trim(t.assigned_to_username))"
        base_where.append("lower(trim(COALESCE(iu.department,'')))=lower(trim(?))")
        department_scope_applied = True
    if team:
        base_where.append("t.team = ?")

    if scope_clause:
        base_where.append(scope_clause)


    def select_ticket_rows(extra_where: List[str], extra_params: List[Any]) -> List[Dict[str, Any]]:
        where = list(base_where) + extra_where
        params: List[Any] = []
        if department_id and joins:
            params.append(department_name)
        if team:
            params.append(team)

        params.extend(scope_values)

        params.extend(extra_params)

        return _rows(connection, "SELECT t.* FROM tickets t" + joins + " WHERE " + " AND ".join(where), tuple(params))

    created = select_ticket_rows(["julianday(t.created_at) >= julianday(?)", "julianday(t.created_at) <= julianday(?)"], [start, end])
    resolved_extra = ["t.resolved_at IS NOT NULL", "julianday(t.resolved_at) >= julianday(?)", "julianday(t.resolved_at) <= julianday(?)"]
    if "resolved_at" in _columns(connection, "tickets"):
        resolved = select_ticket_rows(resolved_extra, [start, end])
    else:
        resolved = []
    backlog_where = ["julianday(t.created_at) <= julianday(?)", "(t.resolved_at IS NULL OR julianday(t.resolved_at) > julianday(?))"]
    backlog_params: List[Any] = []
    if department_id and joins:
        backlog_params.append(department_name)
    if team:
        backlog_params.append(team)

    backlog_params.extend(scope_values)

    backlog_params.extend([end, end])

    backlog = _scalar(connection, "SELECT COUNT(*) FROM tickets t" + joins + " WHERE " + " AND ".join(base_where + backlog_where), tuple(backlog_params), 0)
    created_params: List[Any] = []
    if department_id and joins:
        created_params.append(department_name)
    if team:
        created_params.append(team)

    created_params.extend(scope_values)

    created_params.extend([start, end])

    group_prefix = "SELECT t.{} AS label, COUNT(*) AS value FROM tickets t" + joins + " WHERE " + " AND ".join(base_where + ["julianday(t.created_at) >= julianday(?)", "julianday(t.created_at) <= julianday(?)"]) + " GROUP BY t.{} ORDER BY value DESC, label"
    by_team = _rows(connection, group_prefix.format("team", "team"), tuple(created_params))
    by_status = _rows(connection, group_prefix.format("status", "status"), tuple(created_params))
    by_priority = _rows(connection, group_prefix.format("priority", "priority"), tuple(created_params))
    by_type = _rows(connection, group_prefix.format("ticket_type", "ticket_type"), tuple(created_params)) if "ticket_type" in _columns(connection, "tickets") else []
    by_escalation = _rows(connection, group_prefix.format("escalation_level", "escalation_level"), tuple(created_params)) if "escalation_level" in _columns(connection, "tickets") else []

    resolution_hours: List[float] = []
    for row in resolved:
        try:
            created_at = datetime.fromisoformat(str(row.get("created_at") or "").replace(" ", "T"))
            resolved_at = datetime.fromisoformat(str(row.get("resolved_at") or "").replace(" ", "T"))
            hours = (resolved_at - created_at).total_seconds() / 3600
            if hours >= 0:
                resolution_hours.append(hours)
        except (TypeError, ValueError):
            pass

    response_hours: List[float] = []
    if _has(connection, "ticket_comments", "ticket_id", "created_at", "is_internal", "author_role"):
        response_where = ["t.deleted_at IS NULL", "julianday(t.created_at) >= julianday(?)", "julianday(t.created_at) <= julianday(?)", "COALESCE(c.is_internal,0)=0", "lower(COALESCE(c.author_role,'')) IN ('agent','support')"]
        response_params: List[Any] = [start, end]
        response_join = " JOIN ticket_comments c ON c.ticket_id=t.id"
        if department_id and joins:
            response_join += " LEFT JOIN iam_users iu ON lower(trim(iu.username))=lower(trim(t.assigned_to_username))"
            response_where.append("lower(trim(COALESCE(iu.department,'')))=lower(trim(?))")
            response_params.append(department_name)
        if team:
            response_where.append("t.team = ?")
            response_params.append(team)

        if scope_clause:
            response_where.append(scope_clause)
            response_params.extend(scope_values)

        response_rows = _rows(connection, """

            SELECT t.created_at AS ticket_created, MIN(c.created_at) AS first_response
            FROM tickets t""" + response_join + " WHERE " + " AND ".join(response_where) + " GROUP BY t.id", tuple(response_params))
        for row in response_rows:
            try:
                first = datetime.fromisoformat(str(row["first_response"]).replace(" ", "T"))
                created_at = datetime.fromisoformat(str(row["ticket_created"]).replace(" ", "T"))
                hours = (first - created_at).total_seconds() / 3600
                if hours >= 0:
                    response_hours.append(hours)
            except (TypeError, ValueError):
                pass

    sla_wait_started = None
    sla_timeout_reopened = None
    if _has(connection, "ticket_audit_events", "ticket_id", "action", "created_at"):
        audit_join = " JOIN tickets t ON t.id=e.ticket_id"
        audit_where = ["t.deleted_at IS NULL", "e.action LIKE ?", "julianday(e.created_at) >= julianday(?)", "julianday(e.created_at) <= julianday(?)"]
        audit_params: List[Any] = ["Waiting for requester response (24h)%", start, end]
        if department_id and joins:
            audit_join += " LEFT JOIN iam_users iu ON lower(trim(iu.username))=lower(trim(t.assigned_to_username))"
            audit_where.append("lower(trim(COALESCE(iu.department,'')))=lower(trim(?))")
            audit_params.append(department_name)
        if team:
            audit_where.append("t.team = ?")
            audit_params.append(team)

        if scope_clause:
            audit_where.append(scope_clause)
            audit_params.extend(scope_values)

        sla_wait_started = _scalar(connection, "SELECT COUNT(*) FROM ticket_audit_events e" + audit_join + " WHERE " + " AND ".join(audit_where), tuple(audit_params), 0)

        audit_params[0] = "Auto-reopened after 24 hours%"
        sla_timeout_reopened = _scalar(connection, "SELECT COUNT(*) FROM ticket_audit_events e" + audit_join + " WHERE " + " AND ".join(audit_where), tuple(audit_params), 0)

    return {
        "available": True,
        "created": len(created),
        "resolved_in_period": len(resolved),
        "backlog_at_period_end": int(backlog or 0),
        "average_resolution_hours": round(sum(resolution_hours) / len(resolution_hours), 2) if resolution_hours else None,
        "resolved_time_samples": len(resolution_hours),
        "average_first_response_hours": round(sum(response_hours) / len(response_hours), 2) if response_hours else None,
        "first_response_samples": len(response_hours),
        "by_team": by_team,
        "by_status": by_status,
        "by_priority": by_priority,
        "by_type": by_type,
        "by_escalation": by_escalation,
        "requester_24h_windows_started": sla_wait_started,
        "requester_24h_timeouts": sla_timeout_reopened,
        "sla_note": "Cartman currently records a 24-hour requester-reply timeout. It is not a configured first-response or resolution SLA target.",
        "first_response_sla_target": None,
        "resolution_sla_target": None,
        "scope_note": None if department_scope_applied else "Ticket records do not contain a department relation, and linked IAM user departments are unavailable; department filter could not be applied to tickets.",
    }


def _workload_report(connection, start: str, end: str, department_id: str, department_name: str, scope_user_ids: Optional[List[str]] = None, scope_usernames: Optional[List[str]] = None) -> Dict[str, Any]:

    if not _has(connection, "work_items", "task_key", "created_at", "status"):
        return {"available": False, "reason": "Work item records are not available."}
    work_columns = _columns(connection, "work_items")

    scope_parts: List[str] = []
    scope_params: List[str] = []
    if scope_usernames is not None:
        normalized_users = sorted({str(value).strip().lower() for value in scope_usernames if str(value).strip()})
        normalized_ids = sorted({str(value).strip() for value in (scope_user_ids or []) if str(value).strip()})
        if normalized_ids and "assigned_user_id" in work_columns:
            scope_parts.append("CAST(w.assigned_user_id AS TEXT) IN (" + ",".join("?" for _ in normalized_ids) + ")")
            scope_params.extend(normalized_ids)
        if normalized_users and "created_by_username" in work_columns:
            scope_parts.append("lower(trim(COALESCE(w.created_by_username,''))) IN (" + ",".join("?" for _ in normalized_users) + ")")
            scope_params.extend(normalized_users)
    scope_clause = "(" + " OR ".join(scope_parts) + ")" if scope_usernames is not None and scope_parts else ("0=1" if scope_usernames is not None else "")

    user_join = " LEFT JOIN iam_users u ON CAST(u.id AS TEXT)=CAST(w.assigned_user_id AS TEXT)" if _has(connection, "iam_users", "id", "department") and "assigned_user_id" in work_columns else ""

    target_join = ""
    target_clause = ""
    dept_params: List[Any] = []
    if department_id:
        if user_join:
            target_clause = "lower(trim(COALESCE(u.department,'')))=lower(trim(?))"
            dept_params.append(department_name)
        if _has(connection, "work_item_targets", "task_key", "target_type", "target_id"):
            target_join = " LEFT JOIN work_item_targets wt ON wt.task_key=w.task_key"
            target_parts = ["(" + target_clause + ")"] if target_clause else []
            target_parts.append("(wt.target_type='department' AND CAST(wt.target_id AS TEXT)=?)")
            dept_params.append(department_id)
            if "target_name" in _columns(connection, "work_item_targets"):
                target_parts.append("(wt.target_type='department' AND lower(trim(COALESCE(wt.target_name,'')))=lower(trim(?)))")
                dept_params.append(department_name)
            target_clause = "(" + " OR ".join(target_parts) + ")"
        elif not target_clause:
            # No reliable department relationship exists for work item records.
            return {"available": False, "reason": "Work items have no assignment or target relation that can be matched to a department."}
        if not target_clause:
            return {"available": False, "reason": "Work item department assignments cannot be resolved from current records."}
    base_from = "work_items w" + user_join + target_join

    filter_parts = [part for part in (target_clause, scope_clause) if part]
    filter_sql = " AND " + " AND ".join("(" + part + ")" for part in filter_parts) if filter_parts else ""

    select_dept = "COALESCE(u.department,'') AS assigned_department" if user_join else "'' AS assigned_department"

    base_params = tuple(dept_params)
    all_params = base_params + tuple(scope_params)

    period_rows = _rows(connection, "SELECT DISTINCT w.*, " + select_dept + " FROM " + base_from + " WHERE julianday(w.created_at) >= julianday(?) AND julianday(w.created_at) <= julianday(?)" + filter_sql, (start, end) + all_params)

    completed_rows = _rows(connection, "SELECT DISTINCT w.*, " + select_dept + " FROM " + base_from + " WHERE julianday(w.completed_at) >= julianday(?) AND julianday(w.completed_at) <= julianday(?)" + filter_sql, (start, end) + all_params) if "completed_at" in work_columns else []

    current_where = " WHERE " + " AND ".join("(" + part + ")" for part in filter_parts) if filter_parts else ""
    current_rows = _rows(connection, "SELECT DISTINCT w.*, " + select_dept + " FROM " + base_from + current_where, all_params)

    by_status: Dict[str, int] = {}
    by_owner: Dict[str, int] = {}
    by_department: Dict[str, int] = {}
    by_project: Dict[str, int] = {}
    by_priority: Dict[str, int] = {}
    for row in current_rows:
        status = str(row.get("status") or "Unknown")
        by_status[status] = by_status.get(status, 0) + 1
        owner = str(row.get("owner") or "Unassigned")
        by_owner[owner] = by_owner.get(owner, 0) + 1
        dept = str(row.get("assigned_department") or (department_name if department_id else "Unassigned department"))
        by_department[dept] = by_department.get(dept, 0) + 1
        project = str(row.get("project") or "Unassigned")
        by_project[project] = by_project.get(project, 0) + 1
        priority = str(row.get("priority") or "Unknown")
        by_priority[priority] = by_priority.get(priority, 0) + 1
    def sorted_items(value):
        return [{"label": k, "value": v} for k, v in sorted(value.items(), key=lambda item: (-item[1], item[0].casefold()))]
    return {
        "available": True,
        "created_in_period": len(period_rows),
        "completed_in_period": len(completed_rows),
        "current_open": sum(1 for row in current_rows if str(row.get("status")) != "Done"),
        "current_in_progress": sum(1 for row in current_rows if str(row.get("status")) == "In progress"),
        "current_review": sum(1 for row in current_rows if str(row.get("status")) == "Review"),
        "by_status": sorted_items(by_status),
        "by_owner": sorted_items(by_owner)[:12],
        "by_department": sorted_items(by_department),
        "by_project": sorted_items(by_project),
        "by_priority": sorted_items(by_priority),
        "overdue_count": None,
        "overdue_note": "Work item due values are currently free-text labels, not normalized timestamps; overdue compliance is not calculated.",
    }


def _devices_report(connection, start: str, end: str, department_id: str) -> Dict[str, Any]:
    if not _has(connection, "devices", "id", "status"):
        return {"available": False, "reason": "Device inventory is not available."}
    columns = _columns(connection, "devices")
    where = " WHERE 1=1"
    params: tuple = ()
    if department_id and "department_id" in columns:
        where += " AND CAST(department_id AS TEXT)=?"
        params = (department_id,)
    total = _scalar(connection, "SELECT COUNT(*) FROM devices" + where, params)
    by_status = _rows(connection, "SELECT status AS label, COUNT(*) AS value FROM devices" + where + " GROUP BY status ORDER BY value DESC", params)
    by_os = _rows(connection, "SELECT COALESCE(NULLIF(os,''),'Unknown') AS label, COUNT(*) AS value FROM devices" + where + " GROUP BY COALESCE(NULLIF(os,''),'Unknown') ORDER BY value DESC LIMIT 10", params)
    by_type = _rows(connection, "SELECT COALESCE(NULLIF(device_type,''),'Unknown') AS label, COUNT(*) AS value FROM devices" + where + " GROUP BY COALESCE(NULLIF(device_type,''),'Unknown') ORDER BY value DESC LIMIT 10", params) if "device_type" in columns else []
    registered = _count(connection, "devices", "julianday(created_at) >= julianday(?) AND julianday(created_at) <= julianday(?)" + (" AND CAST(department_id AS TEXT)=?" if department_id and "department_id" in columns else ""), (start, end) + ((department_id,) if department_id and "department_id" in columns else ())) if "created_at" in columns else None
    return {"available": True, "current_total": int(total or 0), "registered_in_period": registered, "by_status": by_status, "by_os": by_os, "by_type": by_type, "snapshot_note": "Device status and total are the current database snapshot; historical status reconstruction is not available unless event history has been collected.", "scope_note": None if not department_id or "department_id" in columns else "The device table has no department_id column; device totals remain organization-wide."}


def _inventory_report(connection, department_id: str, department_name: str) -> Dict[str, Any]:
    if not _has(connection, "inventory_assets", "id", "name", "department"):
        return {"available": False, "reason": "Inventory asset records are not available."}
    where = " WHERE 1=1"
    params: tuple = ()
    if department_name:
        where += " AND lower(trim(department))=lower(trim(?))"
        params = (department_name,)
    total = _scalar(connection, "SELECT COUNT(*) FROM inventory_assets" + where, params)
    by_type = _rows(connection, "SELECT COALESCE(NULLIF(type,''),'Unknown') AS label, COUNT(*) AS value FROM inventory_assets" + where + " GROUP BY type ORDER BY value DESC", params)
    return {"available": True, "current_total": int(total or 0), "by_type": by_type}


def _monitoring_report(connection, start: str, end: str, department_id: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {"available": True}
    unscoped_sources: List[str] = []

    def source(table: str, stamp_column: str, extra_select: str = ""):
        columns = _columns(connection, table)
        if not columns or stamp_column not in columns:
            return None
        supports_department = bool(department_id and "device_id" in columns and _has(connection, "devices", "id", "department_id"))
        if department_id and not supports_department:
            unscoped_sources.append(table)
        from_sql = table + " x"
        where = ["julianday(x." + stamp_column + ") >= julianday(?)", "julianday(x." + stamp_column + ") <= julianday(?)"]
        params: List[Any] = [start, end]
        if supports_department:
            from_sql += " JOIN devices d ON CAST(d.id AS TEXT)=CAST(x.device_id AS TEXT)"
            where = ["CAST(d.department_id AS TEXT)=?", "julianday(x." + stamp_column + ") >= julianday(?)", "julianday(x." + stamp_column + ") <= julianday(?)"]
            params = [department_id, start, end]
        return from_sql, " AND ".join(where), tuple(params)

    alert_source = source("monitoring_alerts", "created_at")
    if alert_source and _has(connection, "monitoring_alerts", "id", "status", "severity"):
        from_sql, where_sql, params = alert_source
        result["alerts_created"] = int(_scalar(connection, "SELECT COUNT(*) FROM " + from_sql + " WHERE " + where_sql, params, 0))
        result["alerts_by_severity"] = _rows(connection, "SELECT x.severity AS label, COUNT(*) AS value FROM " + from_sql + " WHERE " + where_sql + " GROUP BY x.severity ORDER BY value DESC", params)
        # Current open alert count is a live snapshot; department scoping is applied only when the device link exists.
        open_where = ["x.status NOT IN ('Resolved','Closed')"]
        open_from = "monitoring_alerts x"
        open_params: tuple = ()
        if department_id and "device_id" in _columns(connection, "monitoring_alerts") and _has(connection, "devices", "id", "department_id"):
            open_from += " JOIN devices d ON CAST(d.id AS TEXT)=CAST(x.device_id AS TEXT)"
            open_where.append("CAST(d.department_id AS TEXT)=?")
            open_params = (department_id,)
        result["alerts_open_now"] = int(_scalar(connection, "SELECT COUNT(*) FROM " + open_from + " WHERE " + " AND ".join(open_where), open_params, 0))
        if _has(connection, "monitoring_alerts", "resolved_at"):
            resolve_source = source("monitoring_alerts", "resolved_at")
            if resolve_source:
                rfrom, rwhere, rparams = resolve_source
                rwhere += " AND x.resolved_at IS NOT NULL AND julianday(x.resolved_at)>=julianday(x.created_at)"
                rows = _rows(connection, "SELECT AVG((julianday(x.resolved_at)-julianday(x.created_at))*24) AS avg_hours, COUNT(*) AS samples FROM " + rfrom + " WHERE " + rwhere, rparams)
                result["alerts_resolved"] = int(rows[0]["samples"] or 0) if rows else 0
                result["average_alert_resolution_hours"] = round(float(rows[0]["avg_hours"]), 2) if rows and rows[0]["avg_hours"] is not None else None
                result["alert_resolution_samples"] = int(rows[0]["samples"] or 0) if rows else 0

    event_source = source("monitoring_events", "occurred_at")
    if event_source and _has(connection, "monitoring_events", "id", "severity"):
        from_sql, where_sql, params = event_source
        result["events_total"] = int(_scalar(connection, "SELECT COUNT(*) FROM " + from_sql + " WHERE " + where_sql, params, 0))
        result["events_by_severity"] = _rows(connection, "SELECT x.severity AS label, COUNT(*) AS value FROM " + from_sql + " WHERE " + where_sql + " GROUP BY x.severity ORDER BY value DESC", params)

    metric_source = source("monitoring_metrics", "collected_at")
    if metric_source and _has(connection, "monitoring_metrics", "metric_name", "value"):
        from_sql, where_sql, params = metric_source
        result["metric_samples"] = int(_scalar(connection, "SELECT COUNT(*) FROM " + from_sql + " WHERE " + where_sql, params, 0))
        result["metric_averages"] = _rows(connection, "SELECT x.metric_name AS label, ROUND(AVG(x.value),2) AS value, x.unit, COUNT(*) AS samples FROM " + from_sql + " WHERE " + where_sql + " GROUP BY x.metric_name, x.unit ORDER BY x.metric_name LIMIT 16", params)

    for table, alias in (("availability_checks", "availability"), ("service_checks", "service_checks")):
        check_source = source(table, "checked_at")
        if check_source and _has(connection, table, "status"):
            from_sql, where_sql, params = check_source
            rows = _rows(connection, "SELECT x.status, x.response_ms FROM " + from_sql + " WHERE " + where_sql, params) if "response_ms" in _columns(connection, table) else _rows(connection, "SELECT x.status, NULL AS response_ms FROM " + from_sql + " WHERE " + where_sql, params)
            good = sum(1 for row in rows if str(row.get("status") or "").strip().lower() in {"online", "ok", "success", "available", "up", "healthy"})
            latencies = [float(row["response_ms"]) for row in rows if row.get("response_ms") is not None]
            result[alias] = {"checks": len(rows), "successful": good, "success_rate_percent": round(100 * good / len(rows), 2) if rows else None, "average_response_ms": round(sum(latencies) / len(latencies), 2) if latencies else None}

    if not any(key in result for key in ("alerts_created", "events_total", "metric_samples", "availability", "service_checks")):
        return {"available": False, "reason": "No monitoring metric/event/alert/check source is available."}
    if unscoped_sources:
        result["scope_note"] = "Department filtering is not supported by these source tables because they have no device relation: " + ", ".join(sorted(set(unscoped_sources))) + ". Those measurements remain organization-wide."
    return result


def _network_vpn_report(connection, start: str, end: str, department_name: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {"available": True, "network_inventory": {}, "vpn": {}}
    tables = _tables(connection)
    for table in ("network_devices", "network_subnets", "network_ip_addresses", "network_dns_records", "network_dhcp_scopes", "network_dhcp_leases"):
        if table in tables:
            result["network_inventory"][table] = _scalar(connection, "SELECT COUNT(*) FROM \"" + table + "\"")
    for table in ("vpn_networks", "vpn_gateways", "vpn_peers", "vpn_access_policies", "vpn_site_links"):
        if table in tables:
            result["vpn"][table] = _scalar(connection, "SELECT COUNT(*) FROM \"" + table + "\"")
    if _has(connection, "vpn_audit_logs", "created_at", "event"):
        result["vpn"]["events_in_period"] = _count(connection, "vpn_audit_logs", "julianday(created_at) >= julianday(?) AND julianday(created_at) <= julianday(?)", (start, end))
        result["vpn"]["events_by_type"] = _rows(connection, "SELECT event AS label, COUNT(*) AS value FROM vpn_audit_logs WHERE julianday(created_at) >= julianday(?) AND julianday(created_at) <= julianday(?) GROUP BY event ORDER BY value DESC LIMIT 12", (start, end))
    if department_name and _has(connection, "vpn_networks", "department"):
        result["vpn"]["department_networks"] = _count(connection, "vpn_networks", "lower(trim(department))=lower(trim(?))", (department_name,))
    if department_name and result["network_inventory"]:
        result["scope_note"] = "Network infrastructure records do not currently carry a department relationship, so those totals remain organization-wide. VPN department counts use the stored vpn_networks.department value."
    elif department_name:
        result["scope_note"] = "Network infrastructure records do not currently carry a department relationship. VPN counts are organization-wide unless the stored VPN department field is available."
    else:
        result["scope_note"] = "Network and VPN records are shown as organization-wide configuration counts; only VPN audit events are period-based."
    if not result["network_inventory"] and not result["vpn"]:
        return {"available": False, "reason": "Network and VPN source tables are not available."}
    return result


def _deployment_report(connection, start: str, end: str, department_id: str = "") -> Dict[str, Any]:
    if not _has(connection, "device_tasks", "created_at", "action", "status"):
        return {"available": False, "reason": "Endpoint task queue records are not available."}
    join = ""
    where = ["julianday(t.created_at) >= julianday(?)", "julianday(t.created_at) <= julianday(?)"]
    params: List[Any] = [start, end]
    if department_id and _has(connection, "device_tasks", "device_id") and _has(connection, "devices", "id", "department_id"):
        join = " JOIN devices d ON CAST(d.id AS TEXT)=CAST(t.device_id AS TEXT)"
        where.append("CAST(d.department_id AS TEXT)=?")
        params.append(department_id)
    from_sql = "device_tasks t" + join
    where_sql = " AND ".join(where)
    return {
        "available": True,
        "queued_in_period": int(_scalar(connection, "SELECT COUNT(*) FROM " + from_sql + " WHERE " + where_sql, tuple(params), 0)),
        "by_action": _rows(connection, "SELECT t.action AS label, COUNT(*) AS value FROM " + from_sql + " WHERE " + where_sql + " GROUP BY t.action ORDER BY value DESC", tuple(params)),
        "by_status": _rows(connection, "SELECT t.status AS label, COUNT(*) AS value FROM " + from_sql + " WHERE " + where_sql + " GROUP BY t.status ORDER BY value DESC", tuple(params)),
        "scope_note": None if not department_id or join else "Endpoint task records cannot be filtered by department because device-to-department linkage is unavailable.",
    }


def _automation_report(connection, start: str, end: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {"available": False, "reason": "No automation execution records are available."}
    if _has(connection, "automation_executions", "started_at", "status"):
        result = {"available": True, "executions": _count(connection, "automation_executions", "julianday(started_at) >= julianday(?) AND julianday(started_at) <= julianday(?)", (start, end)), "by_status": _rows(connection, "SELECT status AS label, COUNT(*) AS value FROM automation_executions WHERE julianday(started_at) >= julianday(?) AND julianday(started_at) <= julianday(?) GROUP BY status ORDER BY value DESC", (start, end))}
    workflow = {"available": False}
    if _has(connection, "cartman_workflow_runs", "started_at", "status"):
        workflow = {"available": True, "runs": _count(connection, "cartman_workflow_runs", "julianday(started_at) >= julianday(?) AND julianday(started_at) <= julianday(?)", (start, end)), "by_status": _rows(connection, "SELECT status AS label, COUNT(*) AS value FROM cartman_workflow_runs WHERE julianday(started_at) >= julianday(?) AND julianday(started_at) <= julianday(?) GROUP BY status ORDER BY value DESC", (start, end))}
    result["workflow_runs"] = workflow
    result["scope_note"] = "Automation and workflow execution records do not currently store a department or support-team relationship; this section is organization-wide."
    if result.get("available") or workflow.get("available"):
        result.pop("reason", None)
        result["available"] = True
    return result


def _activity_report(connection, start_epoch: int, end_epoch: int, department_name: str = "", scope_usernames: Optional[List[str]] = None) -> Dict[str, Any]:

    result: Dict[str, Any] = {"available": False, "reason": "No first-party user activity samples or login attempts are available in this database."}
    has_iam_department = bool(department_name and _has(connection, "iam_users", "username", "department"))
    if _has(connection, "cartman_user_activity_minutes", "username", "bucket_start", "active_seconds"):
        sql = "SELECT COUNT(DISTINCT a.username), SUM(a.active_seconds), COUNT(*) FROM cartman_user_activity_minutes a"
        where = ["a.bucket_start >= ?", "a.bucket_start <= ?"]
        params: List[Any] = [start_epoch, end_epoch]
        if has_iam_department:
            sql += " JOIN iam_users u ON lower(trim(u.username))=lower(trim(a.username))"

            where.append("lower(trim(COALESCE(u.department,'')))=lower(trim(?))")

            params.append(department_name)

        if scope_usernames is not None:
            normalized = sorted({str(value).strip().lower() for value in scope_usernames if str(value).strip()})
            if normalized:
                where.append("lower(trim(a.username)) IN (" + ",".join("?" for _ in normalized) + ")")
                params.extend(normalized)
            else:
                where.append("0=1")

        row = connection.execute(sql + " WHERE " + " AND ".join(where), tuple(params)).fetchone()

        result = {"available": True, "active_users": int(row[0] or 0), "active_seconds": int(row[1] or 0), "activity_samples": int(row[2] or 0)}
    if _has(connection, "auth_login_attempts", "attempted_at", "succeeded"):
        login_from = "auth_login_attempts a"
        login_where = ["a.attempted_at >= ?", "a.attempted_at <= ?"]
        login_params: List[Any] = [start_epoch, end_epoch]
        if has_iam_department:
            login_from += " JOIN iam_users u ON lower(trim(u.username))=lower(trim(a.username_norm))"

            login_where.append("lower(trim(COALESCE(u.department,'')))=lower(trim(?))")

            login_params.append(department_name)

        if scope_usernames is not None:
            normalized = sorted({str(value).strip().lower() for value in scope_usernames if str(value).strip()})
            if normalized:
                login_where.append("lower(trim(a.username_norm)) IN (" + ",".join("?" for _ in normalized) + ")")
                login_params.extend(normalized)
            else:
                login_where.append("0=1")

        result["login_attempts"] = int(_scalar(connection, "SELECT COUNT(*) FROM " + login_from + " WHERE " + " AND ".join(login_where), tuple(login_params), 0))

        result["successful_logins"] = int(_scalar(connection, "SELECT COUNT(*) FROM " + login_from + " WHERE " + " AND ".join(login_where + ["a.succeeded=1"]), tuple(login_params), 0))
        result["failed_logins"] = int(_scalar(connection, "SELECT COUNT(*) FROM " + login_from + " WHERE " + " AND ".join(login_where + ["a.succeeded=0"]), tuple(login_params), 0))
        result["available"] = True
        result.pop("reason", None)
    if _has(connection, "auth_sessions", "created_at", "last_seen"):
        session_from = "auth_sessions s"
        session_where = ["s.created_at >= ?", "s.created_at <= ?"]
        session_params: List[Any] = [start_epoch, end_epoch]
        if (has_iam_department or scope_usernames is not None) and _has(connection, "auth_accounts", "id", "username"):
            session_from += " JOIN auth_accounts a ON a.id=s.account_id"
            if has_iam_department:
                session_from += " JOIN iam_users u ON lower(trim(u.username))=lower(trim(a.username))"
                session_where.append("lower(trim(COALESCE(u.department,'')))=lower(trim(?))")
                session_params.append(department_name)

        if scope_usernames is not None and _has(connection, "auth_accounts", "id", "username"):
            normalized = sorted({str(value).strip().lower() for value in scope_usernames if str(value).strip()})
            if normalized:
                session_where.append("lower(trim(a.username)) IN (" + ",".join("?" for _ in normalized) + ")")
                session_params.extend(normalized)
            else:
                session_where.append("0=1")

        if scope_usernames is not None and not _has(connection, "auth_accounts", "id", "username"):
            result["sessions_created"] = None
        else:
            result["sessions_created"] = int(_scalar(connection, "SELECT COUNT(*) FROM " + session_from + " WHERE " + " AND ".join(session_where), tuple(session_params), 0))

    if department_name and not has_iam_department:
        result["scope_note"] = "The selected department cannot be applied to user activity because IAM department links are not available."
    return result


def _remote_report(connection, start: str, end: str) -> Dict[str, Any]:
    if not _has(connection, "remote_access_sessions", "created_at", "status"):
        return {"available": False, "reason": "Remote access session history is not available."}
    rows = _rows(connection, "SELECT * FROM remote_access_sessions WHERE julianday(created_at) >= julianday(?) AND julianday(created_at) <= julianday(?)", (start, end))
    durations = []
    for row in rows:
        try:
            a = datetime.fromisoformat(str(row.get("started_at") or "").replace(" ", "T"))
            b = datetime.fromisoformat(str(row.get("ended_at") or "").replace(" ", "T"))
            if b >= a:
                durations.append((b - a).total_seconds() / 60)
        except (TypeError, ValueError):
            pass
    return {"available": True, "sessions": len(rows), "by_status": _rows(connection, "SELECT status AS label, COUNT(*) AS value FROM remote_access_sessions WHERE julianday(created_at) >= julianday(?) AND julianday(created_at) <= julianday(?) GROUP BY status ORDER BY value DESC", (start, end)), "average_duration_minutes": round(sum(durations) / len(durations), 2) if durations else None, "duration_samples": len(durations), "scope_note": "Remote-access session records do not currently store department or support-team relations; this section is organization-wide."}


def _software_report(connection, start: str, end: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {"available": False, "reason": "Software catalog and change history are not available."}
    if _has(connection, "software_catalog", "id", "name"):
        result = {
            "available": True,
            "catalog_total": _count(connection, "software_catalog"),
            "catalog_by_status": _rows(connection, "SELECT COALESCE(NULLIF(status,''),'Unknown') AS label, COUNT(*) AS value FROM software_catalog GROUP BY status ORDER BY value DESC") if "status" in _columns(connection, "software_catalog") else [],
            "catalog_by_os": _rows(connection, "SELECT COALESCE(NULLIF(target_os,''),'Any') AS label, COUNT(*) AS value FROM software_catalog GROUP BY target_os ORDER BY value DESC") if "target_os" in _columns(connection, "software_catalog") else [],
        }
    if _has(connection, "software_audit_history", "occurred_at", "action"):
        changes = _count(connection, "software_audit_history", "julianday(occurred_at) >= julianday(?) AND julianday(occurred_at) <= julianday(?)", (start, end))
        change_types = _rows(connection, "SELECT action AS label, COUNT(*) AS value FROM software_audit_history WHERE julianday(occurred_at) >= julianday(?) AND julianday(occurred_at) <= julianday(?) GROUP BY action ORDER BY value DESC", (start, end))
        if not result.get("available"):
            result = {"available": True}
        result["changes_in_period"] = changes
        result["changes_by_action"] = change_types
    result["scope_note"] = "Software catalogue and audit records do not currently have a consistent department or support-team relation; catalogue totals are organization-wide."
    return result


def _platform_report(connection, start: str, end: str) -> Dict[str, Any]:
    sources = (
        ("iam_audit_events", "occurred_at", "action", "IAM audit events"),
        ("cartman_api_key_access_logs", "created_at", "method", "API key requests"),
        ("cartman_connector_logs", "created_at", "action", "Connector activity"),
        ("knowledge_article_audit", "created_at", "action", "Knowledge article changes"),
        ("cartman_alert_action_history", "occurred_at", "action", "Alert actions"),
        ("device_connection_requests", "created_at", "status", "Endpoint connection requests"),
        ("network_discovery_jobs", "created_at", "status", "Network discovery jobs"),
    )
    rows = []
    for table, stamp, group, label in sources:
        if _has(connection, table, stamp):
            total = _count(connection, table, "julianday(" + stamp + ") >= julianday(?) AND julianday(" + stamp + ") <= julianday(?)", (start, end))
            if total is not None:
                rows.append({"label": label, "value": total})
    result: Dict[str, Any] = {"available": bool(rows), "by_source": rows}
    if not rows:
        result["reason"] = "No platform audit or connection activity sources are available."
    result["scope_note"] = "Platform audit sources do not share a universal department or support-team relation; activity totals are organization-wide."
    if _has(connection, "device_connection_requests", "created_at", "status"):
        result["device_requests_by_status"] = _rows(connection, "SELECT status AS label, COUNT(*) AS value FROM device_connection_requests WHERE julianday(created_at) >= julianday(?) AND julianday(created_at) <= julianday(?) GROUP BY status ORDER BY value DESC", (start, end))
    return result


def _system_report(connection, start: str, end: str, department_id: str = "") -> Dict[str, Any]:
    if not _has(connection, "cartman_process_metric_samples", "device_id", "collected_at"):
        return {"available": False, "reason": "CartmanClient process metric samples are not available."}
    columns = _columns(connection, "cartman_process_metric_samples")
    from_sql = "cartman_process_metric_samples p"
    where = ["julianday(p.collected_at) >= julianday(?)", "julianday(p.collected_at) <= julianday(?)"]
    params: List[Any] = [start, end]
    if department_id and _has(connection, "devices", "id", "department_id"):
        from_sql += " JOIN devices d ON CAST(d.id AS TEXT)=CAST(p.device_id AS TEXT)"
        where.append("CAST(d.department_id AS TEXT)=?")
        params.append(department_id)
    aggregate_fields = (
        ("cpu_percent", "Average process CPU (%)"),
        ("memory_percent", "Average process memory (%)"),
        ("disk_read_bytes_per_sec", "Average disk read (bytes/s)"),
        ("disk_write_bytes_per_sec", "Average disk write (bytes/s)"),
        ("network_rx_bytes_per_sec", "Average network receive (bytes/s)"),
        ("network_tx_bytes_per_sec", "Average network transmit (bytes/s)"),
    )
    metrics = []
    for column, label in aggregate_fields:
        if column in columns:
            row = _rows(connection, "SELECT AVG(p." + column + ") AS value, COUNT(p." + column + ") AS samples FROM " + from_sql + " WHERE " + " AND ".join(where), tuple(params))
            if row and row[0]["samples"]:
                metrics.append({"label": label, "value": round(float(row[0]["value"] or 0), 2), "samples": int(row[0]["samples"])})
    sample_count = _scalar(connection, "SELECT COUNT(*) FROM " + from_sql + " WHERE " + " AND ".join(where), tuple(params), 0)
    return {"available": bool(metrics), "samples": int(sample_count or 0), "averages": metrics, "reason": None if metrics else "No process metric samples were collected in this period.", "scope_note": None if not department_id or _has(connection, "devices", "id", "department_id") else "Device metric samples cannot be scoped to a department because the current device relationship is unavailable."}


def _build_summary(connection, start: str, end: str, start_epoch: int, end_epoch: int, department_id: str = "", team: str = "", report_scope: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:

    department_name = _department_name(connection, department_id) if department_id else ""

    scope_kind = str((report_scope or {}).get("type") or "")
    scoped_usernames = (report_scope or {}).get("usernames") if scope_kind in {"user", "group"} else None
    scoped_user_ids = (report_scope or {}).get("user_ids") if scope_kind in {"user", "group"} else None

    result = {

        "period": {"start": start, "end": end, "timezone": "UTC"},
        "filters": {"department_id": department_id, "department": department_name or "All departments", "team": team or "All support teams"},
        "tickets": _ticket_report(connection, start, end, department_id, department_name, team, scoped_usernames),

        "workload": _workload_report(connection, start, end, department_id, department_name, scoped_user_ids, scoped_usernames),

        "devices": _devices_report(connection, start, end, department_id),
        "inventory": _inventory_report(connection, department_id, department_name),
        "monitoring": _monitoring_report(connection, start, end, department_id),
        "network_vpn": _network_vpn_report(connection, start, end, department_name),
        "deployment": _deployment_report(connection, start, end, department_id),
        "automation": _automation_report(connection, start, end),
        "activity": _activity_report(connection, start_epoch, end_epoch, department_name, scoped_usernames),

        "remote_access": _remote_report(connection, start, end),
        "software": _software_report(connection, start, end),
        "platform_activity": _platform_report(connection, start, end),
        "system_metrics": _system_report(connection, start, end, department_id),
    }
    tickets = result["tickets"]
    workload = result["workload"]
    devices = result["devices"]
    monitoring = result["monitoring"]
    result["kpis"] = [
        {"key": "tickets_created", "label": "Tickets created", "value": tickets.get("created") if tickets.get("available") else None},
        {"key": "tickets_resolved", "label": "Tickets resolved", "value": tickets.get("resolved_in_period") if tickets.get("available") else None},
        {"key": "work_open", "label": "Open work items", "value": workload.get("current_open") if workload.get("available") else None},
        {"key": "devices", "label": "Managed devices", "value": devices.get("current_total") if devices.get("available") else None},
        {"key": "alerts_open", "label": "Open alerts", "value": monitoring.get("alerts_open_now") if monitoring.get("available") else None},
    ]
    if report_scope:
        result["report_scope"] = {"type": report_scope.get("type"), "id": report_scope.get("id"), "name": report_scope.get("name"), "member_count": report_scope.get("member_count")}
    if scope_kind in {"user", "group"}:
        excluded = {"devices", "inventory", "monitoring", "network_vpn", "deployment", "automation", "remote_access", "software", "platform_activity", "system_metrics"}
        reason = "Omitted from this User/Group report because the source records do not contain a reliable user or group-member relationship."
        for section_name in excluded:
            section_data = result.get(section_name)
            if isinstance(section_data, dict):
                section_data["available"] = False
                section_data["scope_excluded"] = True
                section_data["reason"] = reason
        for metric in result.get("kpis", []):
            if metric.get("key") in {"devices", "alerts_open"}:
                metric["value"] = None
    result["coverage"] = {key: bool(value.get("available")) for key, value in result.items() if isinstance(value, dict) and "available" in value}

    return result




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


def _report_schema(connection):

    connection.execute("""
        CREATE TABLE IF NOT EXISTS cartman_generated_reports (
            id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            stored_path TEXT NOT NULL,
            created_by_username TEXT NOT NULL DEFAULT '',
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            filters_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    connection.execute("CREATE INDEX IF NOT EXISTS idx_cartman_generated_reports_created ON cartman_generated_reports(created_at DESC)")


def _pdf_text(value: Any, font_name: str) -> str:
    text = str(value if value is not None else "—")
    # Base Helvetica has no Turkish dotless/dotted-I and g-breve; use a readable
    # transliteration only when a Unicode system font cannot be registered.
    if font_name == "Helvetica":
        table = str.maketrans({"ğ": "g", "Ğ": "G", "ş": "s", "Ş": "S", "ı": "i", "İ": "I", "ç": "c", "Ç": "C", "ö": "o", "Ö": "O", "ü": "u", "Ü": "U"})
        text = text.translate(table)
    return text


def _make_pdf(path: Path, summary: Dict[str, Any], sections: List[str], generated_by: str) -> None:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen import canvas
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="PDF engine is not installed. Run: .venv/bin/pip install reportlab") from exc

    font_regular = "Helvetica"
    font_bold = "Helvetica-Bold"
    for candidate in (
        ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
        ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf"),
        (r"C:\\Windows\\Fonts\\arial.ttf", r"C:\\Windows\\Fonts\\arialbd.ttf"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ):
        if Path(candidate[0]).exists():
            try:
                pdfmetrics.registerFont(TTFont("CartmanReport", candidate[0]))
                font_regular = "CartmanReport"
                if Path(candidate[1]).exists():
                    pdfmetrics.registerFont(TTFont("CartmanReportBold", candidate[1]))
                    font_bold = "CartmanReportBold"
                else:
                    font_bold = font_regular
                break
            except Exception:
                continue

    page_w, page_h = A4
    pdf = canvas.Canvas(str(path), pagesize=A4, pageCompression=1)
    pdf.setTitle("Cartman Operational Report")
    pdf.setAuthor("Cartman")
    margin = 42
    y = page_h - 46
    palette = [colors.HexColor("#6965E8"), colors.HexColor("#21A6A1"), colors.HexColor("#E7A642"), colors.HexColor("#E36B73"), colors.HexColor("#5487D8"), colors.HexColor("#8A6CCF")]

    def page_header():
        nonlocal y
        pdf.setFillColor(colors.HexColor("#111A2D"))
        pdf.rect(0, page_h - 82, page_w, 82, stroke=0, fill=1)
        pdf.setFillColor(colors.white)
        pdf.setFont(font_bold, 17)
        pdf.drawString(margin, page_h - 38, "CARTMAN  /  OPERATIONAL REPORT")
        pdf.setFillColor(colors.HexColor("#C5CEE0"))
        pdf.setFont(font_regular, 8)
        pdf.drawString(margin, page_h - 56, _pdf_text(summary["period"]["start"] + "  —  " + summary["period"]["end"], font_regular)[:115])
        pdf.drawRightString(page_w - margin, page_h - 56, "Generated by " + _pdf_text(generated_by, font_regular)[:35])
        y = page_h - 108

    def ensure_space(height: float):
        nonlocal y
        if y - height < 48:
            pdf.showPage()
            page_header()

    def heading(text: str):
        nonlocal y
        ensure_space(34)
        pdf.setFillColor(colors.HexColor("#252F45"))
        pdf.setFont(font_bold, 12)
        pdf.drawString(margin, y, _pdf_text(text, font_bold)[:100])
        y -= 19

    def line(text: str, bold: bool = False, color=None):
        nonlocal y
        ensure_space(16)
        pdf.setFillColor(color or colors.HexColor("#4C566B"))
        pdf.setFont(font_bold if bold else font_regular, 8.5)
        pdf.drawString(margin + (4 if not bold else 0), y, _pdf_text(text, font_bold if bold else font_regular)[:130])
        y -= 14

    def chart(title: str, rows: List[Dict[str, Any]]):
        nonlocal y
        if not rows:
            return
        heading(title)
        max_value = max([float(row.get("value") or 0) for row in rows] or [1]) or 1
        rows = rows[:8]
        for index, row in enumerate(rows):
            ensure_space(19)
            label = _pdf_text(row.get("label") or "Unspecified", font_regular)[:36]
            value = float(row.get("value") or 0)
            x = margin
            pdf.setFillColor(colors.HexColor("#68738A"))
            pdf.setFont(font_regular, 7.5)
            pdf.drawString(x, y, label)
            bar_x = margin + 136
            bar_w = 275 * max(0.0, min(1.0, value / max_value))
            pdf.setFillColor(colors.HexColor("#E9ECF3"))
            pdf.roundRect(bar_x, y - 2, 275, 8, 3, stroke=0, fill=1)
            pdf.setFillColor(palette[index % len(palette)])
            pdf.roundRect(bar_x, y - 2, max(2, bar_w), 8, 3, stroke=0, fill=1)
            pdf.setFillColor(colors.HexColor("#252F45"))
            pdf.setFont(font_bold, 7.5)
            pdf.drawRightString(page_w - margin, y, str(row.get("value") or 0))
            y -= 17
        y -= 5

    page_header()
    heading("Report scope")

    report_scope = summary.get("report_scope") or {}
    scope_labels = {"user": "User", "group": "Group", "department": "Department"}
    line("Report target: {} · {}".format(scope_labels.get(report_scope.get("type"), "Organization"), report_scope.get("name") or "Entire organization"))
    if report_scope.get("type") == "group":
        line("Active IAM group members included: {}".format(report_scope.get("member_count", 0)))
    line("Department filter: " + str(summary["filters"].get("department") or "All departments"))

    line("Support team: " + str(summary["filters"].get("team") or "All support teams"))
    line("All figures below are calculated from saved Cartman records in the selected period or are explicitly labeled as current snapshots.")
    heading("Executive overview")
    for item in summary.get("kpis", []):
        if item.get("value") is not None:
            line("{}: {}".format(item.get("label"), item.get("value")), bold=True)

    source_by_section = {
        "tickets": ("tickets", "Ticket and response records"), "sla": ("tickets", "Ticket response and requester timeout records"),
        "workload": ("workload", "Work item records"), "devices": ("devices", "Device and inventory records"),
        "monitoring": ("monitoring", "Monitoring records"), "network_vpn": ("network_vpn", "Network and VPN records"),
        "deployment": ("deployment", "Endpoint task records"), "automation": ("automation", "Automation and workflow records"),
        "activity": ("activity", "User activity and authentication records"), "remote_access": ("remote_access", "Remote access session records"),
        "software": ("software", "Software catalogue and change records"), "platform_activity": ("platform_activity", "Platform audit records"),
        "system_metrics": ("system_metrics", "Process telemetry records"),
    }
    unavailable = []
    for section in sections:
        mapped = source_by_section.get(section)
        if mapped and not summary.get(mapped[0], {}).get("available"):
            unavailable.append((mapped[1], mapped[0]))

    if unavailable:
        heading("Selected sections without available source data")
        for item, source_key in unavailable:

            source_data = summary.get(source_key, {})
            line(item + ": " + str(source_data.get("reason") or "No stored source data was available for this period."))


    def has(name):
        return name in sections

    if has("tickets") and summary.get("tickets", {}).get("available"):
        data = summary["tickets"]
        heading("Tickets and service desk")
        for label, key in (("Created in period", "created"), ("Resolved in period", "resolved_in_period"), ("Backlog at period end", "backlog_at_period_end"), ("Average first response (hours)", "average_first_response_hours"), ("Average resolution (hours)", "average_resolution_hours")):
            line(label + ": " + str(data.get(key) if data.get(key) is not None else "Not measured"))
        chart("Tickets by support team", data.get("by_team", []))
        chart("Tickets by status", data.get("by_status", []))
        chart("Tickets by priority", data.get("by_priority", []))
        chart("Tickets by type", data.get("by_type", []))
        chart("Tickets by escalation", data.get("by_escalation", []))
        if data.get("scope_note"):
            line(str(data["scope_note"]))
    if has("sla") and summary.get("tickets", {}).get("available"):
        data = summary["tickets"]
        heading("SLA and response timing")
        line("24-hour requester-reply windows started: " + str(data.get("requester_24h_windows_started") if data.get("requester_24h_windows_started") is not None else "Not tracked"))
        line("Tickets auto-reopened after requester timeout: " + str(data.get("requester_24h_timeouts") if data.get("requester_24h_timeouts") is not None else "Not tracked"))
        line("Average first response (hours): " + str(data.get("average_first_response_hours") if data.get("average_first_response_hours") is not None else "Not measured"))
        line("Average resolution (hours): " + str(data.get("average_resolution_hours") if data.get("average_resolution_hours") is not None else "Not measured"))
        line("First-response samples: " + str(data.get("first_response_samples", 0)) + " · Resolution samples: " + str(data.get("resolved_time_samples", 0)))
        line(str(data.get("sla_note") or "No SLA policy metadata."))
        if data.get("scope_note"):
            line(str(data["scope_note"]))
    if has("workload") and summary.get("workload", {}).get("available"):
        data = summary["workload"]
        heading("Workload")
        for label, key in (("Created in period", "created_in_period"), ("Completed in period", "completed_in_period"), ("Current open", "current_open"), ("Current in progress", "current_in_progress"), ("Current in review", "current_review")):
            line(label + ": " + str(data.get(key, 0)))
        chart("Work items by status", data.get("by_status", []))
        chart("Current workload by owner", data.get("by_owner", []))
        chart("Current workload by department", data.get("by_department", []))
        chart("Current workload by project", data.get("by_project", []))
        chart("Current workload by priority", data.get("by_priority", []))
        line(str(data.get("overdue_note") or ""))
        if data.get("scope_note"):
            line(str(data["scope_note"]))
    if has("devices") and summary.get("devices", {}).get("available"):
        data = summary["devices"]
        heading("Endpoints and device inventory")
        line("Managed devices (current snapshot): " + str(data.get("current_total", 0)))
        line("Newly registered in period: " + str(data.get("registered_in_period") if data.get("registered_in_period") is not None else "Not tracked"))
        chart("Devices by status", data.get("by_status", []))
        chart("Devices by operating system", data.get("by_os", []))
        chart("Devices by type", data.get("by_type", []))
        if data.get("scope_note"):
            line(str(data["scope_note"]))
        inv = summary.get("inventory", {})
        if inv.get("available"):
            line("Inventory assets (current snapshot): " + str(inv.get("current_total", 0)))
            chart("Inventory by type", inv.get("by_type", []))
        line(str(data.get("snapshot_note") or ""))
    if has("monitoring") and summary.get("monitoring", {}).get("available"):
        data = summary["monitoring"]
        heading("Monitoring and availability")
        for label, key in (("Alerts created", "alerts_created"), ("Alerts resolved", "alerts_resolved"), ("Open alerts now", "alerts_open_now"), ("Events", "events_total"), ("Metric samples", "metric_samples"), ("Average alert resolution (hours)", "average_alert_resolution_hours")):
            if key in data:
                line(label + ": " + str(data.get(key) if data.get(key) is not None else "Not measured"))
        chart("Alerts by severity", data.get("alerts_by_severity", []))
        chart("Events by severity", data.get("events_by_severity", []))
        chart("Metric averages", data.get("metric_averages", []))
        for key, label in (("availability", "Availability"), ("service_checks", "Service checks")):
            value = data.get(key)
            if value:
                line("{} success rate: {}% ({} checks)".format(label, value.get("success_rate_percent") if value.get("success_rate_percent") is not None else "Not measured", value.get("checks", 0)))
                line("{} average response: {} ms".format(label, value.get("average_response_ms") if value.get("average_response_ms") is not None else "Not measured"))
        if data.get("scope_note"):
            line(str(data["scope_note"]))
    if has("network_vpn") and summary.get("network_vpn", {}).get("available"):
        data = summary["network_vpn"]
        heading("Network and VPN")
        for key, value in data.get("network_inventory", {}).items():
            line(key.replace("_", " ").title() + ": " + str(value))
        for key, value in data.get("vpn", {}).items():
            if isinstance(value, (int, float)):
                line(key.replace("_", " ").title() + ": " + str(value))
        chart("VPN activity by event", data.get("vpn", {}).get("events_by_type", []))
        if data.get("scope_note"):
            line(str(data["scope_note"]))
    if has("deployment") and summary.get("deployment", {}).get("available"):
        data = summary["deployment"]
        heading("Endpoint tasks and deployment")
        line("Tasks created in period: " + str(data.get("queued_in_period", 0)))
        chart("Endpoint tasks by action", data.get("by_action", []))
        chart("Endpoint tasks by outcome", data.get("by_status", []))
        if data.get("scope_note"):
            line(str(data["scope_note"]))
    if has("automation") and summary.get("automation", {}).get("available"):
        data = summary["automation"]
        heading("Automation and workflows")
        if data.get("executions") is not None:
            line("Automation executions: " + str(data["executions"]))
            chart("Automation executions by status", data.get("by_status", []))
        if data.get("workflow_runs") and data["workflow_runs"].get("available"):
            line("Workflow runs: " + str(data["workflow_runs"].get("runs", 0)))
            chart("Workflow runs by status", data["workflow_runs"].get("by_status", []))
        if data.get("scope_note"):
            line(str(data["scope_note"]))
    if has("activity") and summary.get("activity", {}).get("available"):
        data = summary["activity"]
        heading("User activity and authentication")
        for label, key in (("Active users", "active_users"), ("Active time (hours)", "active_seconds"), ("Login attempts", "login_attempts"), ("Successful logins", "successful_logins"), ("Failed logins", "failed_logins"), ("Sessions created", "sessions_created")):
            if key in data and data.get(key) is not None:
                value = round(float(data[key]) / 3600, 2) if key == "active_seconds" else data[key]
                line(label + ": " + str(value))
        if data.get("scope_note"):
            line(str(data["scope_note"]))
    if has("remote_access") and summary.get("remote_access", {}).get("available"):
        data = summary["remote_access"]
        heading("Remote access")
        line("Sessions created in period: " + str(data.get("sessions", 0)))
        line("Average completed session duration (minutes): " + str(data.get("average_duration_minutes") if data.get("average_duration_minutes") is not None else "Not measured"))
        chart("Remote access sessions by status", data.get("by_status", []))
        if data.get("scope_note"):
            line(str(data["scope_note"]))
    if has("software") and summary.get("software", {}).get("available"):
        data = summary["software"]
        heading("Software catalogue and changes")
        line("Software catalogue entries (current snapshot): " + str(data.get("catalog_total", "Not tracked")))
        line("Software record changes in period: " + str(data.get("changes_in_period", "Not tracked")))
        chart("Software changes by action", data.get("changes_by_action", []))
        chart("Software catalogue by status", data.get("catalog_by_status", []))
        chart("Software catalogue by OS", data.get("catalog_by_os", []))
        if data.get("scope_note"):
            line(str(data["scope_note"]))
    if has("platform_activity") and summary.get("platform_activity", {}).get("available"):
        data = summary["platform_activity"]
        heading("Platform and audit activity")
        chart("Audit and platform activity by source", data.get("by_source", []))
        chart("Endpoint connection requests by status", data.get("device_requests_by_status", []))
        if data.get("scope_note"):
            line(str(data["scope_note"]))
    if has("system_metrics") and summary.get("system_metrics", {}).get("available"):
        data = summary["system_metrics"]
        heading("Process-level system metrics")
        line("Process metric samples: " + str(data.get("samples", 0)))
        chart("Average process metrics", data.get("averages", []))
        if data.get("scope_note"):
            line(str(data["scope_note"]))

    pdf.setStrokeColor(colors.HexColor("#D8DDE7"))
    pdf.line(margin, 34, page_w - margin, 34)
    pdf.setFillColor(colors.HexColor("#7B8496"))
    pdf.setFont(font_regular, 7)
    pdf.drawString(margin, 22, "Cartman · Operational reporting · Generated from the Cartman database")
    pdf.save()


@router.get("/meta")
def reports_meta(request: Request):
    _require_admin(request)
    with _connect() as connection:
        return _meta(connection)


@router.get("/summary")
def reports_summary(request: Request, start: str, end: str, department_id: str = "", team: str = ""):
    _require_admin(request)
    sql_start, sql_end, start_epoch, end_epoch, iso_start, iso_end = _period(start, end)
    if len(team) > 160:
        raise HTTPException(status_code=422, detail="Team filter is too long.")
    with _connect() as connection:
        result = _build_summary(connection, sql_start, sql_end, start_epoch, end_epoch, department_id, team)
        result["period"]["start"] = iso_start
        result["period"]["end"] = iso_end
        return result


@router.post("/pdf", status_code=201)
def create_report_pdf(payload: Dict[str, Any], request: Request):
    user = _require_admin(request)
    sql_start, sql_end, start_epoch, end_epoch, iso_start, iso_end = _period(payload.get("start", ""), payload.get("end", ""))
    department_id = str(payload.get("department_id") or "")[:120]
    team = str(payload.get("team") or "")[:160]
    allowed_sections = {"tickets", "sla", "workload", "devices", "monitoring", "network_vpn", "deployment", "automation", "activity", "remote_access", "software", "platform_activity", "system_metrics"}
    supplied_sections = payload.get("sections")
    sections = [str(x) for x in supplied_sections if str(x) in allowed_sections] if isinstance(supplied_sections, list) else sorted(allowed_sections)
    if not sections:
        raise HTTPException(status_code=422, detail="Select at least one report section.")

    with _connect() as connection:
        report_scope = _resolve_report_scope(connection, payload.get("report_scope"))
        if report_scope["type"] == "department":
            if department_id and department_id != report_scope["id"]:
                raise HTTPException(status_code=422, detail="The PDF report target Department must match the Department filter above.")
            department_id = report_scope["id"]
        summary = _build_summary(connection, sql_start, sql_end, start_epoch, end_epoch, department_id, team, report_scope)

        summary["period"]["start"] = iso_start
        summary["period"]["end"] = iso_end
        summary["filters"]["team"] = team or "All support teams"
        report_id = uuid.uuid4().hex
        filename = "Cartman-Report-{}-{}.pdf".format(datetime.now().strftime("%Y%m%d-%H%M%S"), report_id[:8])
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        target = REPORT_DIR / filename
        _make_pdf(target, summary, sections, str(user.get("display_name") or user.get("username") or "Cartman administrator"))
        _report_schema(connection)
        connection.execute("""
            INSERT INTO cartman_generated_reports
                (id, filename, stored_path, created_by_username, period_start, period_end, filters_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (report_id, filename, str(target.resolve()), str(user.get("username") or ""), sql_start, sql_end,
              json.dumps({"department_id": department_id, "team": team, "sections": sections, "report_scope": {"type": report_scope["type"], "id": report_scope["id"], "name": report_scope["name"], "member_count": report_scope.get("member_count")}}, ensure_ascii=False)))

    return {"id": report_id, "filename": filename, "status": "completed", "report_scope": {"type": report_scope["type"], "id": report_scope["id"], "name": report_scope["name"], "member_count": report_scope.get("member_count")}, "view_url": "/api/reports/pdf/" + report_id, "download_url": "/api/reports/pdf/" + report_id + "/download"}




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


@router.get("/pdf/{report_id}")
def view_report_pdf(report_id: str, request: Request):
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
    return FileResponse(str(stored), media_type="application/pdf", filename=row["filename"], content_disposition_type="inline")
