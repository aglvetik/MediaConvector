from __future__ import annotations

import logging

import pytest

from app.bootstrap import _validate_required_binaries
from app.config import Settings


def test_validate_required_binaries_raises_when_dependency_is_missing(monkeypatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123:test-token")
    settings = Settings(_env_file=None)

    def fake_resolve(path: str) -> str | None:
        if path == settings.gallerydl_path:
            return None
        return f"/usr/bin/{path}"

    monkeypatch.setattr("app.bootstrap._resolve_binary_path", fake_resolve)

    with pytest.raises(RuntimeError, match="gallery-dl"):
        _validate_required_binaries(settings, logging.getLogger("tests.bootstrap"))
