#!/usr/bin/env python3
"""One-time setup helper for the JobSailor web control panel.

Generates:
  - a bcrypt hash of a password you choose (the plaintext is never stored anywhere)
  - a random session-signing secret

Usage:
    venv/bin/python scripts/generate_password_hash.py

Then paste the printed lines into your .env file.
"""
import getpass
import os
import sys
import bcrypt

def main() -> None:
    username = input("Choose a web UI username: ").strip()
    if not username:
        print("Username cannot be empty.", file=sys.stderr)
        sys.exit(1)

    pw1 = getpass.getpass("Choose a web UI password (min 8 chars): ")
    pw2 = getpass.getpass("Confirm password: ")

    if pw1 != pw2:
        print("Passwords did not match. Run this again.", file=sys.stderr)
        sys.exit(1)
    if len(pw1) < 8:
        print("Use at least 8 characters. Run this again.", file=sys.stderr)
        sys.exit(1)
    if len(pw1.encode("utf-8")) > 72:
        print("Password too long for bcrypt (max 72 bytes). Choose a shorter one.", file=sys.stderr)
        sys.exit(1)

    password_hash = bcrypt.hashpw(pw1.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    secret_key = os.urandom(32).hex()

    print("\nAdd these lines to your .env file:\n")
    print(f"WEB_UI_USER={username}")
    print(f"WEB_UI_PASSWORD_HASH={password_hash}")
    print(f"WEB_UI_SECRET_KEY={secret_key}")
    print(
        "\n(WEB_UI_SECRET_KEY signs your session cookies - keep it secret, "
        "and regenerating it will log out any active sessions.)"
    )


if __name__ == "__main__":
    main()
