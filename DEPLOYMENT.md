# Deployment Guide

## Prerequisites

- [Spotify Developer App](https://developer.spotify.com/dashboard) with Client ID and Client Secret
- [Render](https://render.com) account connected to your GitHub repository

## Environment Variables

```bash
SPOTIFY_CLIENT_ID=<your_client_id>
SPOTIFY_CLIENT_SECRET=<your_client_secret>
REDIRECT_URI=https://<your-app-name>.onrender.com/callback
FLASK_SECRET_KEY=<generate_with_script_below>
REDIS_URL=<internal_redis_url>
FLASK_ENV=production
HTTPS_ONLY=true
SESSION_TYPE=redis
RENDER=true
```

Generate a secret key:
```bash
python scripts/generate-secret-key.py
```

Validate your configuration:
```bash
python scripts/check-production-config.py
```

## Render Deployment

### 1. Create Redis Instance

**New > Redis** in Render Dashboard:
- **Name**: `playlist-manager-redis`
- **Plan**: Free (testing) or Starter (production, $7/month)
- **Maxmemory Policy**: `allkeys-lru`

Copy the **Internal Redis URL**.

### 2. Create Web Service

**New > Web Service** in Render Dashboard:
1. Connect your GitHub repository (Render auto-detects `render.yaml`)
2. Set the environment variables listed above
3. Create the service

### 3. Configure Spotify App

Add the redirect URI to your Spotify app:
```
https://<your-app-name>.onrender.com/callback
```

### 4. Verify

- Health check: `https://<your-app-name>.onrender.com/health`
- Readiness: `https://<your-app-name>.onrender.com/ready`
- Test the OAuth login flow

## Redis

Redis is used for session storage (2-hour timeout) and OAuth state storage (5-minute TTL). If Redis is unavailable, the app falls back to filesystem sessions and in-memory OAuth states.

**Alternative Redis providers**: Redis Cloud, Upstash, AWS ElastiCache — set `REDIS_URL` accordingly.

## Alternative Platforms

**Heroku**: `heroku addons:create heroku-redis:mini && git push heroku main`

**Docker**: `docker build -t playlist-manager . && docker run -p 5000:5000 --env-file .env playlist-manager`

**Self-hosted**: Use nginx as a reverse proxy for HTTPS, install Redis locally.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `INVALID_CLIENT: Invalid redirect URI` | Ensure `REDIRECT_URI` matches Spotify app settings exactly (check trailing slashes, HTTPS) |
| `redis.exceptions.ConnectionError` | Use the Internal Redis URL, verify the instance is running |
| `FLASK_SECRET_KEY must be set` | Set it in Render environment variables (32+ characters) |
| Users logged out after deploy | Verify `SESSION_TYPE=redis` and `REDIS_URL` are set correctly |

## Scaling

- **>25 users**: Apply for [Spotify Extended Quota Mode](https://developer.spotify.com/documentation/web-api/concepts/rate-limits)
- **High traffic**: Upgrade Redis plan, add web service instances

## Production Checklist

- [ ] Generate and set `FLASK_SECRET_KEY`
- [ ] Set all required environment variables
- [ ] Configure Spotify app redirect URI
- [ ] Test OAuth flow end-to-end
- [ ] Verify health endpoints
- [ ] Apply for Extended Quota Mode (if needed)
