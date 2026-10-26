"""Trusted local CLI for creating Cartman authentication accounts."""

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import main
import auth_security

auth_security.get_connection = main.get_connection


def main_cli():
    auth_security.initialize_auth_database()

    with auth_security._db() as connection:
        count = connection.execute(
            "SELECT COUNT(*) AS total FROM auth_accounts"
        ).fetchone()["total"]

    print("Cartman local account setup")
    print("Existing authentication accounts:", count)

    username = input("Username: ").strip()
    display_name = input("Display name: ").strip()

    if count == 0:
        role = "admin"
        print("First account will be the Administrator.")
    else:
        print("Roles: admin, network_admin, read_only")
        role = input("Role: ").strip()

    password = getpass.getpass("Password (minimum 14 characters): ")
    confirmation = getpass.getpass("Confirm password: ")

    if password != confirmation:
        raise SystemExit("Passwords do not match.")

    try:
        created = auth_security.create_account_local(
            username=username,
            display_name=display_name,
            password=password,
            role=role,
            require_empty=(count == 0),
        )
    except Exception as exc:
        raise SystemExit("Account creation failed: {}".format(exc))

    print("Account created.")
    print("Username:", created["username"])
    print("Role:", created["role"])
    print("Account ID:", created["id"])


if __name__ == "__main__":
    main_cli()
