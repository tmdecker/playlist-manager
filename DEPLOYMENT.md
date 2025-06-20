# Complete Deployment Guide

This comprehensive guide covers all aspects of deploying the Spotify Tools application to production, with a focus on Render deployment with Redis.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Quick Start](#quick-start)
3. [Environment Configuration](#environment-configuration)
4. [Render Deployment](#render-deployment)
5. [Redis Setup](#redis-setup)
6. [Security Configuration](#security-configuration)
7. [Health Monitoring](#health-monitoring)
8. [Troubleshooting](#troubleshooting)
9. [Scaling & Performance](#scaling--performance)
10. [Alternative Deployment Options](#alternative-deployment-options)

## Prerequisites

Before deploying, ensure you have:

1. **Spotify Developer Account**
   - Create app at [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard)
   - Note your Client ID and Client Secret
   - Required scopes: `playlist-modify-public`, `playlist-modify-private`, `playlist-read-private`, `user-read-email`

2. **Render Account** (for Render deployment)
   - Sign up at [render.com](https://render.com)
   - Connect your GitHub account

3. **GitHub Repository**
   - Code pushed to GitHub
   - Render will deploy from this repository

## Quick Start

### 1. Generate Secret Key
```bash
python scripts/generate-secret-key.py
# Save the generated key - you'll need it for environment variables
```

### 2. Validate Configuration
```bash
python scripts/check-production-config.py
```

### 3. Deploy to Render
1. Push code to GitHub
2. Create services in Render (Web + Redis)
3. Set environment variables
4. Deploy!

## Environment Configuration

### Required Environment Variables

```bash
# Spotify API Credentials (from Spotify Developer Dashboard)
SPOTIFY_CLIENT_ID=your_spotify_client_id_here
SPOTIFY_CLIENT_SECRET=your_spotify_client_secret_here

# OAuth Redirect URI - MUST match Spotify app settings exactly
REDIRECT_URI=https://your-app-name.onrender.com/callback

# Flask Secret Key - Generate with scripts/generate-secret-key.py
FLASK_SECRET_KEY=your_secure_64_character_hex_string_here

# Redis URL - From Render Redis or external service
REDIS_URL=redis://your-redis-url-here

# Production Settings (set automatically by render.yaml)
FLASK_ENV=production
HTTPS_ONLY=true
SESSION_TYPE=redis
RENDER=true
```

### Environment Files

- **`.env.example`** - Development environment template
- **`render.env.example`** - Render-specific environment template
- **`production.env.example`** - General production environment template

## Render Deployment

### Step 1: Create Redis Instance

1. In Render Dashboard: **New → Redis**
2. Configure:
   - **Name**: `playlist-manager-redis`
   - **Region**: Same as your web service
   - **Plan**: 
     - Free: Testing only (25MB, no persistence)
     - Starter: Production ($7/month, 512MB, persistence)
   - **Maxmemory Policy**: `allkeys-lru`
3. Create Redis instance
4. Copy the **Internal Redis URL**

### Step 2: Create Web Service

1. In Render Dashboard: **New → Web Service**
2. Connect your GitHub repository
3. Render will detect `render.yaml` automatically
4. Add environment variables:
   ```
   SPOTIFY_CLIENT_ID=<your_client_id>
   SPOTIFY_CLIENT_SECRET=<your_client_secret>
   REDIRECT_URI=https://<your-app-name>.onrender.com/callback
   FLASK_SECRET_KEY=<your_generated_key>
   REDIS_URL=<internal_redis_url_from_step_1>
   ```
5. Click **Create Web Service**

### Step 3: Configure Spotify App

1. Go to [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Select your app
3. Add redirect URI: `https://your-app-name.onrender.com/callback`
4. Save changes

### Step 4: Verify Deployment

1. Check health endpoint: `https://your-app.onrender.com/health`
2. Check readiness: `https://your-app.onrender.com/ready`
3. Test OAuth flow by logging in

## Redis Setup

### Option 1: Render Redis (Recommended)

Included in Render deployment steps above. Benefits:
- Easy setup
- Same region as web service
- Automatic internal networking
- Built-in monitoring

### Option 2: External Redis Services

#### Redis Cloud (Redis Labs)
```bash
# Connection format
REDIS_URL=redis://default:password@your-endpoint.redis.cloud:port

# With TLS
REDIS_URL=rediss://default:password@your-endpoint.redis.cloud:port
```

#### Upstash
```bash
# Upstash provides a connection URL
REDIS_URL=<copy_from_upstash_console>
```

#### AWS ElastiCache
```bash
REDIS_URL=redis://your-cluster.abc123.ng.0001.use1.cache.amazonaws.com:6379
```

### Redis Configuration

Redis is used for:
- **Session Storage**: User sessions with 2-hour timeout
- **OAuth State Storage**: Temporary OAuth states with 5-minute TTL

If Redis is unavailable, the app falls back to:
- Filesystem sessions (development)
- In-memory OAuth states

## Security Configuration

### HTTPS Enforcement

The application enforces HTTPS in production:
- Automatic HTTP → HTTPS redirect (301)
- Secure cookies (`Secure`, `HttpOnly`, `SameSite=Lax`)
- Security headers (HSTS, CSP, X-Frame-Options)

### Token Security

- **Encryption**: Fernet symmetric encryption for all tokens
- **Key Derivation**: PBKDF2 with 100,000 iterations
- **Session Storage**: Encrypted tokens in Redis
- **Automatic Cleanup**: Invalid tokens are cleaned up

### Secret Key Management

```bash
# Generate secure key
python scripts/generate-secret-key.py

# For extra security (512 bits)
python scripts/generate-secret-key.py --length 64
```

**Important**: 
- Never commit secret keys to Git
- Rotate keys quarterly
- Use different keys for different environments

## Health Monitoring

### Endpoints

- **`/health`** - Basic health check
  ```json
  {"status": "healthy", "timestamp": "2024-01-15 10:30:00.123456"}
  ```

- **`/ready`** - Readiness check (validates Redis)
  ```json
  {"status": "ready", "timestamp": "2024-01-15 10:30:00.123456"}
  ```

### What to Monitor

1. **Web Service Logs**
   - OAuth authentication flows
   - Rate limiting warnings
   - Error rates

2. **Redis Metrics**
   - Connection status
   - Memory usage
   - Hit/miss rates

3. **API Usage**
   - Monitor in Spotify Developer Dashboard
   - Watch for rate limit approaches

## Troubleshooting

### Common Issues

#### 1. OAuth Redirect Mismatch
**Error**: `INVALID_CLIENT: Invalid redirect URI`

**Solution**:
- Ensure `REDIRECT_URI` in Render matches Spotify app exactly
- Check for trailing slashes
- Verify HTTPS is used

#### 2. Redis Connection Failed
**Error**: `redis.exceptions.ConnectionError`

**Solution**:
- Use Internal Redis URL (not External)
- Verify Redis instance is running
- Check `REDIS_URL` format

#### 3. Secret Key Error
**Error**: `FLASK_SECRET_KEY environment variable must be set`

**Solution**:
- Set `FLASK_SECRET_KEY` in Render environment
- Ensure key is 32+ characters
- Don't use example keys

#### 4. Session Lost on Restart
**Issue**: Users logged out after deployment

**Solution**:
- Verify Redis is properly configured
- Check `SESSION_TYPE=redis`
- Ensure `REDIS_URL` is correct

### Debug Commands

```bash
# Test Redis connection
python -c "import redis, os; r = redis.from_url(os.getenv('REDIS_URL')); print(r.ping())"

# Validate configuration
python scripts/check-production-config.py --verbose

# Check environment variables
python scripts/check-production-config.py --env-file .env.production
```

## Scaling & Performance

### Current Limits

- **Development Mode**: 25 users maximum
- **Rate Limits**: ~180 requests/minute (3 req/sec)
- **Session Timeout**: 2 hours
- **OAuth State TTL**: 5 minutes

### Scaling Checklist

1. **For >25 Users**
   - Apply for Spotify Extended Quota Mode
   - Required before going live with more users

2. **For High Traffic**
   - Upgrade Redis plan (more memory)
   - Add more web service instances
   - Consider Redis Cluster

3. **Performance Optimization**
   - Enable Redis persistence for critical data
   - Use connection pooling (automatic)
   - Monitor response times

### Production Checklist

Before going live:

- [ ] Generate secure `FLASK_SECRET_KEY`
- [ ] Set all required environment variables
- [ ] Configure Spotify app redirect URI
- [ ] Test OAuth flow end-to-end
- [ ] Verify health endpoints work
- [ ] Monitor initial deployments
- [ ] Apply for Extended Quota Mode (if needed)
- [ ] Set up error tracking (optional)
- [ ] Configure backups (if using Redis persistence)
- [ ] Document rollback procedure

## Alternative Deployment Options

While this guide focuses on Render, the application supports other platforms:

### Heroku
```bash
# Use Heroku Redis
heroku addons:create heroku-redis:mini

# Deploy
git push heroku main
```

### AWS Elastic Beanstalk
- Use ElastiCache for Redis
- Configure load balancer for HTTPS
- Set environment variables in EB console

### Docker
```dockerfile
# Dockerfile included
docker build -t spotify-tools .
docker run -p 5000:5000 --env-file .env spotify-tools
```

### Self-Hosted
- Install Redis locally
- Use reverse proxy (nginx) for HTTPS
- Configure systemd for process management

## Best Practices

### Security
- ✅ Always use HTTPS in production
- ✅ Rotate secret keys quarterly
- ✅ Monitor for suspicious OAuth activity
- ✅ Use Redis password authentication
- ✅ Enable Redis TLS when available

### Reliability
- ✅ Set up monitoring and alerts
- ✅ Plan for Redis failover
- ✅ Document rollback procedures
- ✅ Test disaster recovery

### Performance
- ✅ Monitor API rate limits
- ✅ Use Redis connection pooling
- ✅ Set appropriate cache TTLs
- ✅ Profile slow operations

## Support Resources

- **Configuration Issues**: Run `python scripts/check-production-config.py`
- **Spotify API**: Check [developer.spotify.com](https://developer.spotify.com)
- **Render Support**: [render.com/docs](https://render.com/docs)
- **Redis Issues**: Check connection and memory usage

## Appendix: File Structure

```
spotify-tools/
├── render.yaml              # Render deployment configuration
├── DEPLOYMENT.md           # This file
├── .env.example            # Development environment template
├── render.env.example      # Render environment template
├── production.env.example  # Production environment template
├── scripts/
│   ├── generate-secret-key.py    # Secret key generator
│   └── check-production-config.py # Configuration validator
└── docs/
    └── (legacy deployment docs - refer to this file instead)
```

---

**Remember**: Never commit secrets to version control. Use environment variables for all sensitive configuration.