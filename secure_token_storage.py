"""
Secure token storage with encryption for production deployments.
Provides encrypted storage for OAuth tokens with Redis/session backend support.
"""

import base64
import json
import logging
import os
from typing import Any

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)


class TokenEncryption:
    """Handles token encryption/decryption using Fernet symmetric encryption."""

    def __init__(self, secret_key: str):
        """
        Initialize token encryption with a secret key.
        
        Args:
            secret_key: Base secret key for encryption (will be derived)
        """
        self.fernet = self._create_fernet(secret_key)

    def _create_fernet(self, secret_key: str) -> Fernet:
        """Create Fernet instance from secret key using PBKDF2."""
        # Use a fixed salt for consistent key derivation
        # In production, you might want to store/retrieve this salt separately
        salt = b'spotify_token_salt'

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(secret_key.encode()))
        return Fernet(key)

    def encrypt_token_data(self, token_data: dict[str, Any]) -> str:
        """
        Encrypt token data dictionary.
        
        Args:
            token_data: Dictionary containing token information
            
        Returns:
            Encrypted token data as base64 string
        """
        try:
            json_data = json.dumps(token_data)
            encrypted_data = self.fernet.encrypt(json_data.encode())
            return base64.urlsafe_b64encode(encrypted_data).decode()
        except Exception as e:
            logger.error(f"Failed to encrypt token data: {e}")
            raise

    def decrypt_token_data(self, encrypted_data: str) -> dict[str, Any]:
        """
        Decrypt token data.
        
        Args:
            encrypted_data: Base64 encoded encrypted token data
            
        Returns:
            Decrypted token data dictionary
        """
        try:
            encrypted_bytes = base64.urlsafe_b64decode(encrypted_data.encode())
            decrypted_data = self.fernet.decrypt(encrypted_bytes)
            return json.loads(decrypted_data.decode())
        except Exception as e:
            logger.error(f"Failed to decrypt token data: {e}")
            raise


class SecureTokenStorage:
    """Secure token storage with encryption for OAuth tokens."""

    def __init__(self, secret_key: str):
        """
        Initialize secure token storage.
        
        Args:
            secret_key: Secret key for encryption
        """
        self.encryption = TokenEncryption(secret_key)

    def store_token_in_session(self, session: dict, token_info: dict[str, Any]) -> None:
        """
        Store encrypted token data in Flask session.
        
        Args:
            session: Flask session object
            token_info: Token information dictionary
        """
        try:
            # Encrypt the entire token info
            encrypted_token = self.encryption.encrypt_token_data(token_info)
            session['encrypted_token'] = encrypted_token

            # Set permanent flag if it's a real Flask session
            if hasattr(session, 'permanent'):
                session.permanent = True

            # Store some metadata unencrypted for convenience
            session['token_expires_at'] = token_info.get('expires_at')
            session['has_refresh_token'] = bool(token_info.get('refresh_token'))

            logger.debug("Token stored securely in session")
        except Exception as e:
            logger.error(f"Failed to store token in session: {e}")
            raise

    def get_token_from_session(self, session: dict) -> dict[str, Any] | None:
        """
        Retrieve and decrypt token data from Flask session.
        
        Args:
            session: Flask session object
            
        Returns:
            Decrypted token information or None if not found/invalid
        """
        try:
            encrypted_token = session.get('encrypted_token')
            if not encrypted_token:
                return None

            token_info = self.encryption.decrypt_token_data(encrypted_token)
            logger.debug("Token retrieved securely from session")
            return token_info
        except Exception as e:
            logger.warning(f"Failed to retrieve token from session: {e}")
            # Clear invalid token data
            session.pop('encrypted_token', None)
            session.pop('token_expires_at', None)
            session.pop('has_refresh_token', None)
            return None

    def update_token_in_session(self, session: dict, token_info: dict[str, Any]) -> None:
        """
        Update encrypted token data in Flask session.
        
        Args:
            session: Flask session object
            token_info: Updated token information dictionary
        """
        self.store_token_in_session(session, token_info)

    def clear_token_from_session(self, session: dict) -> None:
        """
        Clear all token data from Flask session.
        
        Args:
            session: Flask session object
        """
        session.pop('encrypted_token', None)
        session.pop('token_expires_at', None)
        session.pop('has_refresh_token', None)
        logger.debug("Token data cleared from session")


def create_secure_token_storage(secret_key: str | None = None) -> SecureTokenStorage:
    """
    Factory function to create secure token storage instance.
    
    Args:
        secret_key: Optional secret key, defaults to FLASK_SECRET_KEY env var
        
    Returns:
        SecureTokenStorage instance
    """
    if not secret_key:
        secret_key = os.getenv('FLASK_SECRET_KEY')
        if not secret_key:
            raise ValueError("FLASK_SECRET_KEY environment variable must be set for secure token storage")

    return SecureTokenStorage(secret_key)
