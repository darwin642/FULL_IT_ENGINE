from pathlib import Path
from datetime import datetime
import shutil
import sys

ROOT = Path.cwd()

MAIN = ROOT / "app/main.py"
CLIENT = ROOT / "client/cartman_client.py"
DEVICES = ROOT / "app/static/js/modules/devices.js"
EVENTS = ROOT / "app/static/js/core/events.js"

paths = (MAIN, CLIENT, DEVICES, EVENTS)

for path in paths:
    if not path.is_file():
        sys.exit(f"ABORTED: File not found: {path}")

data = {path: path.read_text(encoding="utf-8") for path in paths}


def replace_once(path, old, new, label):
    text = data[path]
    count = text.count(old)

    if count != 1:
        raise RuntimeError(
            f"{label}: expected 1 matching block, found {count}. "
            "No source files have been changed."
        )

    data[path] = text.replace(old, new, 1)


try:
    # 1. Allow self_test in the SQLite table definition.
    replace_once(
        MAIN,
        "                    'vpn_action'\n"
        "                )",
        "                    'vpn_action',\n"
        "                    'self_test'\n"
        "                )",
        "device_tasks schema",
    )

    # 2. Add an idempotent migration for databases that already exist.
    migration_anchor = "def normalize_os_family(value):"

    if data[MAIN].count(migration_anchor) != 1:
        raise RuntimeError("Could not locate the database migration insertion point.")

    migration = r'''
# Migrate the existing task queue to allow the safe agent self-test.
# Existing task records and results are copied without modification.
with get_connection() as connection:
    task_table = connection.execute(
        "SELECT sql FROM sqlite_master "
        "WHERE type='table' AND name='device_tasks'"
    ).fetchone()

    task_schema_sql = (task_table["sql"] or "") if task_table else ""

    if "'self_test'" not in task_schema_sql:
        connection.execute("""
            CREATE TABLE device_tasks_new (
                id TEXT PRIMARY KEY,
                device_id TEXT NOT NULL,
                action TEXT NOT NULL CHECK (
                    action IN (
                        'package_deployment',
                        'shutdown',
                        'network_disconnect',
                        'vpn_action',
                        'self_test'
                    )
                ),
                payload TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'Queued' CHECK (
                    status IN (
                        'Queued', 'Dispatched', 'Running',
                        'Succeeded', 'Failed', 'Cancelled'
                    )
                ),
                result TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                started_at TEXT,
                finished_at TEXT
            )
        """)

        connection.execute("""
            INSERT INTO device_tasks_new (
                id, device_id, action, payload, status, result,
                created_at, started_at, finished_at
            )
            SELECT
                id, device_id, action, payload, status, result,
                created_at, started_at, finished_at
            FROM device_tasks
        """)

        connection.execute("DROP TABLE device_tasks")
        connection.execute(
            "ALTER TABLE device_tasks_new RENAME TO device_tasks"
        )

        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_device_tasks_status_created
            ON device_tasks(status, created_at)
        """)


'''

    data[MAIN] = data[MAIN].replace(
        migration_anchor,
        migration + migration_anchor,
        1,
    )

    # 3. Allow the API to accept the new task type.
    replace_once(
        MAIN,
        '            "vpn_action",\n'
        "        }\n"
        "        if value not in allowed:",
        '            "vpn_action",\n'
        '            "self_test",\n'
        "        }\n"
        "        if value not in allowed:",
        "task action validation",
    )

    # 4. Implement a harmless client-side self-test.
    replace_once(
        CLIENT,
        "    try:\n"
        '        if action == "package_deployment":',
        "    try:\n"
        '        if action == "self_test":\n'
        '            return "Succeeded", (\n'
        '                "Agent self-test passed. The task reached CartmanClient "\n'
        '                "and the task-result channel is responsive. "\n'
        '                "OS: {}. Python: {}."\n'
        '            ).format(platform.system(), platform.python_version())\n'
        "\n"
        '        if action == "package_deployment":',
        "client task executor",
    )

    # 5. Register the UI label and backend action name.
    replace_once(
        DEVICES,
        '        vpn: "VPN action"\n'
        "    };",
        '        vpn: "VPN action",\n'
        '        "self-test": "Agent self-test"\n'
        "    };",
        "action modal labels",
    )

    replace_once(
        DEVICES,
        '        vpn: "vpn_action"\n'
        "    };",
        '        vpn: "vpn_action",\n'
        '        "self-test": "self_test"\n'
        "    };",
        "action API names",
    )

    # 6. Add a no-side-effect form to the existing task modal.
    replace_once(
        DEVICES,
        '            vpn: `\n',
        '            "self-test": `\n'
        '                <p>This safe test verifies that Cartman can deliver a task to the agent and receive its result. '
        'It does not run shell commands or change device settings.</p>\n'
        '            `,\n'
        '            vpn: `\n',
        "self-test task form",
    )

    # 7. Add the option to the per-device Actions menu.
    replace_once(
        DEVICES,
        '                    <button type="button" data-device-menu-action="monitor" '
        'data-device-id="${escapeDeviceHTML(device.id)}">Monitor</button>\n',
        '                    <button type="button" data-device-menu-action="monitor" '
        'data-device-id="${escapeDeviceHTML(device.id)}">Monitor</button>\n'
        '                    <button type="button" data-device-menu-action="self-test" '
        'data-device-id="${escapeDeviceHTML(device.id)}">Agent self-test</button>\n',
        "device Actions menu",
    )

    # 8. Permit the global menu router to open the new action modal.
    allowed_actions = (
        '["package", "shutdown", "network", "connect", "monitor", "vpn"]'
    )
    occurrences = data[EVENTS].count(allowed_actions)

    if occurrences < 2:
        raise RuntimeError(
            "Global Actions routing: expected at least two action lists, "
            f"found {occurrences}. No source files have been changed."
        )

    data[EVENTS] = data[EVENTS].replace(
        allowed_actions,
        '["package", "shutdown", "network", "connect", "monitor", '
        '"vpn", "self-test"]',
    )

except RuntimeError as exc:
    sys.exit(f"PATCH ABORTED: {exc}")

# All patch points were validated before the first write.
stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
backups = []

try:
    for path in paths:
        backup = path.with_name(
            path.name + f".before-self-test-{stamp}.bak"
        )
        shutil.copy2(path, backup)
        backups.append((path, backup))

    for path in paths:
        path.write_text(data[path], encoding="utf-8")
        print(f"UPDATED: {path.relative_to(ROOT)}")

    for path, backup in backups:
        print(f"BACKUP:  {backup.relative_to(ROOT)}")

except Exception as exc:
    print(f"WRITE ERROR: {exc}")
    print("Attempting to restore the original files.")

    for path, backup in backups:
        try:
            shutil.copy2(backup, path)
            print(f"RESTORED: {path.relative_to(ROOT)}")
        except Exception as restore_exc:
            print(f"RESTORE ERROR: {path}: {restore_exc}")

    sys.exit(1)

print("PATCH APPLIED: Agent Self-Test added.")
