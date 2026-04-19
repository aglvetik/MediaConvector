from app.domain.enums.platform import Platform
from app.infrastructure.providers.source_detection import detect_source_type, extract_candidate_urls, extract_first_supported_url


def test_detect_source_type_for_tiktok_hosts_only() -> None:
    assert detect_source_type("https://www.tiktok.com/@user/video/1") == Platform.TIKTOK
    assert detect_source_type("https://vm.tiktok.com/ZM123456/") == Platform.TIKTOK
    assert detect_source_type("https://example.com/video/1") is None


def test_extract_first_supported_url_returns_first_tiktok_url() -> None:
    text = "first https://example.com/x and then https://vm.tiktok.com/ZM123456/"
    assert extract_first_supported_url(text) == "https://vm.tiktok.com/ZM123456/"


def test_extract_candidate_urls_preserves_order() -> None:
    text = "one https://example.com/a two https://www.tiktok.com/@user/photo/123"
    assert extract_candidate_urls(text) == [
        "https://example.com/a",
        "https://www.tiktok.com/@user/photo/123",
    ]
