from app.domain.entities.track_search_candidate import TrackSearchCandidate
from app.domain.policies import derive_track_metadata


def test_track_metadata_splits_artist_dash_title() -> None:
    title, performer = derive_track_metadata(
        TrackSearchCandidate(
            source_id="1",
            source_url="https://youtube/1",
            title="Rammstein - Sonne",
            uploader=None,
            thumbnail_url=None,
            duration_sec=250,
            score=0,
        )
    )
    assert title == "Sonne"
    assert performer == "Rammstein"


def test_track_metadata_falls_back_to_uploader() -> None:
    title, performer = derive_track_metadata(
        TrackSearchCandidate(
            source_id="1",
            source_url="https://youtube/1",
            title="After Dark",
            uploader="Mr.Kitty Topic",
            thumbnail_url=None,
            duration_sec=250,
            score=0,
        )
    )
    assert title == "After Dark"
    assert performer == "Mr.Kitty Topic"
