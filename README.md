# TikTok Telegram Downloader Bot

Production-oriented Telegram bot for Python 3.11 that auto-detects TikTok links, downloads the video, extracts separate audio, sends both to Telegram, and reuses Telegram `file_id` cache on repeated requests.

## Features

- Auto-detects TikTok URLs in normal text messages
- Works in private chats, groups, and supergroups
- Sends `Загрузка 🔎` while processing
- Downloads TikTok video without watermark when available from the downloader path
- Extracts separate audio with ffmpeg
- Sends video and audio with `🎬 Готово!`
- Reuses cached Telegram `file_id` values for repeated requests
- Rebuilds invalid cached media automatically
- Uses temp files only during active processing
- Cleans temp files on startup and in the background worker
- Uses SQLite, Alembic migrations, structured logging, and aiogram polling mode

## Architecture

The project keeps a layered structure:

- `app/presentation`: aiogram handlers and transport
- `app/application`: orchestration services and pipelines
- `app/domain`: entities, enums, policies, interfaces, errors
- `app/infrastructure`: Telegram gateway, SQLite repositories, ffmpeg, TikTok provider, temp management, logging
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
4. If the media is cached, it reuses Telegram `file_id`.
5. Otherwise it downloads the video, extracts audio, sends both, saves cache, and cleans temp files.

## Migrations

Apply all migrations:

```bash
alembic upgrade head
```

The latest migration removes old music-only schema that is no longer used.

## Tests

Run the full suite:

```bash
pytest -q
```

The suite covers:

- TikTok URL extraction and normalization
- cache reuse and invalid cache rebuild
- duplicate in-flight handling
- ffmpeg audio extraction behavior
- Telegram gateway behavior
- temp-file lifecycle
- private/group TikTok success flows

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

- The bot only handles supported video/link conversion flow now.
- Non-command messages without a supported TikTok link are ignored.
- Temporary files are cleaned after processing and by the cleanup worker.
- SQLite is suitable for a small VPS, but not for larger multi-process deployments.

## Limitations

- The downloader depends on upstream TikTok and yt-dlp behavior.
- Large files can still exceed Telegram upload limits.
- SQLite is not intended for high-write multi-instance deployments.
