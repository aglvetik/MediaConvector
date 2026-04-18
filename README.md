# TikTok and Music Telegram Bot

Production-oriented Telegram bot for Python 3.11.

It keeps two user-facing flows:

- TikTok:
  auto-detect a TikTok link in a message, send video plus separate audio
- Music:
  start a message with `найти`, `трек`, or `песня`, then send one matching track as Telegram audio

The bot keeps SQLite cache, temp-file-only processing, structured logging, polling mode, and a layered architecture.

## What Changed In The Music Backend

The music feature no longer depends on YouTube / YouTube Music direct media extraction as the default production path.

Current default provider order:

- `jamendo`
- `internet_archive`

This means:

- search and download now use legal, API-backed, publicly downloadable music sources
- YouTube direct extraction is no longer part of the active production order
- the tradeoff is smaller catalog coverage, but much better stability for a VPS bot

## User Experience

TikTok flow:

- send a TikTok link
- bot replies with `Загрузка 🔎`
- bot sends video and separate audio

Music flow:

- send a message starting with:
  - `найти`
  - `трек`
  - `песня`
- bot replies with `Ищу трек 🔎`
- bot sends one audio track with title / performer / thumbnail when available

Examples:

- `найти after dark`
- `трек rammstein sonne`
- `песня in the end slowed`

TikTok behavior and Telegram UX remain unchanged by the music refactor.

## Architecture

The repository keeps a layered structure:

- `app/presentation`: aiogram handlers and transport
- `app/application`: orchestration services and pipelines
- `app/domain`: entities, enums, policies, interfaces, errors
- `app/infrastructure`: Telegram gateway, SQLite repositories, ffmpeg, TikTok provider, music providers, temp management, logging
- `app/workers`: cleanup and health workers

### Music Provider Architecture

The music subsystem is split into:

- resolver/search providers
- download providers
- metadata/thumbnail provider

Current production configuration:

- Jamendo:
  official API search plus legal download URLs
- Internet Archive:
  official search and metadata endpoints plus downloadable public audio files
- HTTP metadata provider:
  thumbnail download helper

This keeps search and download decoupled and avoids using a fragile YouTube extraction path as the main backend.

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
- Telegram bot token
- SQLite

Optional legacy fallback tooling still present in the repo:

- `yt-dlp`
- `YTDLP_COOKIES_FILE`

Those are no longer required for the default production music path.

## Configuration

Copy `.env.example` to `.env`.

Minimal `.env`:

```env
BOT_TOKEN=1234567890:telegram-bot-token
JAMENDO_CLIENT_ID=your-jamendo-client-id
```

Important settings:

- `BOT_TOKEN`: Telegram bot token
- `BOT_MODE`: transport mode, currently `polling`
- `DATABASE_URL`: default `sqlite+aiosqlite:///runtime/bot.db`
- `TEMP_DIR`: temp processing directory
- `FFMPEG_PATH`: ffmpeg binary path
- `MAX_PARALLEL_DOWNLOADS`: network/download concurrency
- `MAX_PARALLEL_FFMPEG`: ffmpeg concurrency
- `USER_REQUESTS_PER_MINUTE`: per-user rate limit
- `USER_REQUEST_COOLDOWN_SECONDS`: soft cooldown between requests from one user
- `MAX_MUSIC_QUERY_LENGTH`: music query length guard
- `MUSIC_RESOLVER_MAX_CANDIDATES`: candidates checked per music request
- `MUSIC_RESOLVER_ORDER`: default `jamendo,internet_archive`
- `MUSIC_DOWNLOAD_PROVIDER_ORDER`: default `jamendo,internet_archive`
- `JAMENDO_CLIENT_ID`: required for Jamendo API access
- `JAMENDO_TIMEOUT_SECONDS`: Jamendo request timeout
- `INTERNET_ARCHIVE_TIMEOUT_SECONDS`: Internet Archive request timeout

Legacy / optional settings still accepted:

- `YTDLP_PATH`
- `YTDLP_COOKIES_FILE`
- `MUSIC_STRATEGY_ORDER`
- `YOUTUBE_AUTH_FAIL_THRESHOLD`
- `YOUTUBE_DEGRADE_TTL_MINUTES`
- `MUSIC_AUDIO_ONLY`
- `COOKIE_HEALTHCHECK_ENABLED`

They are kept mainly for backward-compatible optional fallback wiring, not for the default production music order.

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

Run only music-related tests:

```bash
pytest app/tests/unit app/tests/integration app/tests/e2e -q
```

The suite covers:

- TikTok extraction and normalization
- music trigger parsing and validation
- Jamendo parsing and legal-download filtering
- Internet Archive search parsing and downloadable file selection
- provider ordering and fallback behavior
- music cache reuse and invalid cache rebuild
- Telegram audio delivery behavior
- temp-file lifecycle
- private/group success flows

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

- TikTok flow is unchanged.
- Music cache keys still use normalized queries like `music:ytm:<normalized_query>`.
- Music cache now stores which acquisition backend produced the cached Telegram audio.
- Jamendo is the preferred first source when `JAMENDO_CLIENT_ID` is configured.
- If Jamendo is unavailable or yields no usable result, the bot falls back to Internet Archive.
- The music backend now prefers stable legal downloads over maximum catalog size.
- Temporary files are cleaned after processing and by the cleanup worker.

## Limitations

- Catalog breadth is smaller than a YouTube-based scraper approach.
- Jamendo requires an API client id.
- Internet Archive search quality depends on public metadata quality.
- The bot still returns one track only, with no result-selection UI.
- SQLite is suitable for a small VPS, but not for larger multi-process deployments.
