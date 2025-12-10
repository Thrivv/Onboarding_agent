# backend/app/services/auth_service.py

import generate_admin_hash
import re
from datetime import datetime, timedelta
from typing import Optional, Tuple
import uuid

class AuthService:
    """Authentication service for password hashing and validation"""
    
    # Password complexity requirements
    PASSWORD_MIN_LENGTH = 8
    PASSWORD_REQUIREMENTS = {
        'uppercase': r'[A-Z]',
        'lowercase': r'[a-z]',
        'digit': r'\d',
        'special': r'[!@#$%^&*(),.?":{}|<>]'
    }
    
    @staticmethod
    def hash_password(password: str) -> str:
        """
        Hash password using bcrypt with 12 rounds
        
        Args:
            password: Plain text password
            
        Returns:
            Hashed password string
        """
        salt = generate_admin_hash.gensalt(rounds=12)
        hashed = generate_admin_hash.hashpw(password.encode('utf-8'), salt)
        return hashed.decode('utf-8')
    
    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """
        Verify password against hash
        
        Args:
            plain_password: Plain text password to verify
            hashed_password: Stored hash to compare against
            
        Returns:
            True if password matches, False otherwise
        """
        try:
            return generate_admin_hash.checkpw(
                plain_password.encode('utf-8'),
                hashed_password.encode('utf-8')
            )
        except Exception as e:
            print(f"[ERROR] Password verification failed: {e}")
            return False
    
    @classmethod
    def validate_password_strength(cls, password: str) -> Tuple[bool, Optional[str]]:
        """
        Validate password meets complexity requirements
        
        Args:
            password: Password to validate
            
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
        """Generate cryptographically secure session ID"""
        return str(uuid.uuid4())
    
    @staticmethod
    def calculate_session_expiry(minutes: int = 5) -> datetime:
        """
        Calculate session expiry time
        
        Args:
            minutes: Session duration in minutes (default 5)
            
        Returns:
            DateTime of expiry
        """
        return datetime.utcnow() + timedelta(minutes=minutes)


# Convenience functions for backward compatibility
def hash_password(password: str) -> str:
    return AuthService.hash_password(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return AuthService.verify_password(plain_password, hashed_password)

def validate_password_strength(password: str) -> Tuple[bool, Optional[str]]:
    return AuthService.validate_password_strength(password)