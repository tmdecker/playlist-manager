"""
Error handling and classification for Spotify API failures.

Provides user-friendly error messages and structured error logging.
"""

import logging
from enum import Enum
from typing import Any

from spotipy.exceptions import SpotifyException

logger = logging.getLogger(__name__)


class ErrorType(Enum):
    """Error classification types for better user messaging."""
    RATE_LIMIT = "rate_limit"
    AUTHENTICATION = "authentication"
    SERVER_ERROR = "server_error"
    NETWORK_ERROR = "network_error"
    CLIENT_ERROR = "client_error"
    UNKNOWN = "unknown"


# User-friendly error messages by type
USER_FRIENDLY_MESSAGES = {
    ErrorType.RATE_LIMIT: "Spotify API rate limit reached. Please try again in a few minutes.",
    ErrorType.AUTHENTICATION: "Your Spotify session has expired. Please log in again.",
    ErrorType.SERVER_ERROR: "Spotify services are temporarily unavailable. Please try again later.",
    ErrorType.NETWORK_ERROR: "Unable to connect to Spotify. Check your internet connection.",
    ErrorType.CLIENT_ERROR: "Invalid request. Please check your input and try again.",
    ErrorType.UNKNOWN: "An unexpected error occurred. Please try again.",
}


def classify_spotify_error(error: Exception) -> ErrorType:
    """
    Classify Spotify API errors into user-friendly categories.
    
    Args:
        error: The exception to classify
        
    Returns:
        ErrorType enum value
    """
    if isinstance(error, SpotifyException):
        if error.http_status == 429:
            return ErrorType.RATE_LIMIT
        elif error.http_status == 401:
            return ErrorType.AUTHENTICATION
        elif error.http_status in [500, 502, 503, 504]:
            return ErrorType.SERVER_ERROR
        elif 400 <= error.http_status < 500:
            return ErrorType.CLIENT_ERROR
    
    # Check for network-related errors
    error_str = str(error).lower()
    if any(keyword in error_str for keyword in ['connection', 'network', 'timeout', 'dns']):
        return ErrorType.NETWORK_ERROR
    
    return ErrorType.UNKNOWN


def get_user_friendly_error(error: Exception) -> str:
    """
    Get a user-friendly error message for the given exception.
    
    Args:
        error: The exception to convert
        
    Returns:
        User-friendly error message string
    """
    error_type = classify_spotify_error(error)
    return USER_FRIENDLY_MESSAGES.get(error_type, USER_FRIENDLY_MESSAGES[ErrorType.UNKNOWN])


def log_error_with_context(error: Exception, context: dict[str, Any] | None = None) -> None:
    """
    Log error with structured context for debugging.
    
    Args:
        error: The exception to log
        context: Additional context information (user_id, playlist_id, operation, etc.)
    """
    error_type = classify_spotify_error(error)
    
    log_data = {
        'error_type': error_type.value,
        'error_class': error.__class__.__name__,
        'error_message': str(error),
    }
    
    if isinstance(error, SpotifyException):
        log_data['http_status'] = getattr(error, 'http_status', None)
        log_data['spotify_error'] = getattr(error, 'msg', None)
    
    if context:
        log_data.update(context)
    
    # Log at appropriate level based on error type
    if error_type in [ErrorType.RATE_LIMIT, ErrorType.SERVER_ERROR]:
        logger.warning("Spotify API error", extra=log_data, exc_info=True)
    elif error_type == ErrorType.AUTHENTICATION:
        logger.info("Authentication error", extra=log_data)
    else:
        logger.error("API operation failed", extra=log_data, exc_info=True)


def is_spotify_api_available(error: Exception) -> bool:
    """
    Check if error indicates Spotify API is unavailable.
    
    Args:
        error: The exception to check
        
    Returns:
        False if API is unavailable, True otherwise
    """
    error_type = classify_spotify_error(error)
    return error_type not in [ErrorType.NETWORK_ERROR, ErrorType.SERVER_ERROR]