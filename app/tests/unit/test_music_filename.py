from app.domain.entities.music_track import MusicTrack
from app.domain.policies import build_track_file_name


def test_track_file_name_prefers_artist_and_title() -> None:
    track = MusicTrack(
        source_id="track-1",
        source_url="https://www.youtube.com/watch?v=track-1",
        canonical_url="https://music.youtube.com/watch?v=track-1",
        title="Summertime Sadness",
        performer="Lana Del Rey",
    )
    assert build_track_file_name(track) == "Lana Del Rey - Summertime Sadness.mp3"


def test_track_file_name_falls_back_to_title() -> None:
    track = MusicTrack(
        source_id="track-2",
        source_url="https://www.youtube.com/watch?v=track-2",
        canonical_url="https://music.youtube.com/watch?v=track-2",
        title="After Dark",
        performer=None,
    )
    assert build_track_file_name(track) == "After Dark.mp3"
