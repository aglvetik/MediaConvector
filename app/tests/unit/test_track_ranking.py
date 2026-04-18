from app.domain.entities.track_search_candidate import TrackSearchCandidate
from app.domain.policies import rank_track_candidates


def test_track_ranking_prefers_normal_track_over_variants() -> None:
    ranked = rank_track_candidates(
        query="linkin park numb",
        candidates=[
            TrackSearchCandidate(
                source_id="1",
                source_url="https://youtube/1",
                title="Linkin Park - Numb (Remix)",
                uploader="Uploader",
                thumbnail_url=None,
                duration_sec=200,
                score=0,
            ),
            TrackSearchCandidate(
                source_id="2",
                source_url="https://youtube/2",
                title="Linkin Park - Numb",
                uploader="Linkin Park Official",
                thumbnail_url=None,
                duration_sec=185,
                score=0,
            ),
            TrackSearchCandidate(
                source_id="3",
                source_url="https://youtube/3",
                title="Linkin Park - Numb (Live)",
                uploader="Live Channel",
                thumbnail_url=None,
                duration_sec=240,
                score=0,
            ),
        ],
    )
    assert ranked[0].source_id == "2"


def test_track_ranking_allows_live_when_query_explicitly_mentions_it() -> None:
    ranked = rank_track_candidates(
        query="metallica one live",
        candidates=[
            TrackSearchCandidate(
                source_id="1",
                source_url="https://youtube/1",
                title="Metallica - One (Live)",
                uploader="Metallica",
                thumbnail_url=None,
                duration_sec=400,
                score=0,
            ),
            TrackSearchCandidate(
                source_id="2",
                source_url="https://youtube/2",
                title="Metallica - One",
                uploader="Metallica Topic",
                thumbnail_url=None,
                duration_sec=450,
                score=0,
            ),
        ],
    )
    assert ranked[0].source_id == "1"
