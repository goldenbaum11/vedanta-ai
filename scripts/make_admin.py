"""Set a registered user's role.

Usage:
    python3 scripts/make_admin.py --email jonas@example.com
    python3 scripts/make_admin.py --email reviewer@example.com --role reviewer

`reviewer` is a restricted role for external collaborators: it can only
reach the pairs-review page/API, never transcripts, training, deployment,
or user management (see backend/security/auth.py::current_reviewer_or_admin).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import text  # noqa: E402

from backend import database  # noqa: E402

VALID_ROLES = {"admin", "reviewer", "student"}


async def set_role(email: str, role: str) -> int:
    await database.init_db()
    async with database.get_connection() as conn:
        result = await conn.execute(
            text("UPDATE users SET role = :role WHERE email = :email"),
            {"role": role, "email": email.strip().lower()},
        )
        await conn.commit()
        if result.rowcount == 0:
            print(f"No user with email {email!r}. Register first, then re-run.")
            return 1
    print(f"{email} is now a(n) {role}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument(
        "--role",
        default="admin",
        choices=sorted(VALID_ROLES),
        help="Role to assign (default: admin).",
    )
    args = parser.parse_args()
    return asyncio.run(set_role(args.email, args.role))


if __name__ == "__main__":
    sys.exit(main())
