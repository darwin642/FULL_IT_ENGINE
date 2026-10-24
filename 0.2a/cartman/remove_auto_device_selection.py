from pathlib import Path
from datetime import datetime
import re
import shutil
import sys

root = Path("app/static")
pattern = re.compile(
    r'(?m)^[ \t]*if \(selectedDevices\.length === 0 && allDevices\.length === 1\) \{\r?\n'
    r'[ \t]*selectedDevices = \[allDevices\[0\]\];\r?\n'
    r'[ \t]*deviceViewState\.selected = \[String\(allDevices\[0\]\.id\)\];\r?\n'
    r'[ \t]*\}\r?\n?'
)

plans = []

for path in root.rglob("*.js"):
    source = path.read_text(encoding="utf-8")
    updated, count = pattern.subn("", source)

    if count:
        plans.append((path, source, updated, count))

if not plans:
    print("ABORTED: Otomatik seçim bloğu bulunamadı.")
    print("Hiçbir dosya değiştirilmedi.")
    for path in root.rglob("*.js"):
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if "selectedDevices.length === 0 && allDevices.length === 1" in line:
                print("{}:{}: {}".format(path, number, line.strip()))
    sys.exit(1)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
backups = []

try:
    for path, source, updated, count in plans:
        backup = path.with_name(
            path.name + ".before-remove-auto-select-" + stamp + ".bak"
        )
        shutil.copy2(path, backup)
        backups.append((path, backup))

    for path, source, updated, count in plans:
        path.write_text(updated, encoding="utf-8")
        print("UPDATED:", path, "| removed blocks:", count)

    for path, backup in backups:
        print("BACKUP:", backup)

except Exception as exc:
    print("ERROR:", exc)
    print("Attempting to restore backups.")
    for path, backup in backups:
        try:
            shutil.copy2(backup, path)
            print("RESTORED:", path)
        except Exception as restore_error:
            print("RESTORE ERROR:", path, restore_error)
    sys.exit(1)

print("DONE: Actions must now require explicit device selection.")
