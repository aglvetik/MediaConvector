from app.domain.enums.platform import Platform
from app.infrastructure.providers.source_detection import detect_source_type, extract_candidate_urls, extract_first_supported_url


def test_detect_source_type_for_supported_hosts() -> None:
    assert detect_source_type("https://www.tiktok.com/@user/video/1") == Platform.TIKTOK
    assert detect_source_type("https://youtu.be/abc123") == Platform.YOUTUBE
    assert detect_source_type("https://www.instagram.com/reel/xyz/") == Platform.INSTAGRAM
    assert detect_source_type("https://fb.watch/abcd/") == Platform.FACEBOOK
    assert detect_source_type("https://pin.it/example") == Platform.PINTEREST
    assert detect_source_type("https://rutube.ru/video/123/") == Platform.RUTUBE
    assert detect_source_type("https://likee.video/@user/video/555") == Platform.LIKEE


def test_extract_first_supported_url_skips_other_links() -> None:
    text = "first https://example.com/x and then https://youtu.be/abc123?si=1"
    assert extract_first_supported_url(text, Platform.YOUTUBE) == "https://youtu.be/abc123?si=1"


def test_extract_candidate_urls_preserves_order() -> None:
    text = "one https://example.com/a two https://www.instagram.com/p/demo/"
    assert extract_candidate_urls(text) == [
        "https://example.com/a",
        "https://www.instagram.com/p/demo/",
    ]
