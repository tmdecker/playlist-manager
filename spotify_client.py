
import requests
import spotipy
from spotipy.oauth2 import SpotifyOAuth


def create_spotify_session() -> requests.Session:
    """
    Create a requests session with descriptive User-Agent header for API identification.
    
    Returns:
        Configured requests session with User-Agent header
    """
    session = requests.Session()

    # Set descriptive User-Agent header for API identification
    user_agent = "PlaylistManager/1.0 (Playlist Management Web App; github.com/tmdecker)"
    session.headers.update({
        "User-Agent": user_agent
    })

    return session


def create_spotify_client(
    access_token: str | None = None,
    auth_manager: SpotifyOAuth | None = None,
    requests_session: requests.Session | None = None
) -> spotipy.Spotify:
    """
    Create a Spotify client with custom User-Agent header.
    
    Args:
        access_token: OAuth access token for authenticated requests
        auth_manager: SpotifyOAuth manager for token handling
        requests_session: Custom requests session (if None, creates one with User-Agent)
    
    Returns:
        Configured Spotify client with User-Agent header
    """
    if requests_session is None:
        requests_session = create_spotify_session()

    return spotipy.Spotify(
        auth=access_token,
        auth_manager=auth_manager,
        requests_session=requests_session
    )


def create_spotify_oauth(
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    scope: str,
    state: str | None = None,
    cache_handler=None,
    cache_path: str | None = None,
    requests_session: requests.Session | None = None
) -> SpotifyOAuth:
    """
    Create SpotifyOAuth with custom User-Agent header.
    
    Args:
        client_id: Spotify app client ID
        client_secret: Spotify app client secret  
        redirect_uri: OAuth redirect URI
        scope: Space-separated list of Spotify scopes
        state: State parameter for CSRF protection
        cache_handler: Token cache handler (for web apps)
        cache_path: Token cache file path (for CLI apps)
        requests_session: Custom requests session (if None, creates one with User-Agent)
    
    Returns:
        Configured SpotifyOAuth with User-Agent header
    """
    if requests_session is None:
        requests_session = create_spotify_session()

    # Build kwargs based on what's provided
    oauth_kwargs = {
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': redirect_uri,
        'scope': scope,
        'requests_session': requests_session
    }

    if state is not None:
        oauth_kwargs['state'] = state

    if cache_handler is not None:
        oauth_kwargs['cache_handler'] = cache_handler
    elif cache_path is not None:
        oauth_kwargs['cache_path'] = cache_path

    return SpotifyOAuth(**oauth_kwargs)
