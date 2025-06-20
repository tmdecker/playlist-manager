#!/usr/bin/env python3
"""
Generate a secure secret key for Flask production deployment.

This script generates cryptographically secure random keys suitable for:
- FLASK_SECRET_KEY: Used for session signing and token encryption
- General purpose secret keys

Usage:
    python scripts/generate-secret-key.py
    python scripts/generate-secret-key.py --length 64
    python scripts/generate-secret-key.py --format base64
"""

import argparse
import secrets
import base64
import string
import sys


def generate_hex_key(length: int = 32) -> str:
    """Generate a hex-encoded secret key.
    
    Args:
        length: Number of bytes (default 32 = 64 hex characters)
    
    Returns:
        Hex-encoded secret key
    """
    return secrets.token_hex(length)


def generate_urlsafe_key(length: int = 32) -> str:
    """Generate a URL-safe base64-encoded secret key.
    
    Args:
        length: Number of bytes
    
    Returns:
        URL-safe base64-encoded secret key
    """
    return secrets.token_urlsafe(length)


def generate_base64_key(length: int = 32) -> str:
    """Generate a standard base64-encoded secret key.
    
    Args:
        length: Number of bytes
    
    Returns:
        Base64-encoded secret key
    """
    return base64.b64encode(secrets.token_bytes(length)).decode('ascii')


def generate_alphanumeric_key(length: int = 64) -> str:
    """Generate an alphanumeric secret key.
    
    Args:
        length: Number of characters
    
    Returns:
        Alphanumeric secret key
    """
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def main():
    parser = argparse.ArgumentParser(
        description='Generate secure secret keys for Flask production deployment',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate default hex key (recommended for FLASK_SECRET_KEY)
  %(prog)s
  
  # Generate longer hex key
  %(prog)s --length 64
  
  # Generate base64 key
  %(prog)s --format base64
  
  # Generate multiple keys
  %(prog)s --count 3
  
Security Notes:
  - Default generates 32 bytes = 64 hex characters (256 bits of entropy)
  - Recommended minimum: 32 bytes (256 bits)
  - For extra security: 64 bytes (512 bits)
  - NEVER reuse keys across different applications
  - NEVER commit keys to version control
  - Rotate keys periodically (quarterly recommended)
        """
    )
    
    parser.add_argument(
        '--length', '-l',
        type=int,
        default=32,
        help='Key length in bytes (default: 32)'
    )
    
    parser.add_argument(
        '--format', '-f',
        choices=['hex', 'base64', 'urlsafe', 'alphanumeric'],
        default='hex',
        help='Output format (default: hex)'
    )
    
    parser.add_argument(
        '--count', '-c',
        type=int,
        default=1,
        help='Number of keys to generate (default: 1)'
    )
    
    parser.add_argument(
        '--env', '-e',
        action='store_true',
        help='Output in .env format'
    )
    
    args = parser.parse_args()
    
    # Validate length
    if args.length < 16:
        print("Warning: Key length should be at least 16 bytes (128 bits) for security", file=sys.stderr)
    
    if args.length < 32 and args.format == 'alphanumeric':
        # For alphanumeric, length is character count, not bytes
        args.length = 64  # Default to 64 characters for alphanumeric
    
    # Generate keys
    for i in range(args.count):
        if args.format == 'hex':
            key = generate_hex_key(args.length)
        elif args.format == 'base64':
            key = generate_base64_key(args.length)
        elif args.format == 'urlsafe':
            key = generate_urlsafe_key(args.length)
        elif args.format == 'alphanumeric':
            key = generate_alphanumeric_key(args.length)
        
        if args.env:
            print(f"FLASK_SECRET_KEY={key}")
        else:
            if args.count > 1:
                print(f"Key {i + 1}: {key}")
            else:
                print(key)
        
        if i == 0 and not args.env:
            print()
            if args.format == 'hex':
                print(f"Length: {args.length} bytes ({args.length * 2} hex characters, {args.length * 8} bits)")
            elif args.format == 'alphanumeric':
                print(f"Length: {args.length} characters")
            else:
                print(f"Length: {args.length} bytes ({args.length * 8} bits)")
            print(f"Format: {args.format}")
            
            if args.count == 1:
                print("\nTo use this key:")
                print("1. Copy the key above")
                print("2. Set it in your Render dashboard as FLASK_SECRET_KEY")
                print("3. Never share or commit this key")
                print("\nFor .env format, use: python scripts/generate-secret-key.py --env")


if __name__ == '__main__':
    main()