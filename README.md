# Multi-Source Telegram URL Downloader Bot

Production-oriented Telegram bot for Python 3.11 that downloads public media links and sends them back to Telegram.

The bot works from ordinary text messages with URLs. It detects the first supported public link, normalizes it into a shared media artifact, downloads the media with the right engine, sends the appropriate Telegram media type, and reuses Telegram `file_id` cache for repeated requests.

## Supported Sources

- TikTok
- YouTube
- Instagram
- Facebook
- Pinterest
- Rutube
- Likee

## Engine Split

This project now uses two download engines on purpose:

- `yt-dlp` for video and audio-first URLs
- `gallery-dl` for image, gallery, and slideshow URLs

In practice:

- TikTok video posts -> `yt-dlp`
- TikTok music URLs -> `yt-dlp`
- TikTok photo/slideshow posts -> `gallery-dl`
- YouTube video URLs -> `yt-dlp`
- Instagram reels/videos -> `yt-dlp`
- Instagram image posts/carousels -> `gallery-dl`
- Facebook videos/reels -> `yt-dlp`
- Facebook image/gallery-style posts -> `gallery-dl` when extractable
- Pinterest image pins/galleries -> `gallery-dl`
- Rutube videos -> `yt-dlp`
- Likee videos/audio-first URLs -> `yt-dlp`

## Supported Content Types

- Video posts
  - sends video
  - tries to extract and send separate audio when an audio track exists
  - audio is prepared as Telegram-safe MP3 with title/performer metadata when available
  - if separate audio extraction fails, the video can still be sent
- Image-only posts
  - sends one image as a Telegram photo
  - sends multiple images as a Telegram media group
- Gallery/slideshow posts
  - prepares valid entries only
  - skips broken gallery items when it can still deliver the remaining images
  - keeps visuals as the primary delivery target even when separate audio is unavailable
- Audio-only URLs
  - sends Telegram audio
  - passes title, performer, duration, and thumbnail when available

TikTok specifics:

- TikTok `/music/...` links are handled as direct audio-only URLs through `yt-dlp`
- TikTok `/photo/...` slideshow posts are handled as visual-first downloads through `gallery-dl`
- separate audio for TikTok video/photo content is best-effort optional, not guaranteed

## What It Does Not Do

- No generic text-based music search
- No `найти`, `трек`, or `песня` trigger flow
- No `ytsearch` song lookup
- No paid APIs
- No cloud backends

This bot is focused on direct public media URLs only.

## Architecture

The project keeps the layered structure:

- `app/presentation`: aiogram handlers and transport
- `app/application`: orchestration services and pipelines
- `app/domain`: entities, enums, policies, interfaces, errors
- `app/infrastructure`: Telegram gateway, SQLite repositories, ffmpeg, yt-dlp, gallery-dl, providers, temp management, logging
- `app/workers`: cleanup and health workers

Key runtime stages:

1. detect the first supported URL in a message
2. classify source and content type
3. choose `yt-dlp` or `gallery-dl`
4. normalize the result into a shared artifact
5. deliver video, photo, gallery, or audio through one Telegram delivery layer
6. reuse cached Telegram `file_id` values when possible

On startup, the bot validates `ffmpeg`, `yt-dlp`, and `gallery-dl` and fails fast if a required binary cannot be resolved.

## Requirements

- Python 3.11
- ffmpeg installed on the host
- yt-dlp installed on the host or available in PATH
- gallery-dl installed on the host or available in PATH
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
- `GALLERYDL_PATH`: gallery-dl binary path
- `YTDLP_COOKIES_FILE`: optional cookies file for direct extractor flows where upstream behavior may require it
- `MAX_PARALLEL_DOWNLOADS`: network/download concurrency shared by the engines
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

Send a message containing a supported public URL, for example:

- `https://www.tiktok.com/@user/video/1234567890`
- `https://www.tiktok.com/@user/photo/1234567890`
- `https://youtu.be/dQw4w9WgXcQ`
- `https://www.instagram.com/reel/abc123/`
- `https://www.instagram.com/p/abc123/`
- `https://www.facebook.com/watch/?v=123456789`
- `https://www.pinterest.com/pin/123456789/`
- `https://rutube.ru/video/abcdef123456/`
- `https://likee.video/@user/video/999999`

The bot will:

1. detect the first supported URL in the message
2. send `Загрузка 🔎`
3. route the URL to `yt-dlp` or `gallery-dl`
4. normalize the result into video, photo, gallery, or audio
5. normalize gallery downloads from disk and prepare audio metadata/tags when possible
6. deliver the media to Telegram
7. reuse cached Telegram `file_id` values on repeated requests when possible

Messages without supported URLs are ignored.

If a message contains only unsupported URLs, the bot replies with a short failure message.

## Migrations

Apply all migrations:

```bash
alembic upgrade head
```

No extra migration is required specifically for the two-engine upgrade.

## Tests

Run the full suite:

```bash
pytest -q
```

The suite covers:

- source detection for supported platforms
- engine routing by content type
- TikTok URL extraction and normalization
- TikTok video, photo/slideshow, and sound-link flows
- unsupported URL handling
- single-video, single-photo, gallery, and audio-only flows
- cache reuse and invalid cache rebuild
- duplicate in-flight handling
- ffmpeg behavior
- Telegram delivery behavior
- temp-file lifecycle

## Deployment On Ubuntu

1. Clone the repository on the VPS.
2. Create `.env` from `.env.example`.
3. Install requirements:

```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv ffmpeg
```

4. Create virtualenv and install Python dependencies:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"
```

5. Ensure the binaries are available:

```bash
which yt-dlp
which gallery-dl
which ffmpeg
```

If `gallery-dl` is not available yet:

```bash
source .venv/bin/activate
pip install -U gallery-dl
```

6. Apply migrations:

```bash
alembic upgrade head
```

7. Start the bot:

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
- Cookies are optional and only relevant for some direct extractor flows.
- `yt-dlp` is kept focused on video/audio-first extraction.
- `gallery-dl` is used for photo/gallery/slideshow extraction where that path is more stable.
- TikTok music links are handled as audio-only URLs through `yt-dlp`.
- Separate audio for video/photo content is best-effort: primary video or visuals are still sent when optional audio preparation fails.
- Temporary files are cleaned after processing and by the cleanup worker.
- SQLite is suitable for a small VPS, but not for larger multi-process deployments.

## Limitations

- Platform support still depends on upstream site behavior and extractor health.
- Public media responses can change without notice.
- Large files can still exceed Telegram upload limits.
- SQLite is not intended for high-write multi-instance deployments.

---
Note

The old text-based track search was removed because it was too unstable in real-world VPS operation.

This project now focuses on direct media URLs instead of song search by words. YouTube-related search and extractor instability was one of the reasons for that change.
