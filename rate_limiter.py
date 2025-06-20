import logging
import random
import time
from collections.abc import Callable
from functools import wraps
from typing import Any

from spotipy.exceptions import SpotifyException

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SpotifyRateLimiter:
    """
    Rate limiter for Spotify API calls with exponential backoff and jitter.
    
    Implements best practices from Spotify API documentation:
    - Exponential backoff with jitter for 429 errors
    - Retry-After header handling
    - Request throttling to stay within rate limits
    """

    def __init__(self,
                 base_delay: float = 1.0,
                 max_delay: float = 60.0,
                 max_retries: int = 5,
                 jitter: bool = True):
        """
        Initialize rate limiter.
        
        Args:
            base_delay: Base delay in seconds for exponential backoff
            max_delay: Maximum delay in seconds
            max_retries: Maximum number of retry attempts
            jitter: Whether to add jitter to backoff delays
        """
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.max_retries = max_retries
        self.jitter = jitter
        self.last_request_time = 0
        self.min_request_interval = 1.0 / 3.0  # ~3 requests/second safe limit

    def _calculate_delay(self, attempt: int, retry_after: int | None = None) -> float:
        """
        Calculate delay using exponential backoff with optional jitter.
        
        Args:
            attempt: Current retry attempt number (0-based)
            retry_after: Retry-After header value in seconds
            
        Returns:
            Delay in seconds
        """
        if retry_after:
            # Use Retry-After header if provided
            delay = retry_after
        else:
            # Exponential backoff: base_delay * (2 ^ attempt)
            delay = self.base_delay * (2 ** attempt)

        # Cap at max_delay
        delay = min(delay, self.max_delay)

        # Add jitter to prevent thundering herd
        if self.jitter:
            jitter_range = delay * 0.1  # 10% jitter
            delay += random.uniform(-jitter_range, jitter_range)

        return max(0, delay)

    def _throttle_request(self):
        """Throttle requests to stay within safe rate limits."""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time

        if time_since_last < self.min_request_interval:
            sleep_time = self.min_request_interval - time_since_last
            logger.debug(f"Throttling request: sleeping {sleep_time:.2f}s")
            time.sleep(sleep_time)

        self.last_request_time = time.time()

    def _handle_spotify_exception(self, e: SpotifyException) -> tuple[bool, int | None]:
        """
        Handle Spotify API exceptions and determine if retry is appropriate.
        
        Args:
            e: SpotifyException instance
            
        Returns:
            Tuple of (should_retry, retry_after_seconds)
        """
        if e.http_status == 429:
            # Rate limit exceeded
            retry_after = None
            if hasattr(e, 'headers') and e.headers:
                retry_after = e.headers.get('Retry-After')
                if retry_after:
                    try:
                        retry_after = int(retry_after)
                    except ValueError:
                        retry_after = None

            logger.warning(f"Rate limit exceeded. Retry-After: {retry_after}")
            return True, retry_after

        elif e.http_status in [500, 502, 503, 504]:
            # Server errors - retry with backoff
            logger.warning(f"Server error {e.http_status}: {e!s}")
            return True, None

        else:
            # Client errors or other issues - don't retry
            logger.error(f"API error {e.http_status}: {e!s}")
            return False, None

    def execute_with_retry(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute a function with rate limiting and retry logic.
        
        Args:
            func: Function to execute
            *args: Positional arguments for the function
            **kwargs: Keyword arguments for the function
            
        Returns:
            Function result
            
        Raises:
            SpotifyException: If all retries are exhausted
        """
        last_exception = None

        for attempt in range(self.max_retries + 1):
            try:
                # Throttle requests to stay within rate limits
                self._throttle_request()

                # Execute the function
                result = func(*args, **kwargs)

                # Success - reset any previous failures
                if attempt > 0:
                    logger.info(f"Request succeeded after {attempt} retries")

                return result

            except SpotifyException as e:
                last_exception = e
                should_retry, retry_after = self._handle_spotify_exception(e)

                if not should_retry or attempt >= self.max_retries:
                    logger.error(f"Request failed after {attempt} attempts: {e!s}")
                    raise e

                # Calculate delay and wait before retry
                delay = self._calculate_delay(attempt, retry_after)
                logger.info(f"Retrying in {delay:.2f}s (attempt {attempt + 1}/{self.max_retries})")
                time.sleep(delay)

            except Exception as e:
                # Non-Spotify exceptions - don't retry
                logger.error(f"Unexpected error: {e!s}")
                raise e

        # This should never be reached, but just in case
        if last_exception:
            raise last_exception
        else:
            raise Exception("Maximum retries exceeded")


def rate_limited_spotify_call(rate_limiter: SpotifyRateLimiter | None = None):
    """
    Decorator for rate-limited Spotify API calls.
    
    Args:
        rate_limiter: SpotifyRateLimiter instance. If None, creates default instance.
    """
    if rate_limiter is None:
        rate_limiter = SpotifyRateLimiter()

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            return rate_limiter.execute_with_retry(func, *args, **kwargs)
        return wrapper
    return decorator


# Global rate limiter instance
_default_rate_limiter = SpotifyRateLimiter()

def get_default_rate_limiter() -> SpotifyRateLimiter:
    """Get the default rate limiter instance."""
    return _default_rate_limiter

def rate_limited_call(func: Callable, *args, **kwargs) -> Any:
    """
    Execute a function with default rate limiting.
    
    Convenience function for one-off rate-limited calls.
    """
    return _default_rate_limiter.execute_with_retry(func, *args, **kwargs)
