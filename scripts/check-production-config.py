#!/usr/bin/env python3
"""
Validate production configuration for Spotify Tools deployment.

This script checks:
- Required environment variables are set
- Configuration values are valid
- Security settings are properly configured
- Redis connectivity (if configured)
- Spotify API credentials

Usage:
    python scripts/check-production-config.py
    python scripts/check-production-config.py --env-file .env.production
"""

import os
import sys
import argparse
import re
import urllib.parse
from typing import Dict, List, Tuple, Optional

# Try to import dependencies
try:
    from dotenv import load_dotenv
    HAS_DOTENV = True
except ImportError:
    HAS_DOTENV = False

try:
    import redis
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False


class ConfigValidator:
    """Validate production configuration."""
    
    def __init__(self, env_file: Optional[str] = None):
        self.env_file = env_file
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.info: List[str] = []
        
        if env_file and HAS_DOTENV:
            load_dotenv(env_file)
    
    def check_required_vars(self) -> None:
        """Check that all required environment variables are set."""
        required_vars = {
            'SPOTIFY_CLIENT_ID': 'Spotify App Client ID',
            'SPOTIFY_CLIENT_SECRET': 'Spotify App Client Secret',
            'REDIRECT_URI': 'OAuth Redirect URI',
            'FLASK_SECRET_KEY': 'Flask Secret Key for sessions',
        }
        
        for var, description in required_vars.items():
            value = os.getenv(var)
            if not value:
                self.errors.append(f"Missing required: {var} - {description}")
            elif var == 'FLASK_SECRET_KEY' and len(value) < 32:
                self.errors.append(f"{var} is too short (min 32 chars, got {len(value)})")
    
    def check_production_settings(self) -> None:
        """Check production-specific settings."""
        flask_env = os.getenv('FLASK_ENV', 'development')
        
        if flask_env != 'production':
            self.warnings.append(f"FLASK_ENV is '{flask_env}', should be 'production'")
        
        https_only = os.getenv('HTTPS_ONLY', 'false').lower()
        if https_only not in ('true', '1', 'yes', 'on'):
            self.warnings.append("HTTPS_ONLY should be 'true' in production")
        
        # Check redirect URI uses HTTPS
        redirect_uri = os.getenv('REDIRECT_URI', '')
        if redirect_uri and not redirect_uri.startswith('https://'):
            self.errors.append(f"REDIRECT_URI must use HTTPS in production: {redirect_uri}")
    
    def check_spotify_config(self) -> None:
        """Validate Spotify configuration."""
        client_id = os.getenv('SPOTIFY_CLIENT_ID', '')
        client_secret = os.getenv('SPOTIFY_CLIENT_SECRET', '')
        
        # Basic format validation
        if client_id and not re.match(r'^[a-f0-9]{32}$', client_id):
            self.warnings.append(f"SPOTIFY_CLIENT_ID format looks incorrect (expected 32 hex chars)")
        
        if client_secret and not re.match(r'^[a-f0-9]{32}$', client_secret):
            self.warnings.append(f"SPOTIFY_CLIENT_SECRET format looks incorrect (expected 32 hex chars)")
        
        # Check redirect URI format
        redirect_uri = os.getenv('REDIRECT_URI', '')
        if redirect_uri:
            try:
                parsed = urllib.parse.urlparse(redirect_uri)
                if not parsed.scheme or not parsed.netloc:
                    self.errors.append(f"Invalid REDIRECT_URI format: {redirect_uri}")
                elif not parsed.path.endswith('/callback'):
                    self.warnings.append(f"REDIRECT_URI should end with '/callback': {redirect_uri}")
            except Exception as e:
                self.errors.append(f"Cannot parse REDIRECT_URI: {e}")
    
    def check_redis_config(self) -> None:
        """Check Redis configuration and connectivity."""
        session_type = os.getenv('SESSION_TYPE', 'filesystem')
        redis_url = os.getenv('REDIS_URL', '')
        
        if session_type == 'redis':
            if not redis_url:
                self.errors.append("SESSION_TYPE is 'redis' but REDIS_URL is not set")
                return
            
            # Validate Redis URL format
            try:
                parsed = urllib.parse.urlparse(redis_url)
                if parsed.scheme not in ('redis', 'rediss'):
                    self.errors.append(f"Invalid Redis URL scheme: {parsed.scheme}")
                
                if not HAS_REDIS:
                    self.warnings.append("Redis package not installed - cannot test connection")
                else:
                    # Try to connect
                    try:
                        r = redis.from_url(redis_url, socket_connect_timeout=5)
                        r.ping()
                        self.info.append(f"✓ Redis connection successful: {parsed.hostname}:{parsed.port or 6379}")
                    except redis.ConnectionError as e:
                        self.errors.append(f"Redis connection failed: {e}")
                    except redis.AuthenticationError as e:
                        self.errors.append(f"Redis authentication failed: {e}")
                    except Exception as e:
                        self.errors.append(f"Redis error: {e}")
            except Exception as e:
                self.errors.append(f"Invalid REDIS_URL format: {e}")
        else:
            if redis_url:
                self.info.append(f"REDIS_URL is set but SESSION_TYPE is '{session_type}' (not using Redis)")
            else:
                self.warnings.append("Not using Redis for sessions (single instance only)")
    
    def check_render_specific(self) -> None:
        """Check Render-specific configuration."""
        is_render = os.getenv('RENDER', '').lower() in ('true', '1', 'yes', 'on')
        port = os.getenv('PORT')
        
        if is_render:
            self.info.append("✓ Render environment detected")
            if not port:
                self.warnings.append("RENDER is true but PORT is not set")
        elif port:
            self.info.append("PORT is set - might be running on Render")
    
    def check_security_headers(self) -> None:
        """Check security-related configuration."""
        # Check session configuration
        cookie_secure = os.getenv('SESSION_COOKIE_SECURE', '').lower()
        cookie_httponly = os.getenv('SESSION_COOKIE_HTTPONLY', '').lower()
        cookie_samesite = os.getenv('SESSION_COOKIE_SAMESITE', '')
        
        if cookie_secure and cookie_secure not in ('true', '1', 'yes', 'on'):
            self.warnings.append("SESSION_COOKIE_SECURE should be 'true' in production")
        
        if cookie_httponly and cookie_httponly not in ('true', '1', 'yes', 'on'):
            self.warnings.append("SESSION_COOKIE_HTTPONLY should be 'true' in production")
        
        if cookie_samesite and cookie_samesite not in ('Strict', 'Lax', 'None'):
            self.warnings.append(f"Invalid SESSION_COOKIE_SAMESITE value: {cookie_samesite}")
    
    def run_all_checks(self) -> Tuple[List[str], List[str], List[str]]:
        """Run all validation checks."""
        self.check_required_vars()
        self.check_production_settings()
        self.check_spotify_config()
        self.check_redis_config()
        self.check_render_specific()
        self.check_security_headers()
        
        return self.errors, self.warnings, self.info
    
    def print_results(self) -> bool:
        """Print validation results. Returns True if config is valid."""
        print("=" * 60)
        print("Production Configuration Validation")
        print("=" * 60)
        
        if self.env_file:
            print(f"Environment file: {self.env_file}")
        else:
            print("Using current environment variables")
        print()
        
        # Print info
        if self.info:
            print("ℹ️  Information:")
            for msg in self.info:
                print(f"   {msg}")
            print()
        
        # Print warnings
        if self.warnings:
            print("⚠️  Warnings:")
            for msg in self.warnings:
                print(f"   {msg}")
            print()
        
        # Print errors
        if self.errors:
            print("❌ Errors:")
            for msg in self.errors:
                print(f"   {msg}")
            print()
            print("❌ Configuration is NOT ready for production!")
            return False
        else:
            print("✅ Configuration is ready for production!")
            print()
            print("Next steps:")
            print("1. Set these environment variables in Render dashboard")
            print("2. Deploy your application")
            print("3. Test OAuth flow with production redirect URI")
            print("4. Monitor logs for any issues")
            return True


def main():
    parser = argparse.ArgumentParser(
        description='Validate production configuration for Spotify Tools',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Check current environment
  %(prog)s
  
  # Check specific env file
  %(prog)s --env-file .env.production
  
  # Check with verbose output
  %(prog)s --verbose

Exit codes:
  0 - Configuration is valid
  1 - Configuration has errors
  2 - Missing dependencies
        """
    )
    
    parser.add_argument(
        '--env-file', '-e',
        help='Path to environment file to validate'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show verbose output'
    )
    
    args = parser.parse_args()
    
    # Check dependencies
    if args.env_file and not HAS_DOTENV:
        print("Error: python-dotenv not installed. Install with: pip install python-dotenv")
        sys.exit(2)
    
    # Run validation
    validator = ConfigValidator(args.env_file)
    errors, warnings, info = validator.run_all_checks()
    
    if args.verbose:
        print("\nEnvironment Variables:")
        for var in ['SPOTIFY_CLIENT_ID', 'REDIRECT_URI', 'FLASK_ENV', 'SESSION_TYPE', 'REDIS_URL']:
            value = os.getenv(var)
            if value:
                if var in ['SPOTIFY_CLIENT_SECRET', 'FLASK_SECRET_KEY']:
                    print(f"  {var}: [REDACTED]")
                elif var == 'REDIS_URL' and '@' in value:
                    # Redact password in Redis URL
                    parsed = urllib.parse.urlparse(value)
                    if parsed.password:
                        safe_url = value.replace(f":{parsed.password}@", ":****@")
                        print(f"  {var}: {safe_url}")
                    else:
                        print(f"  {var}: {value}")
                else:
                    print(f"  {var}: {value}")
            else:
                print(f"  {var}: [NOT SET]")
        print()
    
    # Print results and exit
    is_valid = validator.print_results()
    sys.exit(0 if is_valid else 1)


if __name__ == '__main__':
    main()