import os

import spotipy

from rate_limiter import rate_limited_call
from spotify_client import create_spotify_client, create_spotify_oauth


def get_spotify_client(
    client_id: str | None = None,
    client_secret: str | None = None,
    redirect_uri: str | None = None,
    scope: str = "playlist-modify-public playlist-modify-private playlist-read-private user-read-email",
    cache_path: str = ".cache",
) -> spotipy.Spotify:
    """
    Create and return an authenticated Spotify client.

    Args:
        client_id: Spotify app client ID. If None, uses SPOTIFY_CLIENT_ID env var.
        client_secret: Spotify app client secret. If None, uses SPOTIFY_CLIENT_SECRET env var.
        redirect_uri: OAuth redirect URI (default: http://localhost:8888/callback)
        scope: Space-separated list of Spotify scopes
        cache_path: Path to cache token file

    Returns:
        Authenticated Spotipy client instance

    Raises:
        ValueError: If client_id or client_secret are not provided or found in env vars
    """
    # Get credentials from parameters or environment variables
    if client_id is None:
        client_id = os.getenv("SPOTIFY_CLIENT_ID")
        if not client_id:
            raise ValueError(
                "client_id must be provided or set as SPOTIFY_CLIENT_ID environment variable"
            )

    if client_secret is None:
        client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
        if not client_secret:
            raise ValueError(
                "client_secret must be provided or set as SPOTIFY_CLIENT_SECRET environment variable"
            )

    if redirect_uri is None:
        redirect_uri = os.getenv("REDIRECT_URI", "http://localhost:8888/callback")

    # Create auth manager
    auth_manager = create_spotify_oauth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope=scope,
        cache_path=cache_path,
    )

    # Create and return Spotify client
    return create_spotify_client(auth_manager=auth_manager)


def get_user_playlists(sp: spotipy.Spotify) -> list:
    """
    Get all playlists owned by the authenticated user.

    Args:
        sp: Authenticated Spotipy client

    Returns:
        List of playlist dictionaries owned by the user
    """
    playlists = []
    results = rate_limited_call(sp.current_user_playlists, limit=50)

    # Get current user's ID to filter owned playlists
    current_user = rate_limited_call(sp.current_user)
    user_id = current_user["id"]

    # Filter for user-owned playlists only
    owned_playlists = [p for p in results["items"] if p["owner"]["id"] == user_id]
    playlists.extend(owned_playlists)

    while results["next"]:
        results = rate_limited_call(sp.next, results)
        owned_playlists = [p for p in results["items"] if p["owner"]["id"] == user_id]
        playlists.extend(owned_playlists)

    return playlists


def get_playlist_by_name(sp: spotipy.Spotify, playlist_name: str) -> dict | None:
    """
    Get a playlist by name for the authenticated user.

    Args:
        sp: Authenticated Spotipy client
        playlist_name: Name of the playlist to find

    Returns:
        Playlist dictionary if found, None otherwise
    """
    playlists = get_user_playlists(sp)

    for playlist in playlists:
        if playlist["name"] == playlist_name:
            return playlist

    return None
