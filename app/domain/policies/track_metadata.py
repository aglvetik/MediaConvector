from __future__ import annotations

from app.domain.entities.track_search_candidate import TrackSearchCandidate


def derive_track_metadata(candidate: TrackSearchCandidate) -> tuple[str, str]:
    title = " ".join(candidate.title.split()).strip()
    performer = " ".join((candidate.uploader or "").split()).strip()

    if " - " in title:
        left, right = (part.strip() for part in title.split(" - ", 1))
        if left and right and not performer:
            performer = left
            title = right

    if not title:
        title = candidate.source_id or "Unknown track"
    if not performer:
        performer = "Unknown artist"
    return title, performer
