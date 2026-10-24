#!/usr/bin/env python3
"""Safely patch Cartman's live device status and Actions routing."""
from pathlib import Path
from datetime import datetime
import re
import shutil
import sys

ROOT = Path.cwd()
MAIN = ROOT / "app/main.py"
DEVICES = ROOT / "app/static/js/modules/devices.js"
EVENTS = ROOT / "app/static/js/core/events.js"

for path in (MAIN, DEVICES, EVENTS):
    if not path.is_file():
        sys.exit(
            f"ERROR: {path} not found. "
            "Run this script from ~/Documents/cartman."
        )

originals = {p: p.read_text(encoding="utf-8")
             for p in (MAIN, DEVICES, EVENTS)}
updated = dict(originals)


def replace_regex_once(text, pattern, replacement, label):
    result, count = re.subn(
        pattern, replacement, text, count=1,
        flags=re.MULTILINE | re.DOTALL
    )
    if count != 1:
        raise RuntimeError(
            f"Expected exactly one match for {label}; found {count}. "
            "No files were changed."
        )
    return result


def replace_text_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"Expected exactly one match for {label}; found {count}. "
            "No files were changed."
        )
    return text.replace(old, new, 1)


try:
    # Backend: find connected sessions belonging to approved devices.
    live_helper = '''def _get_live_device_connections():
    """Return the newest connected, approved CartmanClient session per device."""
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, device_id
            FROM device_connection_requests
            WHERE status = 'Approved' AND device_id IS NOT NULL
            """
        ).fetchall()

    approved_device_by_request = {
        str(row["id"]): str(row["device_id"])
        for row in rows
        if row["id"] and row["device_id"]
    }

    with _connection_clients_lock:
        clients = [
            dict(client)
            for client in _connection_clients.values()
            if client.get("connected") is True
        ]

    live_by_device = {}
    for client in clients:
        device_id = approved_device_by_request.get(
            str(client.get("request_id") or "")
        )
        if not device_id:
            continue

        previous = live_by_device.get(device_id)
        if (
            previous is None
            or str(client.get("last_seen") or "")
            > str(previous.get("last_seen") or "")
        ):
            live_by_device[device_id] = client

    return live_by_device


def _apply_live_device_state(device, live_connections):
    """Expose connection liveness without persisting transient status to SQLite."""
    client = live_connections.get(str(device.get("id") or ""))
    live = client is not None

    device["status"] = "Online" if live else "Offline"
    device["connection_status"] = "Online" if live else "Offline"
    device["connection_state"] = (
        (client.get("state") or "Connected")
        if live else "Disconnected"
    )
    device["last_seen"] = (
        (client.get("last_seen") or None) if live else None
    )
    device["lastSeen"] = device["last_seen"]

    return device


'''
    updated[MAIN] = replace_text_once(
        updated[MAIN],
        '@app.get("/api/devices")\ndef list_devices():',
        live_helper + '@app.get("/api/devices")\ndef list_devices():',
        "insert live connection helpers",
    )

    updated[MAIN] = replace_regex_once(
        updated[MAIN],
        r'^@app\.get\("/api/devices"\)\ndef list_devices\(\):.*?(?=^@app\.get\("/api/devices/\{device_id\}"\))',
        '''@app.get("/api/devices")
def list_devices():
    with get_connection() as connection:
        rows = connection.execute("""
            SELECT *
            FROM devices
            ORDER BY name COLLATE NOCASE
        """).fetchall()

    live_connections = _get_live_device_connections()
    return [
        _apply_live_device_state(serialize_device(row), live_connections)
        for row in rows
    ]


''',
        "devices list API",
    )

    updated[MAIN] = replace_regex_once(
        updated[MAIN],
        r'^@app\.get\("/api/devices/\{device_id\}"\)\ndef get_device\(device_id: str\):.*?(?=^@app\.post\("/api/devices", status_code=201\))',
        '''@app.get("/api/devices/{device_id}")
def get_device(device_id: str):
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM devices WHERE id = ?",
            (device_id,),
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Device not found")

    return _apply_live_device_state(
        serialize_device(row), _get_live_device_connections()
    )


''',
        "single device API",
    )

    old_connected_check = '''    with _connection_clients_lock:
        connected = any(
            client.get("request_id") in approved_ids
            and client.get("connected")
            for client in _connection_clients.values()
        )

    if not connected:
        raise HTTPException(
            status_code=409,
            detail="This device must be approved and connected before queuing a task.",
        )'''

    new_connected_check = '''    with _connection_clients_lock:
        connected = any(
            client.get("request_id") in approved_ids
            and client.get("connected")
            and client.get("task_execution_enabled") is True
            for client in _connection_clients.values()
        )

    if not connected:
        raise HTTPException(
            status_code=409,
            detail=(
                "This device must have an approved, connected CartmanClient "
                "with task execution enabled before queuing a task."
            ),
        )'''

    updated[MAIN] = replace_text_once(
        updated[MAIN],
        old_connected_check,
        new_connected_check,
        "require enabled connected CartmanClient for tasks",
    )

    # Frontend: keep the last heartbeat returned by the API.
    updated[DEVICES] = replace_regex_once(
        updated[DEVICES],
        r'(?m)^([ \t]*addedAt: device\.created_at \|\| null,\r?\n)([ \t]*)lastSeen: null[ \t]*$',
        r'\1\2lastSeen: device.last_seen || device.lastSeen || null',
        "preserve API last_seen",
    )

    # Refresh live status periodically when the Devices page is visible.
    polling = '''if (typeof window !== "undefined" && !window.__cartmanDeviceStatusPoller) {
    window.__cartmanDeviceStatusPoller = window.setInterval(async () => {
        const path = window.location.pathname.replace(/\\\\/+$/, "");
        const onDevicesPage =
            path === "/pages/devices" || window.location.hash === "#devices";

        if (
            !onDevicesPage ||
            document.visibilityState === "hidden" ||
            !deviceRecordsLoaded ||
            deviceRecordsLoading
        ) {
            return;
        }

        if (document.querySelector(
            "#device-action-modal-backdrop, #devices-modal-backdrop"
        )) {
            return;
        }

        try {
            await loadDeviceDataFromAPI(true);
            if (typeof renderDevicesModule === "function") {
                renderDevicesModule();
            }
        } catch (error) {
            console.warn(
                "Could not refresh live Cartman device status:", error
            );
        }
    }, 15000);
}

'''
    updated[DEVICES] = replace_text_once(
        updated[DEVICES],
        'function loadDeviceData() {',
        polling + 'function loadDeviceData() {',
        "insert live status polling",
    )

    # Replace the obsolete toolbar demo-only notice with actual action routing.
    old_demo = '''    if (["package", "shutdown", "network"].includes(action)) {
        if (!deviceViewState.selected.length) {
            notify("Select at least one device first.");
            return;
        }
        const labels = {
            package: "Package deployment",
            shutdown: "Shutdown",
            network: "Kick from network"
        };
        notify(`${labels[action]} is demo-only. No endpoint was contacted.`);
    }'''

    new_actions = '''    if (["package", "shutdown", "network", "connect", "monitor", "vpn"].includes(action)) {
        const allDevices = getDeviceData();
        const selectedIds = new Set(
            (deviceViewState.selected || []).map(String)
        );
        let selectedDevices = allDevices.filter(
            device => selectedIds.has(String(device.id))
        );

        if (selectedDevices.length === 0 && allDevices.length === 1) {
            selectedDevices = [allDevices[0]];
            deviceViewState.selected = [String(allDevices[0].id)];
        }

        if (selectedDevices.length !== 1) {
            notify(selectedDevices.length === 0
                ? "Select one device first, then choose this action."
                : "Select only one device at a time for this action.");
            return;
        }

        void openDeviceActionModal(selectedDevices[0], action);
    }'''

    updated[EVENTS] = replace_text_once(
        updated[EVENTS],
        old_demo,
        new_actions,
        "replace demo-only toolbar action fallback",
    )

except RuntimeError as exc:
    sys.exit(f"PATCH ABORTED: {exc}")

# Write only after every expected source block has matched.
stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

for path in (MAIN, DEVICES, EVENTS):
    backup = path.with_name(
        path.name + f".before-live-actions-{stamp}.bak"
    )
    shutil.copy2(path, backup)
    path.write_text(updated[path], encoding="utf-8")

    print(f"UPDATED: {path.relative_to(ROOT)}")
    print(f"BACKUP:  {backup.relative_to(ROOT)}")

print("Patch applied. Run the verification commands next.")
