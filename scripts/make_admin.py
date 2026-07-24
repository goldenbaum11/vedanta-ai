"""Promote a registered user to the admin role.

Usage:
    python3 scripts/make_admin.py --email jonas@example.com
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


async def promote(email: str) -> int:
    await database.init_db()
    async with database.get_connection() as conn:
        result = await conn.execute(
            text("UPDATE users SET role = 'admin' WHERE email = :email"),
            {"email": email.strip().lower()},
        )
        await conn.commit()
        if result.rowcount == 0:
            print(f"No user with email {email!r}. Register first, then re-run.")
            return 1
    print(f"{email} is now an admin.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    args = parser.parse_args()
    return asyncio.run(promote(args.email))


if __name__ == "__main__":
    sys.exit(main())
