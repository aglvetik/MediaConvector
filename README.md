# TikTok and Music Telegram Bot

Telegram bot for Python 3.11 that automatically detects TikTok URLs in incoming text messages, downloads the video, extracts separate audio, searches tracks by text triggers, caches Telegram `file_id` values in SQLite, and runs well on a small Ubuntu VPS.

## Features

- Auto-detects TikTok URLs from plain text messages.
- Searches music when a message starts with `найти`, `трек`, or `песня`.
- Resolves multiple music candidates and tries acquisition strategies in order until one succeeds.
- Works in private chats, groups, and supergroups.
- Sends `Загрузка 🔎` immediately and removes it best-effort after completion.
- Sends `Ищу трек 🔎` for music search requests and removes it best-effort after completion.
- Downloads TikTok video with `yt-dlp`.
- Extracts separate audio with `ffmpeg`.
- Sends video and audio with the caption `🎬 Готово!`.
- Sends found tracks as Telegram audio with title, performer, and thumbnail when available.
- Reuses cached Telegram `file_id` values for repeated requests.
- Invalidates and rebuilds broken cached media automatically.
- Tracks YouTube cookies/source health in SQLite and temporarily degrades broken auth paths.
- Uses only temporary processing files under `TEMP_DIR`.
- Cleans temporary files on startup and on a periodic worker.
- Prevents duplicate in-flight processing per normalized TikTok resource.
- Prevents duplicate in-flight processing per normalized music query.
- Prevents duplicate harmful execution for the same `chat_id + message_id + normalized_key`.
- Applies a soft per-user cooldown and allows only one active job per user at a time.

## Processing Model

The bot has two automatic user-facing flows:

- send a normal text message containing a TikTok URL
- the bot detects the first supported TikTok URL automatically
- the bot processes it without any special command or mention mode
- send a normal text message starting with `найти`, `трек`, or `песня`
- the bot extracts the rest of the message as a music query
- the bot validates the query, resolves several candidates, and tries the configured acquisition strategies until one track can be delivered as Telegram audio

Available service commands:

- `/start`
- `/help`

## Architecture

The codebase keeps a layered structure:

- `app/presentation`: aiogram routers and middlewares.
- `app/application`: orchestration and business workflows for TikTok and music pipelines, including strategy-based music acquisition and source health tracking.
- `app/domain`: entities, enums, policies, interfaces, typed errors.
- `app/infrastructure`: Telegram gateway, SQLite repositories, yt-dlp clients, ffmpeg, TikTok provider, YouTube-oriented music resolver, cookie provider, temp file management, logging.
- `app/workers`: periodic cleanup and health workers.

## Prerequisites

- Linux / Ubuntu VPS target.
- Python 3.11.
- `ffmpeg` installed and available in `PATH` or via `FFMPEG_PATH`.
- Telegram bot token from BotFather.

## Configuration

Copy `.env.example` to `.env` and set the values you need.

Minimal `.env`:

```env
BOT_TOKEN=1234567890:telegram-bot-token
```

Supported variables:

- `BOT_TOKEN`: Telegram bot token. Required.
- `BOT_MODE`: transport mode. Current implementation supports `polling`.
- `DATABASE_URL`: default `sqlite+aiosqlite:///runtime/bot.db`.
- `LOG_LEVEL`: default `INFO`.
- `TEMP_DIR`: default `runtime/tmp`.
- `MAX_PARALLEL_DOWNLOADS`: yt-dlp concurrency limit.
- `MAX_PARALLEL_FFMPEG`: ffmpeg concurrency limit.
- `MAX_FILE_SIZE_MB`: pre-upload Telegram size guard.
- `REQUEST_TIMEOUT_SECONDS`: general request timeout.
- `DOWNLOAD_TIMEOUT_SECONDS`: yt-dlp timeout.
- `FFMPEG_PATH`: ffmpeg binary path.
- `YTDLP_PATH`: yt-dlp binary path or executable name for diagnostics.
- `YTDLP_COOKIES_FILE`: optional Netscape cookies file path for music-search yt-dlp requests.
- `RATE_LIMIT_ENABLED`: enable per-user rate limiting.
- `USER_REQUESTS_PER_MINUTE`: per-user request budget.
- `USER_REQUEST_COOLDOWN_SECONDS`: soft cooldown between new requests from the same user.
- `MAX_MUSIC_QUERY_LENGTH`: maximum accepted music search query length.
- `MUSIC_SEARCH_TIMEOUT_SECONDS`: timeout for the music search provider step.
- `MUSIC_RESOLVER_MAX_CANDIDATES`: number of resolver candidates to consider for a music request.
- `MUSIC_STRATEGY_ORDER`: comma-separated acquisition strategy order. Current values: `youtube_cookies`, `youtube_no_cookies`.
- `YOUTUBE_AUTH_FAIL_THRESHOLD`: consecutive auth-style failures before the cookies strategy is degraded.
- `YOUTUBE_DEGRADE_TTL_MINUTES`: how long degraded auth state is respected before trying the cookies strategy again.
- `MUSIC_AUDIO_ONLY`: keep music downloads on an audio-only yt-dlp profile.
- `COOKIE_HEALTHCHECK_ENABLED`: skip degraded cookie-backed strategy attempts until the TTL expires.
- `TEMP_FILE_TTL_MINUTES`: temp artifact retention.
- `CLEANUP_INTERVAL_MINUTES`: cleanup worker interval.
- `HEALTH_INTERVAL_MINUTES`: health worker interval.
- `JOB_STALE_AFTER_MINUTES`: running job stale threshold.

## Local Run

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

Apply migrations:

```bash
alembic upgrade head
```

Rollback one revision:

```bash
alembic downgrade -1
```

Run the helper script:

```bash
./scripts/run_migrations.sh
```

## Tests

Run the full suite:

```bash
pytest -q
```

Run only end-to-end style tests:

```bash
pytest app/tests/e2e -q
```

Current coverage includes:

- URL extraction and normalization.
- Music trigger parsing, hardened query validation, file-name generation, per-user request guard logic, strategy fallback, and source-health degraded-mode recovery.
- Cache behavior and invalid cached media rebuild.
- Deduplication and rate limiting.
- Health-service fallback.
- SQLite repositories.
- Temp storage lifecycle and cleanup.
- ffmpeg adapter behavior.
- Telegram delivery abstraction.
- Private/group success flows, cache hit/miss, repeated URLs, parallel requests, invalid URLs, no-audio flows, oversized files, partial-audio recovery, music search success flows, music cache reuse, music invalid-cache rebuild, thumbnail optionality, and same-user cooldown behavior.

## Deployment on Ubuntu

1. Clone the repository to `/opt/tiktok-downloader-bot`.
2. Create `.env` from `.env.example`.
3. Bootstrap the environment:

```bash
cd /opt/tiktok-downloader-bot
./scripts/setup_ubuntu.sh /opt/tiktok-downloader-bot
```

4. Start the bot:

```bash
sudo cp deployment/systemd/tiktok-downloader-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable tiktok-downloader-bot
sudo systemctl start tiktok-downloader-bot
sudo systemctl status tiktok-downloader-bot
```

View logs:

```bash
journalctl -u tiktok-downloader-bot -f
```

## Operational Notes

- The bot expects migrations to be applied before startup.
- The runtime directory and SQLite parent directories are created automatically for SQLite URLs.
- Only temporary files are created under `TEMP_DIR`; they are removed after processing and by the cleanup worker.
- Cache identity is based on normalized keys like `tiktok:video:<resource_id>`, not raw URLs.
- Music cache identity is based on normalized keys like `music:ytm:<normalized_query>`.
- Partial cache records with missing audio are self-healed on later requests when the source is expected to have audio.
- Music search respects the user query as-is and does not aggressively filter slowed, remix, live, sped-up, nightcore, or lyrics variants.
- Music resolution now uses several candidates and then tries acquisition strategies in order. The default order is cookies-backed YouTube first, then no-cookies fallback.
- Cookie-backed strategy health is stored in SQLite. Repeated auth failures move that strategy into a temporary degraded state so the bot stops hammering a broken path on every request.
- `YTDLP_COOKIES_FILE` is optional, but if you configure it, keep it fresh. The bot can recover from transient auth failures, but stale or invalid cookies still need operator attention.
- SQLite is intentionally used for the MVP to keep VPS footprint small.

## Limitations

- TikTok downloads and resilient music search are implemented today.
- Polling mode is implemented; webhook support remains a future extension point.
- `yt-dlp` behavior depends on upstream extractor changes, TikTok anti-bot behavior, and YouTube result availability.
- Some TikTok resources may require cookies, region affinity, or authentication outside MVP scope.
- Music search still returns only one delivered track to the user; there is no multi-result selection UI in this version, even though the backend now evaluates multiple candidates internally.
- No cookies setup is permanently “set and forget”: the bot degrades and recovers automatically where possible, but expired cookies or upstream YouTube changes can still require operator intervention.
- SQLite is suitable for a small VPS, but not for large multi-process or high write-concurrency deployments.
