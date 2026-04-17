# TikTok Telegram Downloader Bot

Telegram bot for Python 3.11 that automatically detects TikTok URLs in incoming text messages, downloads the video, extracts separate audio, caches Telegram `file_id` values in SQLite, and runs well on a small Ubuntu VPS.

## Features

- Auto-detects TikTok URLs from plain text messages.
- Works in private chats, groups, and supergroups.
- Sends `Загрузка 🔎` immediately and removes it best-effort after completion.
- Downloads TikTok video with `yt-dlp`.
- Extracts separate audio with `ffmpeg`.
- Sends video and audio with the caption `🎬 Готово!`.
- Reuses cached Telegram `file_id` values for repeated requests.
- Invalidates and rebuilds broken cached media automatically.
- Uses only temporary processing files under `TEMP_DIR`.
- Cleans temporary files on startup and on a periodic worker.
- Prevents duplicate in-flight processing per normalized TikTok resource.
- Prevents duplicate harmful execution for the same `chat_id + message_id + normalized_key`.

## Processing Model

The bot has one user-facing mode only:

- send a normal text message containing a TikTok URL
- the bot detects the first supported TikTok URL automatically
- the bot processes it without any special command or mention mode

Available service commands:

- `/start`
- `/help`

## Architecture

The codebase keeps a layered structure:

- `app/presentation`: aiogram routers and middlewares.
- `app/application`: orchestration and business workflows.
- `app/domain`: entities, enums, policies, interfaces, typed errors.
- `app/infrastructure`: Telegram gateway, SQLite repositories, yt-dlp, ffmpeg, TikTok provider, temp file management, logging.
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
- `RATE_LIMIT_ENABLED`: enable per-user rate limiting.
- `USER_REQUESTS_PER_MINUTE`: per-user request budget.
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
- Cache behavior and invalid cached media rebuild.
- Deduplication and rate limiting.
- Health-service fallback.
- SQLite repositories.
- Temp storage lifecycle and cleanup.
- ffmpeg adapter behavior.
- Telegram delivery abstraction.
- Private/group success flows, cache hit/miss, repeated URLs, parallel requests, invalid URLs, no-audio flows, oversized files, and partial-audio recovery.

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
- Partial cache records with missing audio are self-healed on later requests when the source is expected to have audio.
- SQLite is intentionally used for the MVP to keep VPS footprint small.

## Limitations

- Only TikTok is implemented today.
- Polling mode is implemented; webhook support remains a future extension point.
- `yt-dlp` behavior depends on upstream extractor changes and TikTok anti-bot behavior.
- Some TikTok resources may require cookies, region affinity, or authentication outside MVP scope.
- SQLite is suitable for a small VPS, but not for large multi-process or high write-concurrency deployments.
