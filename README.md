# TikTok Telegram Downloader Bot

Production-oriented Telegram bot for Python 3.11 focused on TikTok media handling.

The bot auto-detects TikTok links in normal messages, resolves the TikTok post type, downloads the required media, sends the result to Telegram, and reuses Telegram `file_id` cache for repeated requests.

## Features

- Auto-detects TikTok URLs in normal text messages
- Works in private chats, groups, and supergroups
- Sends `Загрузка 🔎` while processing
- Supports TikTok video posts:
  - sends video
  - sends separate audio
- Supports TikTok photo/slideshow posts:
  - sends all photos
  - uses media group when possible
  - falls back to sequential photos if media group fails
  - sends separate audio
- Supports TikTok sound/music links:
  - sends audio only
- Reuses cached Telegram `file_id` values for repeated TikTok requests
- Uses temp files only during active processing
- Cleans temp files on startup and in the background worker
- Uses SQLite, Alembic migrations, structured logging, and aiogram polling mode

## Architecture

The project keeps a layered structure:

- `app/presentation`: aiogram handlers and transport
- `app/application`: orchestration services and pipelines
- `app/domain`: entities, enums, policies, interfaces, errors
- `app/infrastructure`: Telegram gateway, SQLite repositories, ffmpeg, yt-dlp client, TikTok provider, temp management, logging
- `app/workers`: cleanup and health workers

## Repository Layout

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
- ffmpeg installed on the host
- yt-dlp installed on the host or available in PATH
- Telegram bot token
- SQLite

## Configuration

Copy `.env.example` to `.env`.

Minimal `.env`:

```env
BOT_TOKEN=1234567890:telegram-bot-token
```

Important settings:

- `BOT_TOKEN`: Telegram bot token
- `BOT_MODE`: transport mode, currently `polling`
- `DATABASE_URL`: default `sqlite+aiosqlite:///runtime/bot.db`
- `TEMP_DIR`: temp processing directory
- `FFMPEG_PATH`: ffmpeg binary path
- `YTDLP_PATH`: yt-dlp binary path
- `MAX_PARALLEL_DOWNLOADS`: network/download concurrency
- `MAX_PARALLEL_FFMPEG`: ffmpeg concurrency
- `USER_REQUESTS_PER_MINUTE`: per-user rate limit
- `USER_REQUEST_COOLDOWN_SECONDS`: soft cooldown between requests from one user

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

## How It Works

1. Send a TikTok link in any normal text message.
2. The bot detects the first supported TikTok URL automatically.
3. The bot sends `Загрузка 🔎`.
4. The provider resolves the TikTok resource type:
   - `video`
   - `photo_post`
   - `music_only`
5. If the result is cached, the bot reuses Telegram `file_id`.
6. Otherwise it downloads the required media, sends it, saves cache, and cleans temp files.

## Migrations

Apply all migrations:

```bash
alembic upgrade head
```

The latest migration adds TikTok resource-type-aware cache fields for photo posts.

## Tests

Run the full suite:

```bash
pytest -q
```

The suite covers:

- TikTok URL extraction and normalization
- TikTok video/photo/music-only flows
- photo-group fallback behavior
- cache reuse and invalid cache rebuild
- duplicate in-flight handling
- ffmpeg behavior
- Telegram gateway behavior
- temp-file lifecycle

## Deployment On Ubuntu

1. Clone the repository on the VPS.
2. Create `.env` from `.env.example`.
3. Install requirements:

```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv ffmpeg
```

4. Create virtualenv and install:

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

Systemd:

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

- Non-command messages without a supported TikTok link are ignored.
- TikTok requests use SQLite-backed Telegram `file_id` cache.
- Temporary files are cleaned after processing and by the cleanup worker.
- SQLite is suitable for a small VPS, but not for larger multi-process deployments.

## Limitations

- TikTok support depends on upstream TikTok and yt-dlp behavior.
- Large files can still exceed Telegram upload limits.
- SQLite is not intended for high-write multi-instance deployments.

---
Note

A generic text-based track search feature was planned, where users could type requests like "найти ..." and the bot would fetch a matching song automatically.

That feature was intentionally removed from this project after repeated instability from third-party music source behavior, authentication friction, and unreliable extractor responses in real VPS operation.

In short: I wanted this feature, but it turned into a maintenance nightmare.

Also, I hate YouTube for this.
---
