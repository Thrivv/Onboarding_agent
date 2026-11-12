"""
backend/scripts/force_password_reset.py

One-off migration: invalidate every existing password hash so all users are
forced through the new POST /auth/request-password-reset ->
POST /auth/reset-password flow the next time they try to log in.

Why this is needed
-------------------
Passwords used to be hashed as SHA256(SHA256(password + email) + SECRET_KEY)
(see the previous version of app/services/auth_service.py). That scheme is
fast and GPU-crackable, and used the user's own email as a non-random,
enumerable "salt" rather than a real one. The app now hashes with bcrypt plus
an HMAC-SHA256 pepper instead (see auth_service.PasswordHasher), which is a
different, one-way transform — there is no way to convert an existing
SHA-256 hash into a bcrypt hash without the original plaintext password, so
every existing hash must be invalidated rather than migrated in place.

What this does
----------------
Sets `password_hash` to RESET_SENTINEL for every user row whose current hash
is not already a bcrypt hash (i.e. does not start with $2a$/$2b$/$2y$) — so
it is also safe to re-run after some users have already reset.
`PasswordHasher.needs_reset()` treats any non-bcrypt value, including this
sentinel, as "must reset" — see its docstring — so a login attempt against a
migrated account gets routed to the reset flow instead of a generic
"invalid credentials", and the sentinel itself can never verify successfully
against any password (it never went through hash_password()).

How to run
-----------
Requires real credentials in the environment — SUPABASE_URL and
SUPABASE_SERVICE_ROLE_KEY (the anon key does not have the row-level-security
permissions to update other users' rows). Run this ONCE, right after
deploying the bcrypt change:

    cd backend
    python -m scripts.force_password_reset             # dry run — lists who would be affected
    python -m scripts.force_password_reset --confirm    # actually writes the sentinel

It requires --confirm on purpose, so it cannot be triggered by accident
(e.g. by an automated script that imports this module).
"""

from __future__ import annotations

import argparse

from app.repositories.base import supabase_service

RESET_SENTINEL = "RESET_REQUIRED:legacy-sha256-invalidated"

_BCRYPT_PREFIXES = ("$2a$", "$2b$", "$2y$")


def _needs_migration(password_hash: str | None) -> bool:
    return not password_hash or not password_hash.startswith(_BCRYPT_PREFIXES)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="actually write the change (default is a dry run that only reports counts)",
    )
    args = parser.parse_args()

    resp = supabase_service.table("users").select("id, email, password_hash").execute()
    rows = resp.data or []
    to_migrate = [r for r in rows if _needs_migration(r.get("password_hash"))]

    print(f"{len(rows)} user(s) total; {len(to_migrate)} carry a pre-bcrypt hash "
          f"and will be forced to reset their password.")

    if not args.confirm:
        print("Dry run only — re-run with --confirm to write the change.")
        return

    migrated = 0
    for row in to_migrate:
        supabase_service.table("users").update(
            {"password_hash": RESET_SENTINEL}
        ).eq("id", row["id"]).execute()
        migrated += 1
        print(f"  invalidated: {row.get('email')}")

    print(f"Done — {migrated} account(s) will be prompted to reset their "
          f"password the next time they try to log in.")


if __name__ == "__main__":
    main()
