#!/usr/bin/env python3
"""
CartmanClient local-network prototype.

Remote task execution is opt-in. Keep the listener LAN-only until TLS and
client authentication are implemented. Package install commands are parsed
without a shell and limited to known package-manager executables.
"""
import argparse
import base64
import ctypes
import getpass
import json
import os
import platform
import re
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from windows_dns_dhcp_actions import execute as execute_windows_dns_dhcp_action


PACKAGE_MANAGERS = {
    "installer", "brew", "softwareupdate", "winget", "msiexec",
    "choco", "scoop", "apt", "apt-get", "dpkg", "dnf", "yum",
    "rpm", "zypper", "flatpak", "snap", "pacman",
}


def send_json(sock, value):
    sock.sendall((json.dumps(value) + "\n").encode("utf-8"))


def read_json(stream):
    raw = stream.readline(65537)
    if not raw or len(raw) > 65536:
        raise ConnectionError("Cartman closed the connection or sent an invalid response.")
    return json.loads(raw.decode("utf-8"))


def run_command(argv, timeout=120):
    completed = subprocess.run(
        argv,
        shell=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    output = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
    return completed.returncode == 0, output[-4500:]


def execute_task(task):
    action = task.get("action")
    payload = task.get("payload") or {}
    execution = task.get("execution") or {}
    system = platform.system()

    try:
        if action == "self_test":
            return "Succeeded", (
                "Agent self-test passed. The task reached CartmanClient "
                "and the task-result channel is responsive. "
                "OS: {}. Python: {}."
            ).format(platform.system(), platform.python_version())


        if action == "remote_command" and payload.get("connector_action") == "windows_dns_dhcp_management_v1":
            return execute_windows_dns_dhcp_action(payload)

        if action == "remote_command":
            command = payload.get("command")
            target_os = payload.get("target_os", "Any")

            if not isinstance(command, str) or not command.strip() or len(command) > 6000:
                return "Failed", "Missing or invalid remote command."

            expected_platform = {
                "Windows": "Windows",
                "macOS": "Darwin",
                "Linux": "Linux",
            }.get(target_os)

            if expected_platform and system != expected_platform:
                return "Failed", (
                    f"This command targets {target_os}, but this client runs "
                    f"{system}. Command was not executed."
                )

            if system == "Windows":
                powershell = shutil.which("powershell") or shutil.which("pwsh")
                if not powershell:
                    return "Failed", "PowerShell was not found on this endpoint."
                argv = [
                    powershell, "-NoProfile", "-NonInteractive",
                    "-ExecutionPolicy", "Bypass", "-Command", command,
                ]
            elif system in {"Darwin", "Linux"}:
                argv = ["/bin/sh", "-lc", command]
            else:
                return "Failed", "Remote commands are unsupported on this operating system."

            ok, output = run_command(argv, timeout=180)
            return (
                "Succeeded" if ok else "Failed",
                output or ("Command completed." if ok else "Command returned a non-zero exit code."),
            )

        if action == "package_deployment":
            command = execution.get("install_command", "")
            argv = shlex.split(command)
            if not argv:
                return "Failed", "Software package has no install command."
            if argv[0].rsplit("/", 1)[-1].lower() not in PACKAGE_MANAGERS:
                return "Failed", (
                    "Install command rejected: use a supported package manager "
                    "such as installer, winget, msiexec, apt, dnf, brew, or pacman."
                )
            ok, output = run_command(argv, timeout=1800)
            return ("Succeeded" if ok else "Failed", output or (
                "Package install command completed." if ok else "Package installer returned a non-zero exit code."
            ))

        if action == "shutdown":
            delay_seconds = payload.get("delay_seconds", 60)
            if (
                type(delay_seconds) is not int
                or not 1 <= delay_seconds <= 86400
            ):
                return "Failed", (
                    "Shutdown countdown must be a whole number from "
                    "1 to 86400 seconds."
                )

            if system == "Windows":
                argv = ["shutdown", "/s", "/t", str(delay_seconds)]
                print(f"DEBUG shutdown: system={system}, delay={delay_seconds}, argv={argv}", flush=True)
                ok, output = run_command(argv, timeout=15)
                if ok:
                    return "Succeeded", (
                        f"Windows accepted the shutdown request. "
                        f"Shutdown is scheduled in {delay_seconds} seconds."
                    )
                return "Failed", output or "Windows could not schedule shutdown."

            if system == "Darwin":
                # Request authorization now and schedule the fixed shutdown
                # command after the validated delay.
                osascript = shutil.which("osascript") or "/usr/bin/osascript"
                script = (
                    'do shell script "nohup /bin/sh -c \'sleep '
                    + str(delay_seconds)
                    + '; /sbin/shutdown -h now\' >/dev/null 2>&1 &" '
                    'with administrator privileges'
                )
                ok, output = run_command([osascript, "-e", script], timeout=120)
                if ok:
                    return "Succeeded", (
                        f"macOS accepted the shutdown schedule after "
                        f"administrator authorization. Countdown: {delay_seconds} seconds."
                    )
                if "User canceled" in output or "(-128)" in output:
                    return "Failed", (
                        "Shutdown cancelled in the macOS administrator authorization dialog."
                    )
                return "Failed", output or (
                    "macOS could not schedule shutdown. Administrator authorization may be required."
                )

            if system == "Linux":
                systemd_run = shutil.which("systemd-run")
                shutdown = shutil.which("shutdown") or "/sbin/shutdown"
                if not systemd_run:
                    return "Failed", (
                        "Exact-second shutdown scheduling requires systemd-run "
                        "on this Linux client. No shutdown was scheduled."
                    )
                unit = "cartman-shutdown-" + uuid.uuid4().hex[:12]
                argv = [
                    systemd_run,
                    "--quiet",
                    "--on-active=" + str(delay_seconds) + "s",
                    "--unit=" + unit,
                    shutdown,
                    "-h",
                    "now",
                ]
                ok, output = run_command(argv, timeout=30)
                if ok:
                    return "Succeeded", (
                        f"Linux accepted the shutdown schedule. "
                        f"Countdown: {delay_seconds} seconds."
                    )
                return "Failed", output or (
                    "Linux could not schedule shutdown. Check systemd and permissions."
                )

            return "Failed", "Shutdown is unsupported on this operating system."

        if action == "network_disconnect":
            name = payload.get("interface_name", "").strip()
            if not name or len(name) > 150:
                return "Failed", "Missing network interface/service name."

            # Disabling the active management interface will sever this agent's
            # connection. Schedule it after reporting the task result.
            if system == "Darwin":
                argv = ["/usr/sbin/networksetup", "-setnetworkserviceenabled", name, "off"]
            elif system == "Windows":
                argv = ["netsh", "interface", "set", "interface", "name=" + name, "admin=disabled"]
            elif system == "Linux":
                argv = ["nmcli", "connection", "down", "id", name]
            else:
                return "Failed", "Network disconnect is unsupported on this operating system."

            def delayed_disconnect():
                time.sleep(15)
                try:
                    run_command(argv, timeout=45)
                except Exception:
                    pass

            threading.Thread(target=delayed_disconnect, daemon=True).start()
            return "Succeeded", (
                "Network disconnect scheduled for 15 seconds from now. "
                "The management connection may drop; local access may be needed to restore it."
            )

        if action == "vpn_action":
            mode = payload.get("mode")
            profile = payload.get("profile_name", "").strip()
            if mode not in {"connect", "disconnect"} or not profile or len(profile) > 150:
                return "Failed", "Invalid VPN action or profile name."

            if system == "Darwin":
                argv = ["/usr/sbin/scutil", "--nc", "start" if mode == "connect" else "stop", profile]
            elif system == "Windows":
                argv = ["rasdial", profile] if mode == "connect" else ["rasdial", "/disconnect"]
            elif system == "Linux":
                argv = ["nmcli", "connection", "up" if mode == "connect" else "down", "id", profile]
            else:
                return "Failed", "VPN actions are unsupported on this operating system."

            ok, output = run_command(argv, timeout=90)
            return ("Succeeded" if ok else "Failed", output or (
                "VPN command completed." if ok else "VPN command returned a non-zero exit code."
            ))

        return "Failed", "Unsupported task action."

    except subprocess.TimeoutExpired:
        return "Failed", "Task timed out."
    except FileNotFoundError:
        return "Failed", "Required operating system command was not found."
    except PermissionError:
        return "Failed", "Permission denied. Run the agent with the required operating-system privileges."
    except Exception as exc:
        return "Failed", "{}: {}".format(type(exc).__name__, str(exc))



def _read_command(argv, timeout=8):
    try:
        completed = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, check=False
        )
        if completed.returncode == 0:
            return (completed.stdout or "").strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return ""


def _gb_from_bytes(value):
    try:
        amount = int(value)
        return f"{max(1, round(amount / (1024 ** 3)))} GB" if amount > 0 else ""
    except (TypeError, ValueError):
        return ""


def get_os_display():
    system = platform.system()
    if system == "Darwin":
        version = platform.mac_ver()[0] or platform.release()
        return f"macOS {version}".strip()
    if system == "Windows":
        version = platform.release()
        return f"Windows {version}".strip()
    if system == "Linux":
        try:
            info = platform.freedesktop_os_release()
            return info.get("PRETTY_NAME") or platform.platform()
        except (AttributeError, OSError):
            return platform.platform()
    return platform.platform()


def get_hardware_info():
    info = {
        "manufacturer": "",
        "model": "",
        "device_type": "Workstation",
        "cpu": "",
        "ram": "",
        "disk": "",
        "gpu": "",
    }
    system = platform.system()
    cores = os.cpu_count() or 0

    try:
        if system == "Darwin":
            info["manufacturer"] = "Apple"
            raw = _read_command([
                "/usr/sbin/system_profiler", "-json",
                "SPHardwareDataType", "SPDisplaysDataType",
            ], timeout=12)
            if raw:
                try:
                    data = json.loads(raw)
                    hardware_items = data.get("SPHardwareDataType", [])
                    display_items = data.get("SPDisplaysDataType", [])
                    if hardware_items:
                        hw = hardware_items[0]
                        info["model"] = (
                            hw.get("machine_name") or hw.get("model_name")
                            or hw.get("model_identifier") or ""
                        )
                        chip = hw.get("chip") or hw.get("cpu_type") or ""
                        if chip:
                            info["cpu"] = str(chip)
                        memory = hw.get("physical_memory") or ""
                        if memory:
                            info["ram"] = str(memory)
                    gpu_names = []
                    for display in display_items:
                        name = (
                            display.get("sppci_model")
                            or display.get("spdisplays_device-id")
                            or display.get("_name")
                        )
                        if name and str(name) not in gpu_names:
                            gpu_names.append(str(name))
                    info["gpu"] = ", ".join(gpu_names)
                except (ValueError, TypeError, AttributeError):
                    pass

            if not info["cpu"]:
                info["cpu"] = _read_command(
                    ["/usr/sbin/sysctl", "-n", "machdep.cpu.brand_string"]
                )
            if not info["ram"]:
                info["ram"] = _gb_from_bytes(
                    _read_command(["/usr/sbin/sysctl", "-n", "hw.memsize"])
                )

        elif system == "Windows":
            powershell = shutil.which("powershell") or shutil.which("pwsh")
            if powershell:
                ps = (
                    "$c=Get-CimInstance Win32_ComputerSystem;"
                    "$p=Get-CimInstance Win32_Processor | Select-Object -First 1;"
                    "$g=Get-CimInstance Win32_VideoController | "
                    "Select-Object -ExpandProperty Name;"
                    "[pscustomobject]@{Manufacturer=$c.Manufacturer;Model=$c.Model;"
                    "RAM=$c.TotalPhysicalMemory;CPU=$p.Name;GPU=($g -join ', ')} "
                    "| ConvertTo-Json -Compress"
                )
                raw = _read_command(
                    [powershell, "-NoProfile", "-Command", ps], timeout=12
                )
                if raw:
                    try:
                        data = json.loads(raw)
                        info["manufacturer"] = str(data.get("Manufacturer") or "")
                        info["model"] = str(data.get("Model") or "")
                        info["ram"] = _gb_from_bytes(data.get("RAM"))
                        info["cpu"] = str(data.get("CPU") or "")
                        info["gpu"] = str(data.get("GPU") or "")
                    except (ValueError, TypeError):
                        pass

        elif system == "Linux":
            try:
                info["manufacturer"] = Path(
                    "/sys/class/dmi/id/sys_vendor"
                ).read_text(encoding="utf-8", errors="ignore").strip()
            except OSError:
                pass

            for filename in (
                "/sys/class/dmi/id/product_name",
                "/sys/firmware/devicetree/base/model",
            ):
                try:
                    value = Path(filename).read_text(
                        encoding="utf-8", errors="ignore"
                    ).replace("\x00", "").strip()
                    if value:
                        info["model"] = value
                        break
                except OSError:
                    pass

            try:
                cpuinfo = Path("/proc/cpuinfo").read_text(
                    encoding="utf-8", errors="ignore"
                )
                for line in cpuinfo.splitlines():
                    if line.lower().startswith(("model name", "hardware")):
                        info["cpu"] = line.split(":", 1)[-1].strip()
                        if info["cpu"]:
                            break
            except OSError:
                pass

            try:
                for line in Path("/proc/meminfo").read_text().splitlines():
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        info["ram"] = _gb_from_bytes(kb * 1024)
                        break
            except (OSError, ValueError, IndexError):
                pass

            lspci = shutil.which("lspci")
            if lspci:
                raw = _read_command([lspci], timeout=5)
                names = [
                    line.split(":", 2)[-1].strip()
                    for line in raw.splitlines()
                    if "vga compatible controller" in line.lower()
                    or "3d controller" in line.lower()
                    or "display controller" in line.lower()
                ]
                info["gpu"] = ", ".join(names)

    except Exception as exc:
        print("Hardware discovery warning:", type(exc).__name__, str(exc))

    if not info["cpu"]:
        processor = platform.processor().strip()
        if processor:
            info["cpu"] = processor
    if info["cpu"] and cores:
        if str(cores) not in info["cpu"]:
            info["cpu"] = f"{info['cpu']} ({cores} logical cores)"
    elif cores:
        info["cpu"] = f"{cores} logical cores"

    if not info["ram"] or not info["disk"]:
        try:
            usage = shutil.disk_usage(os.path.abspath(os.sep))
            if not info["disk"]:
                info["disk"] = _gb_from_bytes(usage.total)
        except OSError:
            pass

    return info



def _telemetry_cpu_percent():
    """Return a real system CPU-utilization sample, or None if unavailable."""
    try:
        if sys.platform == "darwin":
            result = subprocess.run(
                ["/usr/bin/top", "-l", "2", "-n", "0", "-s", "1"],
                capture_output=True, text=True, timeout=5, check=False,
            )
            output = (result.stdout or "") + "\n" + (result.stderr or "")
            matches = re.findall(
                r"CPU usage:\s*([\d.]+)% user,\s*([\d.]+)% sys,\s*([\d.]+)% idle",
                output, flags=re.IGNORECASE,
            )
            if matches:
                user, system, _idle = map(float, matches[-1])
                return round(max(0.0, min(100.0, user + system)), 2)

        elif sys.platform.startswith("linux"):
            def snapshot():
                with open("/proc/stat", "r", encoding="ascii") as handle:
                    fields = handle.readline().split()
                if not fields or fields[0] != "cpu":
                    return None
                values = [int(value) for value in fields[1:]]
                if len(values) < 4:
                    return None
                idle = values[3] + (values[4] if len(values) > 4 else 0)
                return sum(values), idle

            before = snapshot()
            time.sleep(0.2)
            after = snapshot()
            if before and after:
                total_delta = after[0] - before[0]
                idle_delta = after[1] - before[1]
                if total_delta > 0:
                    busy = total_delta - idle_delta
                    return round(max(0.0, min(100.0, busy * 100.0 / total_delta)), 2)

        elif os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class FILETIME(ctypes.Structure):
                _fields_ = [
                    ("dwLowDateTime", wintypes.DWORD),
                    ("dwHighDateTime", wintypes.DWORD),
                ]

            kernel32 = ctypes.windll.kernel32
            get_times = kernel32.GetSystemTimes
            get_times.argtypes = [
                ctypes.POINTER(FILETIME),
                ctypes.POINTER(FILETIME),
                ctypes.POINTER(FILETIME),
            ]
            get_times.restype = wintypes.BOOL

            def filetime_value(item):
                return (item.dwHighDateTime << 32) | item.dwLowDateTime

            def snapshot():
                idle, kernel, user = FILETIME(), FILETIME(), FILETIME()
                if not get_times(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
                    return None
                return (
                    filetime_value(idle),
                    filetime_value(kernel),
                    filetime_value(user),
                )

            before = snapshot()
            time.sleep(0.2)
            after = snapshot()
            if before and after:
                idle_delta = after[0] - before[0]
                total_delta = (after[1] - before[1]) + (after[2] - before[2])
                if total_delta > 0:
                    busy = total_delta - idle_delta
                    return round(max(0.0, min(100.0, busy * 100.0 / total_delta)), 2)

    except Exception:
        return None

    return None


def _telemetry_memory_percent():
    """Return an OS-reported memory-usage estimate, or None if unavailable."""
    try:
        if sys.platform == "darwin":
            result = subprocess.run(
                ["/usr/bin/memory_pressure"],
                capture_output=True, text=True, timeout=4, check=False,
            )
            output = (result.stdout or "") + "\n" + (result.stderr or "")
            match = re.search(
                r"System-wide memory free percentage:\s*(\d+)%",
                output, flags=re.IGNORECASE,
            )
            if match:
                free_percent = float(match.group(1))
                return round(max(0.0, min(100.0, 100.0 - free_percent)), 2)

        elif sys.platform.startswith("linux"):
            values = {}
            with open("/proc/meminfo", "r", encoding="ascii") as handle:
                for line in handle:
                    parts = line.split()
                    if len(parts) >= 2 and parts[0] in {"MemTotal:", "MemAvailable:"}:
                        values[parts[0]] = int(parts[1])
            total = values.get("MemTotal", 0)
            available = values.get("MemAvailable", 0)
            if total > 0:
                used = max(0, total - available)
                return round(max(0.0, min(100.0, used * 100.0 / total)), 2)

        elif os.name == "nt":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return float(status.dwMemoryLoad)

    except Exception:
        return None

    return None


def _collect_telemetry():
    """Collect genuine local utilization samples; never synthesize missing values."""
    readings = []

    cpu = _telemetry_cpu_percent()
    if cpu is not None:
        readings.append({"metric_name": "cpu_percent", "value": cpu, "unit": "%"})

    memory = _telemetry_memory_percent()
    if memory is not None:
        readings.append({"metric_name": "memory_percent", "value": memory, "unit": "%"})

    try:
        usage = shutil.disk_usage(os.path.abspath(os.sep))
        if usage.total > 0:
            disk = round(max(0.0, min(100.0, usage.used * 100.0 / usage.total)), 2)
            readings.append({"metric_name": "disk_percent", "value": disk, "unit": "%"})
    except (OSError, ValueError):
        pass

    return readings


def _client_identity_path():
    if os.name == "nt":
        base = Path(
            os.environ.get("LOCALAPPDATA")
            or (Path.home() / "AppData" / "Local")
        )
    elif platform.system() == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(
            os.environ.get("XDG_DATA_HOME")
            or (Path.home() / ".local" / "share")
        )
    return base / "Cartman" / "client_identity.json"


def load_or_create_identity():
    """Persist an Ed25519 identity; never silently replace a damaged identity."""
    path = _client_identity_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
            client_instance = str(uuid.UUID(stored["client_instance"]))
            private_bytes = base64.b64decode(
                stored["private_key"], validate=True
            )
            if len(private_bytes) != 32:
                raise ValueError("Invalid private key length.")
            private_key = Ed25519PrivateKey.from_private_bytes(private_bytes)
        except Exception as exc:
            raise RuntimeError(
                "Could not read the saved Cartman identity at {}. "
                "Do not delete it; restore or inspect the file first.".format(path)
            ) from exc
    else:
        client_instance = str(uuid.uuid4())
        private_key = Ed25519PrivateKey.generate()
        private_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        stored = {
            "client_instance": client_instance,
            "private_key": base64.b64encode(private_bytes).decode("ascii"),
        }
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(
            json.dumps(stored, indent=2), encoding="utf-8"
        )
        if os.name != "nt":
            os.chmod(temporary, 0o600)
        temporary.replace(path)
        if os.name != "nt":
            os.chmod(path, 0o600)

    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_text = base64.b64encode(public_bytes).decode("ascii")
    return client_instance, private_key, public_text


def main():
    parser = argparse.ArgumentParser(description="CartmanClient LAN agent prototype")
    parser.add_argument("--server", required=True, help="Cartman server LAN IP or hostname")
    parser.add_argument("--port", type=int, default=50101)
    parser.add_argument("--name", default=socket.gethostname())
    parser.add_argument(
        "--enable-task-execution",
        action="store_true",
        help="Allow approved Cartman tasks to execute on this endpoint.",
    )
    parser.add_argument(
        "--enable-windows-dns-dhcp-management",
        action="store_true",
        help="Enable allowlisted Windows DNS/DHCP operations only; does not enable general remote commands.",
    )
    parser.add_argument("--heartbeat-interval", type=int, default=20)
    args = parser.parse_args()

    client_instance, identity_private_key, public_key_text = load_or_create_identity()
    print("Persistent Cartman device ID:", client_instance)
    print("Identity file:", _client_identity_path())

    hardware = get_hardware_info()
    hello = {
        "type": "hello",
        "device_name": args.name,
        "os": get_os_display(),
        "username": getpass.getuser(),
        "client_instance": client_instance,
        "public_key": public_key_text,
        "task_execution_enabled": bool(args.enable_task_execution),
        "windows_dns_dhcp_management_enabled": bool(args.enable_windows_dns_dhcp_management),
        **hardware,
    }

    if args.enable_task_execution:
        print("WARNING: approved Cartman tasks may run on this endpoint.")
    else:
        print("Task execution is disabled. Use --enable-task-execution to opt in.")

    while True:
        try:
            print("Connecting to {}:{} ...".format(args.server, args.port))

            with socket.create_connection((args.server, args.port), timeout=10) as sock:
                sock.settimeout(120)
                with sock.makefile("rb") as stream:
                    send_json(sock, hello)
                    response = read_json(stream)
                    if response.get("status") == "challenge":
                        try:
                            challenge = base64.b64decode(
                                response.get("nonce", ""), validate=True
                            )
                            if len(challenge) != 32:
                                raise ValueError("Invalid server challenge.")
                            signature = identity_private_key.sign(challenge)
                            send_json(sock, {
                                "type": "authenticate",
                                "signature": base64.b64encode(signature).decode("ascii"),
                            })
                            response = read_json(stream)
                        except Exception as exc:
                            raise ConnectionError(
                                "Could not authenticate persistent Cartman identity: {}".format(exc)
                            ) from exc

                    print("Cartman:", response)

                    if response.get("status") != "connected":
                        raise ConnectionError("Cartman did not accept the connection.")

                    print("Connected. Waiting for approval and heartbeats. Press Ctrl+C to stop.")

                    while True:
                        time.sleep(max(5, args.heartbeat_interval))
                        telemetry = (
                            _collect_telemetry()
                            if response.get("approval_status") == "Approved"
                            else []
                        )
                        send_json(sock, {"type": "heartbeat", "telemetry": telemetry})
                        response = read_json(stream)

                        if response.get("status") == "rejected":
                            print("Connection request rejected by Cartman administrator.")
                            return
                        if response.get("status") != "connected":
                            raise ConnectionError("Invalid heartbeat response: {}".format(response))

                        print(
                            "Heartbeat OK:",
                            response.get("last_seen"),
                            "| approval:",
                            response.get("approval_status"),
                        )
                        if telemetry:
                            print(
                                "Telemetry samples accepted:",
                                response.get("telemetry_accepted", 0), "/", len(telemetry),
                            )
                        if response.get("telemetry_error"):
                            print("Telemetry warning:", response["telemetry_error"])

                        task = response.get("task")
                        if task:
                            task_payload = task.get("payload") or {}
                            is_dns_dhcp = (
                                task.get("action") == "remote_command"
                                and task_payload.get("connector_action")
                                == "windows_dns_dhcp_management_v1"
                            )
                            if is_dns_dhcp and args.enable_windows_dns_dhcp_management:
                                print(
                                    "Executing allowlisted DNS/DHCP action:",
                                    task.get("id"), task_payload.get("operation")
                                )
                                result_status, result_text = execute_task(task)
                            elif not args.enable_task_execution:
                                print("Task received but the required capability is disabled; not executing.")
                                result_status, result_text = "Failed", "This task requires its dedicated capability flag."
                            else:
                                print("Executing task:", task.get("id"), task.get("action"))
                                result_status, result_text = execute_task(task)

                            send_json(sock, {
                                "type": "task_result",
                                "task_id": task.get("id"),
                                "result_status": result_status,
                                "result": result_text,
                            })
                            ack = read_json(stream)
                            print("Task result:", result_status, result_text)
                            print("Cartman acknowledgement:", ack)

        except KeyboardInterrupt:
            print("\nClient stopped.")
            return
        except (OSError, ValueError, ConnectionError) as exc:
            print("CartmanClient connection lost:", str(exc))
            print("Retrying in 5 seconds. A new enrollment request may require approval.")
            time.sleep(5)


if __name__ == "__main__":
    main()
