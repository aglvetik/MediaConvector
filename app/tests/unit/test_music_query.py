import pytest

from app import messages
from app.application.services.music_search_service import MusicSearchService
from app.domain.errors import MusicQueryValidationError
from app.domain.policies import parse_music_trigger
from app.tests.fakes import FakeMusicProvider


def test_music_trigger_detection_and_query_extraction() -> None:
    parsed = parse_music_trigger("найти after dark")
    assert parsed == ("найти", "after dark")


def test_music_trigger_detection_is_case_insensitive() -> None:
    parsed = parse_music_trigger("ТРЕК   rammstein sonne")
    assert parsed == ("трек", "rammstein sonne")


def test_music_search_service_rejects_empty_query() -> None:
    service = MusicSearchService(provider=FakeMusicProvider(), max_query_length=120)
    with pytest.raises(MusicQueryValidationError) as exc_info:
        service.parse_message("песня   ")
    assert exc_info.value.user_message == messages.music_empty_query("песня")


def test_music_cache_key_generation() -> None:
    service = MusicSearchService(provider=FakeMusicProvider(), max_query_length=120)
    query = service.parse_message("Найти   After Dark")
    assert query is not None
    assert query.normalized_resource.normalized_key == "music:ytm:after dark"
