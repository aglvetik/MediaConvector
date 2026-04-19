# TikTok Telegram URL Downloader Bot

Production-oriented Telegram bot for Python 3.11 that downloads public TikTok links and sends the media back to Telegram.

The bot works from ordinary text messages with URLs. It detects the first TikTok link in the message, normalizes it into a shared media artifact, downloads the media with the right engine, sends the appropriate Telegram media type, and reuses Telegram `file_id` cache for repeated requests.

## Supported Source

- TikTok

## Engine Split

- TikTok video posts -> `yt-dlp`
- TikTok photo/slideshow posts -> `gallery-dl`

## Supported Content Types

- Video posts
  - sends video
  - tries to extract and send separate audio when an audio track exists
  - if separate audio extraction fails, the video can still be sent
- Image-only posts
  - sends one image as a Telegram photo
  - sends multiple images as a Telegram media group
- Gallery/slideshow posts
  - prepares valid entries only
  - skips broken gallery items when it can still deliver the remaining images
  - keeps visuals as the primary delivery target even when separate audio is unavailable

TikTok specifics:

- TikTok `/music/...` links are not supported right now; send a video link with that sound instead
- TikTok `/photo/...` slideshow posts are handled as visual-first downloads through `gallery-dl`
- separate audio for TikTok video/photo content is best-effort optional, not guaranteed

## What It Does Not Do

- No generic text-based music search
- No `найти трек` flow
- No multi-platform support

This bot is focused on direct public TikTok URLs only.

## Architecture

The project keeps the layered structure:

- `app/presentation`: aiogram handlers and transport
- `app/application`: orchestration services and pipelines
- `app/domain`: entities, enums, policies, interfaces, errors
- `app/infrastructure`: Telegram gateway, SQLite repositories, ffmpeg, yt-dlp, gallery-dl, TikTok provider, temp management, logging
- `app/workers`: cleanup and health workers

Key runtime stages:

1. detect the first TikTok URL in a message
2. classify it as TikTok video or TikTok photo/slideshow
3. choose `yt-dlp` or `gallery-dl`
4. normalize the result into a shared artifact
5. deliver video, photo, gallery, or optional audio through one Telegram delivery layer
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
- `DATABASE_URL`: default `sqlite+aiosqlite:///runtime/bot.db`
- `FFMPEG_PATH`: ffmpeg binary path
- `YTDLP_PATH`: yt-dlp binary path
- `GALLERYDL_PATH`: gallery-dl binary path
- `MAX_PARALLEL_DOWNLOADS`: download concurrency
- `MAX_PARALLEL_FFMPEG`: ffmpeg concurrency

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

Send a message containing a public TikTok URL, for example:

- `https://www.tiktok.com/@user/video/1234567890`
- `https://www.tiktok.com/@user/photo/1234567890`

The bot will:

1. detect the first TikTok URL in the message
2. send `Загрузка 🔎`
3. route the URL to `yt-dlp` or `gallery-dl`
4. normalize the result into video, photo, or gallery
5. prepare optional audio metadata/tags when possible
6. deliver the media to Telegram
7. reuse cached Telegram `file_id` values on repeated requests when possible

Messages without TikTok URLs are ignored.

If a message contains only unsupported URLs, the bot replies with a short failure message.

## Migrations

Apply all migrations:

```bash
alembic upgrade head
```

## Tests

Run the full suite:

```bash
pytest -q
```

The suite covers:

- TikTok URL detection
- TikTok URL extraction and normalization
- TikTok video and photo/slideshow flows
- unsupported URL handling
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

## Operational Notes

- The bot works with direct public TikTok links only.
- `yt-dlp` is used for TikTok videos.
- `gallery-dl` is used for TikTok photo/gallery/slideshow extraction.
- Separate audio for video/photo content is best-effort: primary video or visuals are still sent when optional audio preparation fails.
- Temporary files are cleaned after processing and by the cleanup worker.
- SQLite is suitable for a small VPS, but not for larger multi-process deployments.

## Limitations

- TikTok support still depends on upstream site behavior and extractor health.
- Public media responses can change without notice.
- Large files can still exceed Telegram upload limits.
- SQLite is not intended for high-write multi-instance deployments.

---
Note

The old text-based track search was removed because it was too unstable in real-world VPS operation.

This project now focuses on direct TikTok media URLs instead of song search by words.
