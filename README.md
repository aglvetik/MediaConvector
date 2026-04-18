# TikTok and Music Telegram Bot

Production-oriented Telegram bot for Python 3.11 that:

- auto-detects TikTok links in chat messages
- downloads TikTok video and extracts separate audio
- searches music by text triggers: `найти`, `трек`, `песня`
- sends music as Telegram audio with metadata when available
- caches Telegram `file_id` values in SQLite

The project keeps a layered architecture and is designed for a small Ubuntu VPS.

## What The Bot Does

User-facing flows:

- TikTok:
  send a message with a TikTok URL and the bot will reply with the video and separate audio
- Music:
  start a message with `найти`, `трек`, or `песня`, for example:
  - `найти after dark`
  - `трек rammstein sonne`
  - `песня in the end slowed`

The bot keeps the same simple UX:

- TikTok loading message: `Загрузка 🔎`
- Music loading message: `Ищу трек 🔎`
- one-result delivery flow
- best-effort loading-message cleanup

## Architecture Overview

The repository keeps a layered structure:

- `app/presentation`: aiogram handlers and transport wiring
- `app/application`: orchestration services for TikTok and music flows
- `app/domain`: entities, enums, policies, interfaces, typed errors
- `app/infrastructure`: Telegram gateway, SQLite repositories, ffmpeg, yt-dlp integrations, music providers, temp storage, logging
- `app/workers`: cleanup and health workers

## Music Backend Design

The music flow is intentionally decoupled into separate concerns:

- search provider:
  used to resolve candidate tracks and metadata
- metadata provider:
  used for optional cover-art retrieval
- download providers:
  used to acquire downloadable audio

Current production-oriented design:

- YouTube / YouTube Music is used for search and metadata discovery
- primary downloadable path is a configurable remote HTTP download provider
- YouTube direct extraction remains only as an optional fallback path

This reduces operational dependence on fragile direct YouTube media extraction.

## Directory Structure

```text
app/
  main.py
  config.py
  presentation/
  application/
  domain/
  infrastructure/
  workers/
  tests/
alembic/
deployment/
scripts/
```

## Requirements

- Python 3.11
- ffmpeg installed on the VPS
- Telegram bot token from BotFather
- SQLite for MVP persistence

Optional for music fallback:

- `yt-dlp`
- valid cookies file for YouTube-backed search/fallback if you want cookie-backed resolver/download attempts

Recommended for stable music delivery:

- an operator-managed HTTP download backend exposed through `MUSIC_REMOTE_PROVIDER_URL`

## Configuration

Copy `.env.example` to `.env`.

Minimal `.env`:

```env
BOT_TOKEN=1234567890:telegram-bot-token
```

Important settings:

- `BOT_TOKEN`: required Telegram bot token
- `BOT_MODE`: current implementation uses `polling`
- `DATABASE_URL`: default `sqlite+aiosqlite:///runtime/bot.db`
- `TEMP_DIR`: temp processing directory
- `FFMPEG_PATH`: ffmpeg binary path
- `YTDLP_PATH`: yt-dlp executable name/path for diagnostics and fallback downloader
- `YTDLP_COOKIES_FILE`: optional Netscape cookies file path for YouTube-backed music resolver/fallback
- `MAX_PARALLEL_DOWNLOADS`: global download concurrency limit
- `MAX_PARALLEL_FFMPEG`: ffmpeg concurrency limit
- `USER_REQUESTS_PER_MINUTE`: per-user rate limit
- `USER_REQUEST_COOLDOWN_SECONDS`: soft cooldown between requests from the same user
- `MAX_MUSIC_QUERY_LENGTH`: music query guard
- `MUSIC_SEARCH_TIMEOUT_SECONDS`: search provider timeout
- `MUSIC_RESOLVER_MAX_CANDIDATES`: number of candidates evaluated per music request
- `MUSIC_RESOLVER_ORDER`: resolver strategy order, default `youtube_cookies,youtube_no_cookies`
- `MUSIC_DOWNLOAD_PROVIDER_ORDER`: download strategy order, default `remote_http,youtube_cookies,youtube_no_cookies`
- `MUSIC_REMOTE_PROVIDER_URL`: recommended primary music download backend endpoint
- `MUSIC_REMOTE_PROVIDER_TOKEN`: optional bearer token for the remote music backend
- `MUSIC_REMOTE_PROVIDER_TIMEOUT_SECONDS`: timeout for the remote music backend
- `MUSIC_STRATEGY_ORDER`: legacy compatibility setting still accepted for resolver ordering
- `YOUTUBE_AUTH_FAIL_THRESHOLD`: repeated auth failures before degrading cookie-backed YouTube path
- `YOUTUBE_DEGRADE_TTL_MINUTES`: TTL for degraded cookie-backed YouTube state
- `COOKIE_HEALTHCHECK_ENABLED`: skip degraded cookie-backed strategies until recovery window expires

## Remote Music Download Provider Contract

The recommended primary music backend is a simple HTTP provider.

Request:

- `POST` to `MUSIC_REMOTE_PROVIDER_URL`
- JSON body contains:
  - `query`
  - `normalized_query`
  - `candidate` with source id, title, performer, canonical/source URLs, thumbnail, ranking

Supported response modes:

- JSON:
  - `download_url` or `audio_url`
  - optional `title`, `performer`, `thumbnail_url`, `canonical_url`, `source_id`, `source_name`, `file_name`
- direct audio response:
  - `audio/*` or `application/octet-stream`

This keeps the bot pluggable: the search backend and the actual download backend do not need to be the same system.

## Local Development

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"
cp .env.example .env
alembic upgrade head
python -m app.main
```

## Migrations

Apply all migrations:

```bash
alembic upgrade head
```

Rollback one revision:

```bash
alembic downgrade -1
```

## Tests

Run the full suite:

```bash
pytest -q
```

Run only e2e-style tests:

```bash
pytest app/tests/e2e -q
```

Coverage includes:

- TikTok URL extraction and normalization
- music trigger parsing and hardened query validation
- multi-candidate music resolution
- stable-provider-first acquisition and fallback behavior
- degraded YouTube auth state tracking and recovery
- cache reuse and invalid cached file rebuild
- SQLite repository round-trips
- Telegram delivery behavior
- temp-file lifecycle
- private/group happy paths and failure paths

## Deployment on Ubuntu

1. Clone the repository to your VPS.
2. Create `.env` from `.env.example`.
3. Install system dependencies:

```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv ffmpeg
```

4. Create virtualenv and install the app:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"
```

5. Apply migrations:

```bash
alembic upgrade head
```

6. Start the bot:

```bash
python -m app.main
```

Systemd example:

```bash
sudo cp deployment/systemd/tiktok-downloader-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable tiktok-downloader-bot
sudo systemctl start tiktok-downloader-bot
sudo systemctl status tiktok-downloader-bot
```

Logs:

```bash
journalctl -u tiktok-downloader-bot -f
```

## Operational Notes

- TikTok flow is unchanged by the music refactor.
- Music cache keys still use normalized queries like `music:ytm:<normalized_query>`.
- Music cache now also stores which acquisition backend produced the cached Telegram audio.
- The bot still uses temp files only during active processing.
- Cookie-backed YouTube strategies are health-tracked in SQLite and automatically degraded after repeated auth-like failures.
- Remote HTTP download is the recommended primary music backend for a low-maintenance VPS setup.
- If the remote backend is not configured or unavailable, the bot can still try configured fallback download strategies.

## Limitations

- The bot still returns only one music result to the user.
- YouTube-backed fallback remains subject to upstream anti-bot behavior, cookies freshness, and extractor changes.
- A remote music backend is recommended for production stability; this repository does not bundle a universal third-party media service.
- SQLite is appropriate for a small VPS, but not for large multi-process deployments.
