from pathlib import Path
from datetime import datetime
import shutil
import sys

ROOT = Path.cwd()
MAIN = ROOT / "app/main.py"
CLIENT = ROOT / "client/cartman_client.py"

for path in (MAIN, CLIENT):
    if not path.is_file():
        sys.exit("ABORTED: File not found: {}".format(path))

main = MAIN.read_text(encoding="utf-8")
client = CLIENT.read_text(encoding="utf-8")


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            "{}: expected exactly one match, found {}. "
            "No source files have been changed.".format(label, count)
        )
    return text.replace(old, new, 1)


def add_import(source, module, anchor="import json\n"):
    line = "import " + module + "\n"
    if line in source:
        return source
    if source.count(anchor) != 1:
        raise RuntimeError("Could not insert import: " + module)
    return source.replace(anchor, anchor + line, 1)


try:
    # Backend standard-library imports.
    main = add_import(main, "base64")
    main = add_import(main, "secrets")

    # Client imports. The private key never leaves the endpoint.
    client = add_import(client, "base64", "import argparse\n")

    crypto_imports = (
        "from cryptography.hazmat.primitives import serialization\n"
        "from cryptography.hazmat.primitives.asymmetric.ed25519 "
        "import Ed25519PrivateKey\n"
    )
    if "from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey\n" not in client:
        client = replace_once(
            client,
            "import uuid\n",
            "import uuid\n\n" + crypto_imports,
            "Client crypto imports",
        )

    # Persistent credential registry. Existing device and task tables are untouched.
    credential_table = '''with get_connection() as connection:
    connection.execute("""
        CREATE TABLE IF NOT EXISTS device_agent_credentials (
            client_instance TEXT PRIMARY KEY,
            device_id TEXT NOT NULL,
            public_key TEXT NOT NULL,
            revoked INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_seen TEXT
        )
    """)
    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_device_agent_credentials_device
        ON device_agent_credentials(device_id)
    """)


'''
    main = replace_once(
        main,
        "def normalize_os_family(value):",
        credential_table + "def normalize_os_family(value):",
        "Persistent credential table",
    )

    # Replace the connection handler's ephemeral enrollment block.
    start_marker = "            task_execution_enabled = hello.get(\"task_execution_enabled\") is True"
    end_marker = "            # Allow long-running approved tasks to report their final result."
    start = main.find(start_marker)
    end = main.find(end_marker, start)

    if start < 0 or end < 0 or main.find(start_marker, start + 1) >= 0:
        raise RuntimeError(
            "Could not uniquely locate the CartmanClient hello handler. "
            "No source files have been changed."
        )

    handler_block = r'''            task_execution_enabled = hello.get("task_execution_enabled") is True

            client_instance = hello.get("client_instance")
            public_key_text = hello.get("public_key")

            try:
                if not isinstance(client_instance, str):
                    raise ValueError("Missing persistent client ID.")
                client_instance = str(uuid.UUID(client_instance))
                if not isinstance(public_key_text, str):
                    raise ValueError("Missing client public key.")
                public_key_bytes = base64.b64decode(
                    public_key_text, validate=True
                )
                if len(public_key_bytes) != 32:
                    raise ValueError("Invalid public key length.")
            except (ValueError, TypeError, AttributeError):
                self._reply({
                    "status": "error",
                    "message": (
                        "This CartmanClient version has no valid persistent identity. "
                        "Update the client before connecting."
                    ),
                })
                return

            hardware = {}
            for key in ("model", "manufacturer", "device_type", "cpu", "ram", "disk", "gpu"):
                value = hello.get(key, "")
                hardware[key] = value.strip()[:180] if isinstance(value, str) else ""

            identity_metadata = dict(hardware)
            identity_metadata["client_instance"] = client_instance
            identity_metadata["public_key"] = public_key_text

            connection_id = str(uuid.uuid4())
            request_id = str(uuid.uuid4())
            client_ip = str(self.client_address[0])[:64]

            with get_connection() as connection:
                trusted = connection.execute(
                    """
                    SELECT device_id, public_key, revoked
                    FROM device_agent_credentials
                    WHERE client_instance = ?
                    """,
                    (client_instance,),
                ).fetchone()

            device_id = None
            approval = "Pending"

            if trusted is not None:
                if trusted["revoked"]:
                    self._reply({
                        "status": "error",
                        "message": "This CartmanClient identity has been revoked.",
                    })
                    return

                if trusted["public_key"] != public_key_text:
                    self._reply({
                        "status": "error",
                        "message": "Client identity key mismatch. Connection refused.",
                    })
                    return

                challenge = secrets.token_bytes(32)
                self._reply({
                    "status": "challenge",
                    "nonce": base64.b64encode(challenge).decode("ascii"),
                })

                raw_auth = self.rfile.readline(8193)
                if not raw_auth or len(raw_auth) > 8192 or not raw_auth.endswith(b"\n"):
                    self._reply({
                        "status": "error",
                        "message": "Missing or invalid identity proof.",
                    })
                    return

                try:
                    auth_message = json.loads(raw_auth.decode("utf-8"))
                    if not isinstance(auth_message, dict) or auth_message.get("type") != "authenticate":
                        raise ValueError("Invalid authentication message.")
                    signature = base64.b64decode(
                        auth_message.get("signature", ""), validate=True
                    )
                    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
                    Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(
                        signature, challenge
                    )
                except Exception:
                    self._reply({
                        "status": "error",
                        "message": "Client identity verification failed.",
                    })
                    return

                device_id = trusted["device_id"]
                with get_connection() as connection:
                    device = connection.execute(
                        "SELECT id FROM devices WHERE id = ?",
                        (device_id,),
                    ).fetchone()

                    if device is None:
                        self._reply({
                            "status": "error",
                            "message": (
                                "The registered inventory device no longer exists. "
                                "Administrator re-enrollment is required."
                            ),
                        })
                        return

                    connection.execute(
                        """
                        UPDATE devices
                        SET os = ?, ip = ?, local_ip = ?, username = ?,
                            status = 'Online', updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (os_name.strip(), client_ip, client_ip, username.strip(), device_id),
                    )
                    connection.execute(
                        """
                        UPDATE device_agent_credentials
                        SET last_seen = CURRENT_TIMESTAMP
                        WHERE client_instance = ?
                        """,
                        (client_instance,),
                    )
                    connection.execute(
                        """
                        INSERT INTO device_connection_requests
                            (id, device_name, os, client_ip, username,
                             status, reviewed_at, device_id, metadata_json)
                        VALUES (?, ?, ?, ?, ?, 'Approved', CURRENT_TIMESTAMP, ?, ?)
                        """,
                        (
                            request_id, name.strip(), os_name.strip(), client_ip,
                            username.strip(), device_id,
                            json.dumps(identity_metadata, ensure_ascii=False),
                        ),
                    )

                approval = "Approved"

            else:
                with get_connection() as connection:
                    connection.execute(
                        """
                        INSERT INTO device_connection_requests
                            (id, device_name, os, client_ip, username, metadata_json)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            request_id, name.strip(), os_name.strip(), client_ip,
                            username.strip(),
                            json.dumps(identity_metadata, ensure_ascii=False),
                        ),
                    )

            now = self._utc_now()

            with _connection_clients_lock:
                _connection_clients[connection_id] = {
                    "connection_id": connection_id,
                    "request_id": request_id,
                    "device_id": device_id,
                    "client_instance": client_instance,
                    "device_name": name.strip(),
                    "os": os_name.strip(),
                    "username": username.strip(),
                    "client_ip": client_ip,
                    "connected": True,
                    "state": "Connected" if approval == "Approved"
                        else "Connected · awaiting approval",
                    "approval_status": approval,
                    "task_execution_enabled": task_execution_enabled,
                    "connected_at": now,
                    "last_seen": now,
                }

            self._reply({
                "status": "connected",
                "approval_status": approval,
                "request_id": request_id,
                "device_id": device_id,
                "message": (
                    "Authenticated existing device session."
                    if approval == "Approved"
                    else "New client identity; awaiting administrator approval."
                ),
            })

'''
    main = main[:start] + handler_block + main[end:]

    # Bind a new identity to its device only when an administrator approves it.
    approval_anchor = (
        '        connection.execute(\n'
        '            """\n'
        '            UPDATE device_connection_requests\n'
        '            SET status = ?, reviewed_at = CURRENT_TIMESTAMP, device_id = ?'
    )

    bind_credential = r'''        if decision.decision == "Approved":
            client_instance = hardware.get("client_instance")
            public_key_text = hardware.get("public_key")

            if client_instance or public_key_text:
                try:
                    client_instance = str(uuid.UUID(client_instance))
                    public_key_bytes = base64.b64decode(
                        public_key_text, validate=True
                    )
                    if len(public_key_bytes) != 32:
                        raise ValueError("Invalid public key length.")
                except (ValueError, TypeError, AttributeError):
                    raise HTTPException(
                        status_code=422,
                        detail="The client identity key is invalid.",
                    )

                prior = connection.execute(
                    """
                    SELECT device_id, public_key
                    FROM device_agent_credentials
                    WHERE client_instance = ?
                    """,
                    (client_instance,),
                ).fetchone()

                if prior and (
                    prior["device_id"] != device_id
                    or prior["public_key"] != public_key_text
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="This client identity is already bound to another device.",
                    )

                connection.execute(
                    """
                    INSERT INTO device_agent_credentials
                        (client_instance, device_id, public_key, last_seen)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(client_instance) DO UPDATE SET
                        device_id = excluded.device_id,
                        public_key = excluded.public_key,
                        revoked = 0,
                        last_seen = CURRENT_TIMESTAMP
                    """,
                    (client_instance, device_id, public_key_text),
                )

'''
    main = replace_once(
        main,
        approval_anchor,
        bind_credential + approval_anchor,
        "Bind client identity on administrator approval",
    )

    # Client identity is stored under the OS user's data directory.
    identity_helper = r'''def _client_identity_path():
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


'''
    client = replace_once(
        client,
        "def main():",
        identity_helper + "def main():",
        "Client persistent identity helper",
    )

    client = replace_once(
        client,
        '    hardware = get_hardware_info()\n',
        '    client_instance, identity_private_key, public_key_text = load_or_create_identity()\n'
        '    print("Persistent Cartman device ID:", client_instance)\n'
        '    print("Identity file:", _client_identity_path())\n'
        '\n'
        '    hardware = get_hardware_info()\n',
        "Load persistent identity",
    )

    client = replace_once(
        client,
        '"client_instance": str(uuid.uuid4()),',
        '"client_instance": client_instance,\n        "public_key": public_key_text,',
        "Use persistent client ID",
    )

    challenge_anchor = (
        '                    response = read_json(stream)\n'
        '                    print("Cartman:", response)\n'
    )
    challenge_client = r'''                    response = read_json(stream)
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
'''
    client = replace_once(
        client,
        challenge_anchor,
        challenge_client,
        "Client challenge-response handshake",
    )

except RuntimeError as exc:
    sys.exit("PATCH ABORTED: {}".format(exc))

# Verify the dependency before writing any source files.
try:
    import subprocess
    subprocess.run(
        [str(ROOT / ".venv/bin/python"), "-c",
         "from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
except Exception as exc:
    sys.exit(
        "PATCH ABORTED: cryptography is not available in .venv. "
        "Install it first with .venv/bin/python -m pip install "
        "'cryptography>=41,<46'. Details: {}".format(exc)
    )

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
backups = []

try:
    for path in (MAIN, CLIENT):
        backup = path.with_name(
            path.name + ".before-persistent-identity-" + stamp + ".bak"
        )
        shutil.copy2(path, backup)
        backups.append((path, backup))

    MAIN.write_text(main, encoding="utf-8")
    CLIENT.write_text(client, encoding="utf-8")

except Exception as exc:
    print("WRITE ERROR:", exc)
    for path, backup in backups:
        try:
            shutil.copy2(backup, path)
            print("RESTORED:", backup)
        except Exception as restore_exc:
            print("RESTORE ERROR:", path, restore_exc)
    sys.exit(1)

for path, backup in backups:
    print("UPDATED:", path.relative_to(ROOT))
    print("BACKUP: ", backup.relative_to(ROOT))

print("PATCH APPLIED: persistent device identity is installed.")
print("Existing devices and task history were not deleted.")
