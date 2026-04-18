from app.infrastructure.providers.tiktok.url_utils import extract_first_tiktok_url, extract_music_id, extract_photo_id, extract_video_id


def test_extracts_first_tiktok_url_from_arbitrary_text() -> None:
    text = "hello https://example.com and https://www.tiktok.com/@user/video/1234567890?lang=ru more"
    assert extract_first_tiktok_url(text) == "https://www.tiktok.com/@user/video/1234567890?lang=ru"


def test_extracts_short_tiktok_url() -> None:
    text = "share https://vm.tiktok.com/ZM123456/"
    assert extract_first_tiktok_url(text) == "https://vm.tiktok.com/ZM123456/"


def test_extract_video_id_from_standard_url() -> None:
    assert extract_video_id("https://www.tiktok.com/@user/video/9876543210?lang=en") == "9876543210"


def test_extract_photo_id_from_standard_url() -> None:
    assert extract_photo_id("https://www.tiktok.com/@user/photo/1234567890?lang=en") == "1234567890"


def test_extract_music_id_from_standard_url() -> None:
    assert extract_music_id("https://www.tiktok.com/music/original-sound-1234567890") == "1234567890"
