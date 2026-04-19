# Multi-Source Telegram Media Downloader Bot

Production-oriented Telegram bot for Python 3.11 that downloads public media links and sends them back to Telegram.

The bot works from ordinary text messages with URLs. It detects the first supported public link, downloads the media, sends the right Telegram media type, and reuses Telegram `file_id` cache for repeated requests.

## Supported Sources

- TikTok
- YouTube
- Instagram
- Facebook
- Pinterest
- Rutube
- Likee

## Supported Content Types

- Video posts
  - sends video
  - tries to extract and send separate audio when the source contains an audio track
  - if separate audio extraction fails, the video is still sent when possible
- Image-only posts
  - sends one image as a Telegram photo
  - sends multi-image posts as a photo group
- Audio-only URLs
  - sends Telegram audio
- Gallery-like extractor results
  - normalizes entries
  - skips invalid items when it can still deliver valid images safely

## What It Does Not Do

- No generic text-based music search
- No `найти`, `трек`, or `песня` trigger flow
- No `ytsearch` song lookup
- No paid APIs
- No cloud backends

The bot is focused on direct public media URLs only.

## Current TikTok Behavior

TikTok support remains first-class:

- video posts -> video + separate audio
- photo/slideshow posts -> photos + separate audio
- sound/music links -> audio only

## Architecture

The project keeps a layered structure:

- `app/presentation`: aiogram handlers and transport
- `app/application`: orchestration services and pipelines
- `app/domain`: entities, enums, policies, interfaces, errors
- `app/infrastructure`: Telegram gateway, SQLite repositories, ffmpeg, yt-dlp client, providers, temp management, logging
- `app/workers`: cleanup and health workers

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

Useful settings:

- `BOT_TOKEN`: Telegram bot token
- `BOT_MODE`: transport mode, currently `polling`
- `DATABASE_URL`: default `sqlite+aiosqlite:///runtime/bot.db`
- `LOG_LEVEL`: logging level
- `TEMP_DIR`: temp processing directory
- `FFMPEG_PATH`: ffmpeg binary path
- `YTDLP_PATH`: yt-dlp binary path
- `YTDLP_COOKIES_FILE`: optional cookies file for platforms where upstream extraction may require it
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

## Usage

Send a message containing a public supported URL, for example:

- `https://www.tiktok.com/@user/video/1234567890`
- `https://youtu.be/dQw4w9WgXcQ`
- `https://www.instagram.com/reel/abc123/`
- `https://www.facebook.com/watch/?v=123456789`
- `https://www.pinterest.com/pin/123456789/`
- `https://rutube.ru/video/abcdef123456/`
- `https://likee.video/@user/video/999999`

The bot will:

1. detect the first supported URL in the message
2. send `Загрузка 🔎`
3. normalize the extractor result into video, photo, gallery, or audio
4. deliver the media to Telegram
5. reuse cached Telegram `file_id` values on repeated requests when possible

Messages without supported URLs are ignored.

If the message contains only unsupported URLs, the bot replies with a short failure message.

## Migrations

Apply all migrations:

```bash
alembic upgrade head
```

No additional migration step is needed specifically for the multi-source upgrade beyond the normal migration chain.

## Tests

Run the full suite:

```bash
pytest -q
```

The suite covers:

- source detection for supported platforms
- TikTok URL extraction and normalization
- TikTok video, photo/slideshow, and sound-link flows
- unsupported URL handling
- generic single video, single photo, gallery, and audio-only flows
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

- The bot works with direct public media links only.
- Cookies are optional and only relevant for some platforms when upstream extractor behavior requires them.
- Temporary files are cleaned after processing and by the cleanup worker.
- SQLite is suitable for a small VPS, but not for larger multi-process deployments.

## Limitations

- Platform support still depends on upstream site behavior and yt-dlp extractor health.
- Some platforms can change their public media responses without notice.
- Large files can still exceed Telegram upload limits.
- SQLite is not intended for high-write multi-instance deployments.

---
Note

The old text-trigger music search was removed because it was too unstable in real-world VPS operation.

This project is now focused on direct media links, not song search by words.
---
