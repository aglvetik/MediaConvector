from __future__ import annotations

from app.domain.entities.track_search_candidate import TrackSearchCandidate

_NEGATIVE_HINTS = {
    "karaoke": -60,
    "remix": -35,
    "slowed": -35,
    "reverb": -30,
    "nightcore": -45,
    "instrumental": -35,
    "cover": -30,
    "live": -25,
}
_POSITIVE_HINTS = {
    "official": 12,
    "topic": 10,
    "audio": 4,
}


def rank_track_candidates(
    *,
    query: str,
    candidates: list[TrackSearchCandidate],
    min_duration_seconds: int = 60,
    max_duration_seconds: int = 12 * 60,
) -> list[TrackSearchCandidate]:
    ranked: list[TrackSearchCandidate] = []
    normalized_query = query.casefold()
    for candidate in candidates:
        score = score_track_candidate(
            query=normalized_query,
            candidate=candidate,
            min_duration_seconds=min_duration_seconds,
            max_duration_seconds=max_duration_seconds,
        )
        ranked.append(
            TrackSearchCandidate(
                source_id=candidate.source_id,
                source_url=candidate.source_url,
                title=candidate.title,
                uploader=candidate.uploader,
                thumbnail_url=candidate.thumbnail_url,
                duration_sec=candidate.duration_sec,
                score=score,
            )
        )
    return sorted(ranked, key=lambda item: item.score, reverse=True)


def score_track_candidate(
    *,
    query: str,
    candidate: TrackSearchCandidate,
    min_duration_seconds: int,
    max_duration_seconds: int,
) -> int:
    haystack = f"{candidate.title} {candidate.uploader or ''}".casefold()
    score = 100

    if not candidate.title.strip():
        score -= 100

    for hint, penalty in _NEGATIVE_HINTS.items():
        if hint in haystack and hint not in query:
            score += penalty
        elif hint in haystack and hint in query:
            score += 12

    for hint, bonus in _POSITIVE_HINTS.items():
        if hint in haystack:
            score += bonus

    if candidate.duration_sec is not None:
        if candidate.duration_sec < min_duration_seconds:
            score -= 25
        elif candidate.duration_sec > max_duration_seconds:
            score -= 20
        else:
            score += 10

    query_tokens = {token for token in query.split() if token}
    if query_tokens:
        matched_tokens = sum(1 for token in query_tokens if token in haystack)
        score += matched_tokens * 8

    return score
