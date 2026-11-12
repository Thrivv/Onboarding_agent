# backend/app/services/auth_service.py

import base64
import hashlib
import hmac
import re
from datetime import datetime, timedelta
from typing import Optional, Tuple
import uuid

import bcrypt

from app.config import PASSWORD_SECRET_KEY

# Every bcrypt hash produced by this module starts with one of these —
# used to tell a current hash apart from a pre-migration one. See
# PasswordHasher.needs_reset() and backend/scripts/force_password_reset.py.
_BCRYPT_PREFIXES = ("$2a$", "$2b$", "$2y$")


class PasswordHasher:
    """
    bcrypt password hashing, with an HMAC-SHA256 pre-hash as the pepper step.

    Replaces the previous two-step SHA-256 scheme —
    ``SHA256(SHA256(password + email) + SECRET_KEY)`` — which had two real
    weaknesses: SHA-256 is fast and GPU-friendly (cheap to brute-force offline
    from a leaked database), and using the user's own email as "salt" is
    deterministic and enumerable, not a real per-user salt.

    Design
    ------
    1. Pre-hash: ``HMAC-SHA256(key=PASSWORD_SECRET_KEY, msg=password)``.
       bcrypt only reads the first 72 bytes of its input and silently
       discards the rest, so a long passphrase would otherwise be truncated
       without warning. Reducing the password to a fixed 32-byte digest
       before bcrypt sidesteps that entirely, and folds the server-side
       pepper (PASSWORD_SECRET_KEY) into every hash — a leaked database on
       its own is no longer enough to attempt a crack; the attacker also
       needs the pepper.
    2. bcrypt: hashes the (base64-encoded) digest with a fresh random salt
       per call (``bcrypt.gensalt()``) at a deliberately slow work factor.
       The salt is stored inside the returned hash string itself, as usual
       for bcrypt — nothing extra needs to be persisted alongside it.

    Migration from the old scheme
    ------------------------------
    A SHA-256 hash cannot be converted to a bcrypt hash without the original
    plaintext password, so existing hashes cannot be transparently upgraded.
    Instead, ``backend/scripts/force_password_reset.py`` invalidates every
    pre-bcrypt hash, and ``needs_reset()`` below is how the login route (see
    app/api/routes/auth.py) tells "this account must reset its password"
    apart from "wrong password" — both a legacy SHA-256 hash and the
    invalidation sentinel that script writes are, correctly, hashes that no
    password will ever verify against, but they need a different, actionable
    error message rather than a generic "invalid credentials".
    """

    @staticmethod
    def _prehash(password: str) -> bytes:
        return hmac.new(
            PASSWORD_SECRET_KEY.encode("utf-8"),
            password.encode("utf-8"),
            hashlib.sha256,
        ).digest()

    @classmethod
    def hash_password(cls, password: str, email: str) -> str:
        """
        Hash a plain-text password with bcrypt.

        Args:
            password: Plain-text password supplied by the user.
            email:    Kept for call-site compatibility with every existing
                      caller (signup, reset-password, the migration script);
                      no longer part of the hash input. bcrypt's own random
                      salt replaces the old "email as salt" scheme, which was
                      deterministic and not a real salt.

        Returns:
            The bcrypt hash string (includes algorithm tag, cost and salt) to
            store in the database.
        """
        digest = cls._prehash(password)
        hashed = bcrypt.hashpw(base64.b64encode(digest), bcrypt.gensalt(rounds=12))
        return hashed.decode("utf-8")

    @classmethod
    def verify_password(cls, password: str, email: str, stored_hash: str) -> bool:
        """
        Verify a plain-text password against the stored hash.

        Returns False (never raises) for a hash that isn't a bcrypt hash —
        that covers both "no hash on file" and "pre-migration hash" — so a
        wrong-shape stored_hash reads to the caller exactly like a login
        that needs a password reset, not a server error. Callers that need
        to distinguish "needs reset" from "wrong password" should check
        ``needs_reset(stored_hash)`` themselves before calling this.
        """
        if not stored_hash or not stored_hash.startswith(_BCRYPT_PREFIXES):
            return False
        try:
            digest = cls._prehash(password)
            return bcrypt.checkpw(base64.b64encode(digest), stored_hash.encode("utf-8"))
        except Exception:
            return False

    @staticmethod
    def needs_reset(stored_hash: Optional[str]) -> bool:
        """
        True when `stored_hash` cannot be verified by this scheme at all —
        either it's empty, it's a pre-migration SHA-256 hash, or it's the
        RESET_SENTINEL written by force_password_reset.py. In every one of
        those cases the account must go through /auth/reset-password; no
        password will ever verify successfully against it.
        """
        return not bool(stored_hash) or not stored_hash.startswith(_BCRYPT_PREFIXES)


class AuthService:
    """Authentication service — password complexity, session helpers."""

    PASSWORD_MIN_LENGTH = 8
    PASSWORD_REQUIREMENTS = {
        "uppercase": r"[A-Z]",
        "lowercase": r"[a-z]",
        "digit": r"\d",
        "special": r'[!@#$%^&*(),.?":{}|<>]',
    }

    @classmethod
    def validate_password_strength(cls, password: str) -> Tuple[bool, Optional[str]]:
        """
        Validate password meets complexity requirements.

        Returns:
            Tuple of (is_valid, error_message)
        """
        if len(password) < cls.PASSWORD_MIN_LENGTH:
            return False, f"Password must be at least {cls.PASSWORD_MIN_LENGTH} characters long"

        for requirement, pattern in cls.PASSWORD_REQUIREMENTS.items():
            if not re.search(pattern, password):
                return False, f"Password must contain at least one {requirement} character"

        return True, None

    @staticmethod
    def generate_session_id() -> str:
        """Generate a cryptographically secure session ID."""
        return str(uuid.uuid4())

    @staticmethod
    def calculate_session_expiry(minutes: int = 5) -> datetime:
        """Return the UTC datetime at which a session expires."""
        return datetime.utcnow() + timedelta(minutes=minutes)


# ---------------------------------------------------------------------------
# Module-level convenience aliases
# ---------------------------------------------------------------------------

def hash_password(password: str, email: str) -> str:
    return PasswordHasher.hash_password(password, email)

def verify_password(password: str, email: str, stored_hash: str) -> bool:
    return PasswordHasher.verify_password(password, email, stored_hash)

def needs_password_reset(stored_hash: Optional[str]) -> bool:
    return PasswordHasher.needs_reset(stored_hash)

def validate_password_strength(password: str) -> Tuple[bool, Optional[str]]:
    return AuthService.validate_password_strength(password)
