"""Server administration commands.

    python manage.py create-admin          # create an admin account (prompts for details)
    python manage.py reset-password EMAIL  # set a new password and sign out that admin's sessions
    python manage.py list-admins
"""
from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import select

from auth import AuthService, hash_password, password_problem
from config import settings
from database_models import AdminUser, Database


def prompt_password() -> str:
    while True:
        password = getpass.getpass("Password: ")
        problem = password_problem(password)
        if problem:
            print(problem)
            continue
        if getpass.getpass("Repeat password: ") != password:
            print("Passwords don't match.")
            continue
        return password


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-admin")
    create.add_argument("--email")
    create.add_argument("--name")
    reset = sub.add_parser("reset-password")
    reset.add_argument("email")
    sub.add_parser("list-admins")
    args = parser.parse_args()

    db = Database(settings)
    db.create_all()
    auth = AuthService(db)

    if args.command == "create-admin":
        email = args.email or input("Email: ").strip()
        name = args.name or input("Name: ").strip()
        try:
            user = auth.create_admin(email, name, prompt_password())
        except ValueError as exc:
            print(f"Error: {exc}")
            return 1
        print(f"Created admin {user.email}. Sign in at /admin.")
    elif args.command == "reset-password":
        with db.session() as s:
            user = s.scalar(select(AdminUser).where(AdminUser.email == args.email.strip().lower()))
            if user is None:
                print(f"No admin with email {args.email}.")
                return 1
            user.password_hash = hash_password(prompt_password())
            admin_id = user.id
        auth.end_other_sessions(admin_id, keep_token=None)
        print("Password updated; existing sessions were signed out.")
    else:
        for user in auth.list_admins():
            print(f"{user.id:>4}  {user.email:40s} {user.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
