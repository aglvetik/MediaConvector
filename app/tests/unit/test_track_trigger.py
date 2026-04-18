import pytest

from app.domain.errors import InvalidTrackQueryError
from app.domain.policies import parse_track_trigger


def test_track_trigger_parses_find_query() -> None:
    parsed = parse_track_trigger("найти song name")
    assert parsed is not None
    assert parsed.trigger == "найти"
    assert parsed.raw_query == "song name"
    assert parsed.normalized_query == "song name"


def test_track_trigger_parses_case_insensitive_with_leading_spaces() -> None:
    parsed = parse_track_trigger("   ПЕСНЯ   Linkin   Park   Numb  ")
    assert parsed is not None
    assert parsed.trigger == "песня"
    assert parsed.normalized_query == "linkin park numb"


def test_track_trigger_not_at_start_does_not_match() -> None:
    assert parse_track_trigger("скачай и найди song") is None


def test_track_trigger_without_query_raises() -> None:
    with pytest.raises(InvalidTrackQueryError):
        parse_track_trigger("трек   ")


def test_track_trigger_rejects_punctuation_only_query() -> None:
    with pytest.raises(InvalidTrackQueryError):
        parse_track_trigger("найти .")
