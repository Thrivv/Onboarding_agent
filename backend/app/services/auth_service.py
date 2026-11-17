# backend/app/services/auth_service.py

import hashlib
import base64
import re
from datetime import datetime, timedelta
from typing import Optional, Tuple
import uuid

from app.config import PASSWORD_SECRET_KEY


class PasswordHasher:
    """
    Two-step SHA256 password hashing utility.

    Step 1 — hash with email as salt:
        SHA256_Base64(password + email)

    Step 2 — hash with secret key:
        SHA256_Base64(step1_hash + SECRET_KEY)

    The result of step 2 is stored in the database.
    """

    @staticmethod
    def _sha256_base64(value: str) -> str:
        """Compute SHA-256 and return Base64-encoded result (standard encoding)."""
        digest = hashlib.sha256(value.encode("utf-8")).digest()
        return base64.b64encode(digest).decode("utf-8")

    @classmethod
    def hash_password(cls, password: str, email: str) -> str:
        """
        Hash a plain-text password using the two-step scheme.

        Args:
            password: Plain-text password supplied by the user.
            email:    User's email address (used as salt in step 1).

        Returns:
            Final Base64-encoded hash to store in the database.
        """
        # 1st hash: password + email
        first_hash = cls._sha256_base64(password + email)
        # 2nd hash: first_hash + SECRET_KEY
        second_hash = cls._sha256_base64(first_hash + PASSWORD_SECRET_KEY)
        return second_hash

    @classmethod
    def verify_password(cls, password: str, email: str, stored_hash: str) -> bool:
        """
        Verify a plain-text password against the stored hash.

        Args:
            password:    Plain-text password to verify.
            email:       User's email address.
            stored_hash: Hash retrieved from the database.

        Returns:
            True if the password matches, False otherwise.
        """
        try:
            return cls.hash_password(password, email) == stored_hash
        except Exception:
            return False


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

def validate_password_strength(password: str) -> Tuple[bool, Optional[str]]:
    return AuthService.validate_password_strength(password)
