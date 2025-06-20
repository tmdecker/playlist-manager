"""
OAuth state storage implementations for production and development environments.
Provides Redis-based storage with automatic fallback to in-memory storage.
"""

import logging
import os
import time
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class OAuthStateStore(ABC):
    """Abstract base class for OAuth state storage."""

    @abstractmethod
    def set_state(self, state: str, value: bool = True, ttl: int = 300) -> None:
        """Store an OAuth state with optional TTL in seconds."""
        pass

    @abstractmethod
    def get_state(self, state: str) -> bool | None:
        """Retrieve an OAuth state. Returns None if not found or expired."""
        pass

    @abstractmethod
    def delete_state(self, state: str) -> None:
        """Delete an OAuth state."""
        pass

    @abstractmethod
    def cleanup(self) -> None:
        """Clean up expired states (if applicable)."""
        pass


class RedisOAuthStateStore(OAuthStateStore):
    """Redis-based OAuth state storage with automatic expiration."""

    def __init__(self, redis_client):
        """
        Initialize Redis OAuth state store.
        
        Args:
            redis_client: Connected Redis client instance
        """
        self.redis = redis_client
        self.prefix = "oauth_state:"

    def set_state(self, state: str, value: bool = True, ttl: int = 300) -> None:
        """Store an OAuth state with TTL (default 5 minutes)."""
        try:
            key = f"{self.prefix}{state}"
            logger.info(f"Redis setex: {key}")
            self.redis.setex(key, ttl, "1" if value else "0")
        except Exception as e:
            logger.error(f"Redis setex failed: {e}")
            raise

    def get_state(self, state: str) -> bool | None:
        """Retrieve an OAuth state."""
        try:
            key = f"{self.prefix}{state}"
            result = self.redis.get(key)
            if result is None:
                return None
            return result == "1"
        except Exception as e:
            logger.error(f"Redis get failed: {e}")
            raise

    def delete_state(self, state: str) -> None:
        """Delete an OAuth state."""
        try:
            key = f"{self.prefix}{state}"
            self.redis.delete(key)
        except Exception as e:
            logger.error(f"Redis delete failed: {e}")
            raise

    def cleanup(self) -> None:
        """No cleanup needed - Redis handles expiration automatically."""
        pass


class InMemoryOAuthStateStore(OAuthStateStore):
    """In-memory OAuth state storage for development/fallback."""

    def __init__(self):
        """Initialize in-memory store with expiration tracking."""
        self.states: dict[str, dict[str, any]] = {}
        self._last_cleanup = time.time()

    def set_state(self, state: str, value: bool = True, ttl: int = 300) -> None:
        """Store an OAuth state with expiration time."""
        self.states[state] = {
            'value': value,
            'expires_at': time.time() + ttl
        }
        # Periodic cleanup every 60 seconds
        if time.time() - self._last_cleanup > 60:
            self.cleanup()

    def get_state(self, state: str) -> bool | None:
        """Retrieve an OAuth state if not expired."""
        if state not in self.states:
            return None

        state_data = self.states[state]
        if time.time() > state_data['expires_at']:
            # State expired
            del self.states[state]
            return None

        return state_data['value']

    def delete_state(self, state: str) -> None:
        """Delete an OAuth state."""
        self.states.pop(state, None)

    def cleanup(self) -> None:
        """Remove all expired states."""
        current_time = time.time()
        expired_states = [
            state for state, data in self.states.items()
            if current_time > data['expires_at']
        ]
        for state in expired_states:
            del self.states[state]
        self._last_cleanup = current_time


def create_oauth_state_store() -> OAuthStateStore:
    """
    Factory function to create appropriate OAuth state store.
    
    Returns:
        RedisOAuthStateStore if Redis is available, otherwise InMemoryOAuthStateStore
    """
    redis_url = os.getenv('REDIS_URL')

    if redis_url:
        try:
            import redis
            # Create Redis client
            client = redis.from_url(redis_url, decode_responses=True)
            # Test connection
            client.ping()
            # Test a real operation to verify Redis actually works
            test_key = "test_connection"
            client.set(test_key, "test_value", ex=10)
            result = client.get(test_key)
            client.delete(test_key)
            if result != "test_value":
                raise Exception("Redis test operation failed")
            logger.info("Using Redis for OAuth state storage - connection verified")
            return RedisOAuthStateStore(client)
        except ImportError:
            logger.warning("Redis package not installed. Install with: pip install redis")
        except Exception as e:
            logger.warning(f"Failed to connect to Redis: {e}. Falling back to in-memory storage")

    logger.info("Using in-memory OAuth state storage")
    return InMemoryOAuthStateStore()
