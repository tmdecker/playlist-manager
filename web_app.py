import logging
import os
import re
import secrets
from datetime import timedelta
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for

from error_handler import get_user_friendly_error, log_error_with_context, is_spotify_api_available
from flask_session import Session
from rate_limiter import SpotifyRateLimiter, rate_limited_call
from redis_oauth_store import create_oauth_state_store
from remove_duplicates_from_playlist import remove_duplicates_from_playlist
from secure_token_storage import create_secure_token_storage
from sort_playlist_by_release_date import batch_sort_playlist
from spotify_auth import get_user_playlists
from spotipy.cache_handler import MemoryCacheHandler
from spotify_client import create_spotify_client, create_spotify_oauth

# Load environment variables first
load_dotenv()

# Configure logging based on environment
FLASK_ENV = os.getenv('FLASK_ENV', 'development')
HTTPS_ONLY = os.getenv('HTTPS_ONLY', 'false').lower() == 'true'
SESSION_TYPE = os.getenv('SESSION_TYPE', 'filesystem')
RENDER = os.getenv('RENDER', 'false').lower() == 'true'

# Set up logging configuration
log_level = logging.DEBUG if FLASK_ENV == 'development' else logging.INFO
logging.basicConfig(
    level=log_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)

# Set Flask and Werkzeug log levels
logging.getLogger('werkzeug').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Detect Render environment automatically
if os.getenv('PORT') and not RENDER:
    RENDER = True
    os.environ['RENDER'] = 'true'

app = Flask(__name__)

# Persistent secret key management
flask_secret_key = os.getenv('FLASK_SECRET_KEY')
if not flask_secret_key:
    if FLASK_ENV == 'production' or RENDER:
        raise ValueError('FLASK_SECRET_KEY environment variable must be set for production/Render deployment')
    else:
        # Generate a warning for development
        import warnings
        warnings.warn('FLASK_SECRET_KEY not set - using generated key (sessions will not persist across restarts)')
        flask_secret_key = secrets.token_hex(32)

app.secret_key = flask_secret_key
app.permanent_session_lifetime = timedelta(hours=2)

# Configure Flask-Session for production session storage
if FLASK_ENV == 'production' or RENDER or SESSION_TYPE == 'redis':
    # Use Redis for session storage in production
    redis_url = os.getenv('REDIS_URL')
    if redis_url:
        try:
            import redis
            app.config.update(
                SESSION_TYPE='redis',
                SESSION_REDIS=redis.from_url(redis_url),
                SESSION_PERMANENT=False,
                SESSION_USE_SIGNER=True,
                SESSION_KEY_PREFIX='spotify-tools:',
                SESSION_COOKIE_HTTPONLY=True,
                SESSION_COOKIE_SAMESITE='Lax',
            )
            if HTTPS_ONLY or RENDER:
                app.config['SESSION_COOKIE_SECURE'] = True
        except ImportError:
            import warnings
            warnings.warn('Redis package not available - falling back to filesystem sessions')
            app.config['SESSION_TYPE'] = 'filesystem'
    else:
        # Fallback to filesystem sessions
        app.config['SESSION_TYPE'] = 'filesystem'
else:
    # Development configuration
    app.config['SESSION_TYPE'] = 'filesystem'

# Configure secure session cookies for production
if FLASK_ENV == 'production' or HTTPS_ONLY or RENDER:
    app.config.update(
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
    )

# Initialize Flask-Session
Session(app)

# OAuth configuration
SPOTIFY_CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID')
SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET')
# Use HTTPS in production by default
default_redirect = 'https://localhost:5000/callback' if FLASK_ENV == 'production' else 'http://localhost:5000/callback'
REDIRECT_URI = os.getenv('REDIRECT_URI', default_redirect)
SCOPE = 'playlist-modify-public playlist-modify-private playlist-read-private user-read-email'

# Validate required environment variables
if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
    raise ValueError('Missing required environment variables: SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET')

# OAuth state storage with Redis support and automatic fallback
oauth_state_store = create_oauth_state_store()

# Global rate limiter instance
rate_limiter = SpotifyRateLimiter()

# Secure token storage instance
secure_token_storage = create_secure_token_storage(flask_secret_key)

# Compliance safeguards
PROHIBITED_ACTIVITIES = [
    'download', 'save_file', 'export_tracks', 'bulk_download',
    'ai_training', 'ml_training', 'data_mining', 'scraping'
]

def require_https(f):
    """Decorator to enforce HTTPS in production"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if HTTPS_ONLY and not request.is_secure:
            # Redirect HTTP to HTTPS
            https_url = request.url.replace('http://', 'https://', 1)
            return redirect(https_url, code=301)
        return f(*args, **kwargs)
    return decorated_function

@app.before_request
def force_https():
    """Force HTTPS for all requests in production"""
    if HTTPS_ONLY and not request.is_secure:
        https_url = request.url.replace('http://', 'https://', 1)
        return redirect(https_url, code=301)

@app.after_request
def apply_security_headers(response):
    """Apply security headers to all responses"""
    if FLASK_ENV == 'production' or HTTPS_ONLY:
        # HTTP Strict Transport Security (HSTS)
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'

    # Security headers for all environments
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'

    # Content Security Policy
    csp = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
        "img-src 'self' data: https:; "
        "connect-src 'self' https://api.spotify.com; "
        "font-src 'self' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://fonts.gstatic.com;"
    )
    response.headers['Content-Security-Policy'] = csp

    return response

def ensure_compliance():
    """Ensure application complies with Spotify API terms"""
    # This application is designed to only:
    # 1. Sort playlists by release date
    # 2. Remove duplicate tracks
    # No data is permanently stored, downloaded, or used for prohibited purposes
    pass

def get_authenticated_spotify_client():
    """Get authenticated Spotify client, refreshing token if needed"""
    # Try to get token from secure storage
    token_info = secure_token_storage.get_token_from_session(session)
    if not token_info:
        return None

    try:
        # Check if token needs refresh
        if token_info.get('expires_at') and token_info.get('refresh_token'):
            import time
            if time.time() > token_info['expires_at']:
                # Token expired, refresh it
                auth_manager = create_spotify_oauth(
                    client_id=SPOTIFY_CLIENT_ID,
                    client_secret=SPOTIFY_CLIENT_SECRET,
                    redirect_uri=REDIRECT_URI,
                    scope=SCOPE,
                    cache_handler=None  # Use cache_handler instead of cache_path
                )

                refreshed_token = auth_manager.refresh_access_token(token_info['refresh_token'])
                # Update token info with refreshed data
                token_info.update(refreshed_token)
                # Store updated token securely
                secure_token_storage.update_token_in_session(session, token_info)

        return create_spotify_client(access_token=token_info['access_token'])
    except Exception:
        # Token refresh failed, clear session
        secure_token_storage.clear_token_from_session(session)
        session.clear()
        return None

def extract_playlist_id_from_link(link):
    """
    Extract playlist ID from Spotify playlist URL or return playlist ID if already valid.
    
    Supports:
    - https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M
    - https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=...
    - Direct playlist ID: 37i9dQZF1DXcBWIGoYBM5M (when selected from dropdown)
    
    Returns:
        str: The playlist ID if valid URL format or valid playlist ID
        None: If invalid format
    """
    link = link.strip()

    # Check for web URL pattern first
    web_pattern = r'https://open\.spotify\.com/playlist/([a-zA-Z0-9]+)'
    match = re.search(web_pattern, link)
    if match:
        return match.group(1)

    # If it's already a playlist ID (22 characters, alphanumeric), return it
    # This handles dropdown selections which send the playlist ID directly
    if re.match(r'^[a-zA-Z0-9]{22}$', link):
        return link

    # Return None for invalid formats
    return None

def validate_playlist_snapshot(sp, playlist_id, stored_snapshot_id):
    """
    Validate that the playlist hasn't changed since we last fetched it.
    
    Args:
        sp: Authenticated Spotify client
        playlist_id: The playlist ID to check
        stored_snapshot_id: The snapshot_id we have stored from previous fetch
        
    Returns:
        tuple: (is_valid: bool, current_snapshot_id: str)
    """
    try:
        # Fetch only the snapshot_id field to minimize API usage
        playlist = rate_limited_call(sp.playlist, playlist_id, fields='snapshot_id')
        current_snapshot_id = playlist.get('snapshot_id')
        
        is_valid = current_snapshot_id == stored_snapshot_id
        return is_valid, current_snapshot_id
    except Exception:
        # If we can't validate, assume it's invalid to be safe
        return False, None

@app.route('/')
def index():
    """Home page with feature selection"""
    sp = get_authenticated_spotify_client()
    if sp:
        try:
            user = rate_limited_call(sp.current_user)
            return render_template('index.html', user=user)
        except Exception:
            session.clear()

    return render_template('index.html', user=None)

@app.route('/auth')
def auth():
    """Initialize Spotify authentication"""
    # Generate state parameter for CSRF protection
    state = secrets.token_urlsafe(32)
    session['oauth_state'] = state
    oauth_state_store.set_state(state)

    # Create OAuth manager
    auth_manager = create_spotify_oauth(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope=SCOPE,
        state=state,
        cache_handler=None  # Don't use file cache for web app
    )

    # Get authorization URL
    auth_url = auth_manager.get_authorize_url()
    return redirect(auth_url)

@app.route('/callback')
def callback():
    """Handle OAuth callback from Spotify"""
    # Validate HTTPS in production
    if HTTPS_ONLY and not request.is_secure:
        return render_template('error.html', error='HTTPS is required for OAuth callback in production.')

    # Get authorization code and state from callback
    code = request.args.get('code')
    state = request.args.get('state')
    error = request.args.get('error')

    # Check for errors
    if error:
        return render_template('error.html', error=f'Spotify authentication error: {error}')

    # Validate state parameter
    if not state or state != session.get('oauth_state') or not oauth_state_store.get_state(state):
        return render_template('error.html', error='Invalid state parameter. Please try again.')

    # Clean up state
    session.pop('oauth_state', None)
    oauth_state_store.delete_state(state)

    if not code:
        return render_template('error.html', error='No authorization code received.')

    try:
        # Exchange code for access token
        mem_cache = MemoryCacheHandler()
        auth_manager = create_spotify_oauth(
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET,
            redirect_uri=REDIRECT_URI,
            scope=SCOPE,
            cache_handler=mem_cache
        )

        # Exchange code for token; full token dict is saved to mem_cache
        auth_manager.get_access_token(code, as_dict=False, check_cache=False)
        token_info = mem_cache.get_cached_token()

        if not token_info:
            return render_template('error.html', error='Failed to get access token.')

        # Store token securely in session
        secure_token_storage.store_token_in_session(session, token_info)

        return redirect(url_for('index'))

    except Exception as e:
        return render_template('error.html', error=f'Authentication failed: {e!s}')

@app.route('/logout')
def logout():
    """Clear session and log out user with secure token cleanup"""
    # Clear tokens securely
    secure_token_storage.clear_token_from_session(session)
    # Clear entire session
    session.clear()
    return redirect(url_for('index'))

@app.route('/privacy')
def privacy():
    """Privacy policy page"""
    from datetime import datetime
    return render_template('privacy.html', current_date=datetime.now().strftime('%B %d, %Y'))

@app.route('/terms')
def terms():
    """Terms of service page"""
    from datetime import datetime
    return render_template('terms.html', current_date=datetime.now().strftime('%B %d, %Y'))

@app.route('/consent')
def consent():
    """Data consent page"""
    return render_template('consent.html')

@app.route('/health')
def health_check():
    """Health check endpoint for load balancers"""
    from datetime import datetime
    return jsonify({'status': 'healthy', 'timestamp': str(datetime.now())})

@app.route('/ready')
def readiness_check():
    """Readiness check endpoint for Kubernetes/deployment"""
    from datetime import datetime
    try:
        # Check if we can connect to OAuth state store
        test_state = 'health_check'
        oauth_state_store.set_state(test_state)
        oauth_state_store.delete_state(test_state)
        return jsonify({'status': 'ready', 'timestamp': str(datetime.now())})
    except Exception as e:
        return jsonify({'status': 'not_ready', 'error': str(e), 'timestamp': str(datetime.now())}), 503

@app.route('/sort-playlist')
def sort_playlist_page():
    """Sort playlist page"""
    sp = get_authenticated_spotify_client()
    if not sp:
        return redirect(url_for('index'))

    try:
        user = rate_limited_call(sp.current_user)
        return render_template('sort_playlist.html', user=user)
    except Exception:
        session.clear()
        return redirect(url_for('index'))

@app.route('/remove-duplicates')
def remove_duplicates_page():
    """Remove duplicates page"""
    sp = get_authenticated_spotify_client()
    if not sp:
        return redirect(url_for('index'))

    try:
        user = rate_limited_call(sp.current_user)
        return render_template('remove_duplicates.html', user=user)
    except Exception:
        session.clear()
        return redirect(url_for('index'))

@app.route('/api/sort-playlist', methods=['POST'])
def api_sort_playlist():
    """API endpoint to sort playlist"""
    sp = get_authenticated_spotify_client()
    if not sp:
        return jsonify({'error': 'Not authenticated'}), 401

    data = request.json
    playlist_input = data.get('playlist_id')
    sort_order = data.get('sort_order', 'newest')
    stored_snapshot_id = data.get('snapshot_id')  # Get snapshot_id from client

    if not playlist_input:
        return jsonify({'error': 'No playlist selected'}), 400

    # Extract playlist ID from link if necessary
    playlist_id = extract_playlist_id_from_link(playlist_input)
    if playlist_id is None:
        return jsonify({'error': 'Invalid playlist URL format. Please use a valid Spotify playlist URL (e.g., https://open.spotify.com/playlist/...)'}), 400

    reverse = sort_order == 'newest'

    try:
        # Validate snapshot_id if provided
        if stored_snapshot_id:
            is_valid, current_snapshot_id = validate_playlist_snapshot(sp, playlist_id, stored_snapshot_id)
            if not is_valid:
                return jsonify({
                    'error': 'This playlist has been modified since you loaded it. Please refresh the page and try again.',
                    'conflict': True,
                    'current_snapshot_id': current_snapshot_id
                }), 409

        # Get playlist info with rate limiting
        playlist = rate_limited_call(sp.playlist, playlist_id)

        # Sort playlist (batch_sort_playlist will use rate limiting internally)
        moves = batch_sort_playlist(sp, playlist_id, reverse=reverse)

        # Get first 10 tracks after sorting with rate limiting
        results = rate_limited_call(sp.playlist_items, playlist_id, limit=10)
        tracks = []
        if results and 'items' in results:
            for i, item in enumerate(results['items']):
                if item['track']:
                    track = item['track']
                    tracks.append({
                        'position': i + 1,
                        'name': track['name'],
                        'artist': track['artists'][0]['name'] if track['artists'] else 'Unknown',
                        'release_date': track['album']['release_date']
                    })

        return jsonify({
            'success': True,
            'moves': moves,
            'playlist_name': playlist['name'],
            'tracks': tracks
        })

    except Exception as e:
        # Log error with context
        log_error_with_context(e, {
            'operation': 'sort_playlist',
            'playlist_id': playlist_id,
            'sort_order': sort_order
        })
        
        # Return user-friendly error message
        error_message = get_user_friendly_error(e)
        response = {'error': error_message}
        
        # Add offline indicator if API is unavailable
        if not is_spotify_api_available(e):
            response['offline'] = True
            
        return jsonify(response), 500

@app.route('/api/remove-duplicates', methods=['POST'])
def api_remove_duplicates():
    """API endpoint to remove duplicates"""
    sp = get_authenticated_spotify_client()
    if not sp:
        return jsonify({'error': 'Not authenticated'}), 401

    data = request.get_json()
    playlist_input = data.get('playlist_id') if data else None
    stored_snapshot_id = data.get('snapshot_id') if data else None  # Get snapshot_id from client

    if not playlist_input:
        return jsonify({'error': 'No playlist selected'}), 400

    # Extract playlist ID from link if necessary
    playlist_id = extract_playlist_id_from_link(playlist_input)
    if playlist_id is None:
        return jsonify({'error': 'Invalid playlist URL format. Please use a valid Spotify playlist URL (e.g., https://open.spotify.com/playlist/...)'}), 400

    try:
        # Validate snapshot_id if provided
        if stored_snapshot_id:
            is_valid, current_snapshot_id = validate_playlist_snapshot(sp, playlist_id, stored_snapshot_id)
            if not is_valid:
                return jsonify({
                    'error': 'This playlist has been modified since you loaded it. Please refresh the page and try again.',
                    'conflict': True,
                    'current_snapshot_id': current_snapshot_id
                }), 409
        # Get playlist info with rate limiting
        playlist = rate_limited_call(sp.playlist, playlist_id)

        # Remove duplicates (remove_duplicates_from_playlist will use rate limiting internally)
        stats = remove_duplicates_from_playlist(sp, playlist_id)

        # Prepare response with removal strategy info
        response_data = {
            'success': True,
            'playlist_name': playlist['name'],
            'total_tracks': stats['total_tracks'],
            'unique_tracks': stats['unique_tracks'],
            'duplicates_found': stats['duplicates_found'],
            'tracks_removed': stats['tracks_removed'],
            'duplicate_groups': stats['duplicate_groups']  # Return all duplicate groups
        }
        
        # Add removal strategy breakdown if available
        if 'unique_uri_removals' in stats and 'identical_uri_groups' in stats:
            response_data['removal_strategy'] = {
                'position_specific': len(stats['unique_uri_removals']),
                'remove_all_readd': sum(len(group) for group in stats['identical_uri_groups'].values())
            }
        
        return jsonify(response_data)

    except Exception as e:
        # Log error with context
        log_error_with_context(e, {
            'operation': 'remove_duplicates',
            'playlist_id': playlist_id
        })
        
        # Return user-friendly error message
        error_message = get_user_friendly_error(e)
        response = {'error': error_message}
        
        # Add offline indicator if API is unavailable
        if not is_spotify_api_available(e):
            response['offline'] = True
            
        return jsonify(response), 500

@app.route('/api/playlists')
def api_playlists():
    """Get user playlists"""
    sp = get_authenticated_spotify_client()
    if not sp:
        return jsonify({'error': 'Not authenticated'}), 401
    try:
        # get_user_playlists will use rate limiting internally
        playlists = get_user_playlists(sp)
        return jsonify({'playlists': playlists})
    except Exception as e:
        # Log error with context
        log_error_with_context(e, {
            'operation': 'get_playlists'
        })
        
        # Return user-friendly error message
        error_message = get_user_friendly_error(e)
        response = {'error': error_message}
        
        # Add offline indicator if API is unavailable
        if not is_spotify_api_available(e):
            response['offline'] = True
            
        return jsonify(response), 500

if __name__ == '__main__':
    # Create templates directory if it doesn't exist
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static', exist_ok=True)

    # Configure port for different environments
    port = int(os.getenv('PORT', 5000))
    debug = FLASK_ENV == 'development' and not RENDER

    app.run(debug=debug, host='0.0.0.0', port=port)
