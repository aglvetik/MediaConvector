from app.domain.enums.platform import Platform
from app.domain.policies.cache_key import build_cache_key


def test_build_cache_key() -> None:
    assert build_cache_key(Platform.TIKTOK, "video", "123") == "tiktok:video:123"

