import pytest

from app.application.services.rate_limit_service import RateLimitService
from app.domain.errors import RateLimitExceededError


def test_rate_limit_blocks_after_threshold() -> None:
    service = RateLimitService(enabled=True, requests_per_minute=2)
    service.ensure_allowed(1)
    service.ensure_allowed(1)
    with pytest.raises(RateLimitExceededError):
        service.ensure_allowed(1)

