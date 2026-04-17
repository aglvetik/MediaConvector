#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-/opt/tiktok-downloader-bot}"
PYTHON_BIN="${PYTHON_BIN:-python3.11}"

sudo apt-get update
sudo apt-get install -y ffmpeg sqlite3 "${PYTHON_BIN}" "${PYTHON_BIN}-venv"

mkdir -p "${PROJECT_DIR}"
cd "${PROJECT_DIR}"
"${PYTHON_BIN}" -m venv "${PROJECT_DIR}/.venv"
"${PROJECT_DIR}/.venv/bin/pip" install --upgrade pip
"${PROJECT_DIR}/.venv/bin/pip" install -e ".[dev]"
"${PROJECT_DIR}/.venv/bin/alembic" -c "${PROJECT_DIR}/alembic.ini" upgrade head
