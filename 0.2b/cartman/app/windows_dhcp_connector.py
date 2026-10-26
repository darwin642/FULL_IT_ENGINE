"""Read-only Windows DHCP connector using an approved CartmanClient."""

import ipaddress
import json
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter()
get_connection = None
get_live_device_connections = None


class DHCPReadRequest(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=120)


def _local_only(request: Request):
    peer = request.client.host if request.client else ""
    try:
        if not ipaddress.ip_address(peer.split("%", 1)[0]).is_loopback:
            raise HTTPException(
                status_code=403,
                detail="DHCP connector is restricted to the local Cartman machine.",
            )
    except ValueError as exc:
        raise HTTPException(
            status_code=403,
            detail="Could not verify local Cartman operator.",
        ) from exc


# Fixed read-only command. No user-supplied PowerShell is accepted here.
# It returns up to eight scopes to keep the agent's task result bounded.
_DHCP_READ_ONLY_PS = r"""$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue';$server=$env:COMPUTERNAME;try{if(-not(Get-Module -ListAvailable -Name DhcpServer)){throw 'DhcpServer PowerShell module is not installed on this Windows host.'};Import-Module DhcpServer -ErrorAction Stop;$svc=Get-Service -Name DHCPServer -ErrorAction SilentlyContinue;$serviceState=if($svc){$svc.Status.ToString()}else{'NotInstalledOrUnavailable'};$all=@(Get-DhcpServerv4Scope -ComputerName $server -ErrorAction Stop);$shown=@($all|Select-Object -First 8|ForEach-Object{$s=$_;$o=@();try{$o=@(Get-DhcpServerv4OptionValue -ComputerName $server -ScopeId $s.ScopeId -ErrorAction Stop)}catch{};$gw=@($o|Where-Object{$_.OptionId -eq 3}|ForEach-Object{$_.Value}|ForEach-Object{[string]$_});$dns=@($o|Where-Object{$_.OptionId -eq 6}|ForEach-Object{$_.Value}|ForEach-Object{[string]$_});$dom=@($o|Where-Object{$_.OptionId -eq 15}|ForEach-Object{$_.Value}|ForEach-Object{[string]$_});[pscustomobject]@{scope_id=$s.ScopeId.ToString();name=[string]$s.Name;subnet_mask=$s.SubnetMask.ToString();start_ip=$s.StartRange.ToString();end_ip=$s.EndRange.ToString();state=$s.State.ToString();lease_duration=$s.LeaseDuration.ToString();gateway=$gw;dns_servers=$dns;domain_name=$dom}});$stats=$null;try{$st=Get-DhcpServerv4Statistics -ComputerName $server -ErrorAction Stop;$stats=[pscustomobject]@{total_scopes=$st.TotalScopes;total_addresses=$st.TotalAddresses;addresses_in_use=$st.AddressesInUse;addresses_available=$st.AddressesAvailable}}catch{$stats=[pscustomobject]@{unavailable=$true;message=$_.Exception.Message}};$fqdn=$server;if($env:USERDNSDOMAIN){$fqdn="$server.$env:USERDNSDOMAIN"};[pscustomobject]@{status='Succeeded';read_only=$true;connector='windows-dhcp-powershell';server=$server;server_fqdn=$fqdn;checked_at=(Get-Date).ToUniversalTime().ToString('o');service_state=$serviceState;scope_count=$all.Count;scopes_truncated=($all.Count -gt 8);scopes=$shown;statistics=$stats}|ConvertTo-Json -Depth 6 -Compress}catch{$err=$_.Exception.Message;[pscustomobject]@{status='Failed';read_only=$true;connector='windows-dhcp-powershell';server=$server;checked_at=(Get-Date).ToUniversalTime().ToString('o');error=$err}|ConvertTo-Json -Depth 4 -Compress;exit 1}"""


@router.get("/api/network/dhcp/connector/targets")
def list_targets(request: Request):
    _local_only(request)
    live_by_device = (
        get_live_device_connections()
        if callable(get_live_device_connections) else {}
    )

    with get_connection() as db:
        rows = db.execute("""
            SELECT id, name, os, ip FROM devices
            WHERE LOWER(os) LIKE '%windows%' OR LOWER(os) LIKE 'win%'
            ORDER BY name COLLATE NOCASE
        """).fetchall()
        registered = {
            str(r["device_id"])
            for r in db.execute("""
                SELECT DISTINCT device_id
                FROM device_agent_credentials WHERE revoked=0
            """).fetchall()
        }

    result = []
    for row in rows:
        device_id = str(row["id"])
        live = live_by_device.get(device_id)
        connected = bool(live and live.get("connected") is True)
        enabled = bool(
            connected and live.get("task_execution_enabled") is True
        )
        result.append({
            "id": device_id,
            "name": row["name"],
            "os": row["os"],
            "ip": row["ip"],
            "status": "Online" if connected else "Offline",
            "agent_registered": device_id in registered,
            "task_execution_enabled": enabled,
            "ready": bool(enabled and device_id in registered),
            "read_only": True,
        })
    return result


@router.post("/api/network/dhcp/connector/read", status_code=202)
def start_read(payload: DHCPReadRequest, request: Request):
    _local_only(request)

    if not callable(get_live_device_connections):
        raise HTTPException(
            status_code=503,
            detail="CartmanClient live-session provider is not configured.",
        )

    device_id = payload.device_id.strip()
    with get_connection() as db:
        device = db.execute(
            "SELECT id,name,os FROM devices WHERE id=?",
            (device_id,),
        ).fetchone()
        if not device:
            raise HTTPException(status_code=404, detail="Device not found.")

        os_name = str(device["os"] or "").lower()
        if "windows" not in os_name and not os_name.startswith("win"):
            raise HTTPException(
                status_code=422, detail="Select a Windows device."
            )

        registered = db.execute("""
            SELECT 1 FROM device_agent_credentials
            WHERE device_id=? AND revoked=0 LIMIT 1
        """, (device_id,)).fetchone()

    if not registered:
        raise HTTPException(
            status_code=409,
            detail="This device has no registered CartmanClient identity.",
        )

    live = get_live_device_connections().get(device_id)
    if not live or live.get("connected") is not True:
        raise HTTPException(
            status_code=409,
            detail="CartmanClient is offline. Start the approved client on the Windows DHCP server, then retry.",
        )
    if live.get("task_execution_enabled") is not True:
        raise HTTPException(
            status_code=409,
            detail="CartmanClient is connected but task execution is disabled. Start it with task execution enabled.",
        )

    task_id = "task-" + uuid.uuid4().hex
    task_payload = {
        "command": _DHCP_READ_ONLY_PS,
        "confirmed": True,
        "target_os": "Windows",
        "connector_action": "windows_dhcp_readonly_v1",
    }

    with get_connection() as db:
        db.execute("""
            INSERT INTO device_tasks
                (id,device_id,action,payload,scheduled_at)
            VALUES (?,?,'remote_command',?,NULL)
        """, (task_id, device_id, json.dumps(task_payload)))

    return {
        "task_id": task_id,
        "device_id": device_id,
        "device_name": device["name"],
        "status": "Queued",
        "read_only": True,
        "message": "Fixed read-only DHCP inspection queued.",
    }


@router.get("/api/network/dhcp/connector/tasks/{task_id}")
def read_result(task_id: str, request: Request):
    _local_only(request)
    with get_connection() as db:
        row = db.execute("""
            SELECT t.id,t.device_id,d.name AS device_name,t.action,
                   t.payload,t.status,t.result,t.created_at,
                   t.started_at,t.finished_at
            FROM device_tasks t
            JOIN devices d ON d.id=t.device_id
            WHERE t.id=?
        """, (task_id,)).fetchone()

    if not row:
        raise HTTPException(
            status_code=404, detail="DHCP read task not found."
        )

    try:
        task_payload = json.loads(row["payload"] or "{}")
    except (TypeError, json.JSONDecodeError):
        task_payload = {}

    if (
        row["action"] != "remote_command"
        or task_payload.get("connector_action") != "windows_dhcp_readonly_v1"
    ):
        raise HTTPException(
            status_code=404, detail="DHCP read task not found."
        )

    raw = row["result"] or ""
    try:
        parsed = json.loads(raw) if raw else None
    except (TypeError, json.JSONDecodeError):
        parsed = None

    return {
        "task_id": row["id"],
        "device_id": row["device_id"],
        "device_name": row["device_name"],
        "status": row["status"],
        "result": parsed,
        "result_text": raw if parsed is None else "",
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "read_only": True,
    }
