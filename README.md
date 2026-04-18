# TikTok Telegram Downloader Bot

Production-oriented Telegram bot for Python 3.11 with two supported feature groups:

- TikTok media handling
- text-triggered track search

The TikTok flow auto-detects TikTok links in normal messages, resolves the post type, downloads the required media, sends the result to Telegram, and reuses Telegram `file_id` cache for repeated requests.

The track-search flow is intentionally lightweight: it reacts to `найти`, `трек`, or `песня` at the start of a message, searches public YouTube results through `yt-dlp`, downloads audio, converts it to MP3 with `ffmpeg`, and reuses a persistent local JSON/file cache for repeated queries.

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
- Supports text-triggered track search:
  - `найти <query>`
  - `трек <query>`
  - `песня <query>`
- Uses public YouTube search through `yt-dlp`
- Does not require cookies for track search
- Converts downloaded track audio to MP3 with `ffmpeg`
- Reuses cached Telegram `file_id` values for repeated TikTok requests
- Reuses cached local MP3 files for repeated track-search queries
- Uses temp files only during active processing
- Cleans temp files on startup and in the background worker
- Uses SQLite, Alembic migrations, structured logging, and aiogram polling mode

## Architecture

The project keeps a layered structure:

- `app/presentation`: aiogram handlers and transport
- `app/application`: orchestration services and pipelines
- `app/domain`: entities, enums, policies, interfaces, errors
- `app/infrastructure`: Telegram gateway, SQLite repositories, JSON track cache, ffmpeg, yt-dlp clients, TikTok provider, temp management, logging
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
cache/
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
- `TRACK_CACHE_DIR`: persistent cache directory for track-search MP3 files and JSON index
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

### TikTok flow

1. Send a TikTok link in any normal text message.
2. The bot detects the first supported TikTok URL automatically.
3. The bot sends `Загрузка 🔎`.
4. The provider resolves the TikTok resource type:
   - `video`
   - `photo_post`
   - `music_only`
5. If the result is cached, the bot reuses Telegram `file_id`.
6. Otherwise it downloads the required media, sends it, saves cache, and cleans temp files.

### Track-search flow

1. Start a message with one of the trigger words:
   - `найти`
   - `трек`
   - `песня`
2. The bot normalizes the remaining query.
3. It searches public YouTube results through `yt-dlp`.
4. It ranks the top candidates and picks the best match.
5. It downloads audio, converts it to MP3, and sends it to Telegram as audio.
6. It stores the resulting MP3 in `TRACK_CACHE_DIR` and writes a JSON cache entry.
7. Repeated identical queries reuse the cached MP3 file immediately if it still exists.

Examples:

- `найти Hot Dog Limp Bizkit`
- `трек Linkin Park Numb`
- `песня Metallica One`

Notes:

- Track search uses standard public YouTube search via `yt-dlp`, not YouTube Music or cookies.
- Search quality depends on YouTube search results, so the best match may not always be perfect.

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
- track-trigger parsing and normalization
- track candidate ranking and metadata normalization
- track cache hit, miss, and missing-file repair
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

- Non-command messages without a supported TikTok link or a supported trigger are ignored.
- TikTok requests use SQLite-backed Telegram `file_id` cache.
- Track-search requests use a persistent JSON/file cache in `TRACK_CACHE_DIR`.
- Temporary files are cleaned after processing and by the cleanup worker.
- SQLite is suitable for a small VPS, but not for larger multi-process deployments.

## Limitations

- TikTok support depends on upstream TikTok and yt-dlp behavior.
- Track search depends on YouTube search quality.
- Large files can still exceed Telegram upload limits.
- SQLite is not intended for high-write multi-instance deployments.
