import pytest

from app.worker.tasks import retry_delay


@pytest.mark.parametrize(("retries", "base"), [(0, 1), (1, 2), (3, 8), (6, 60), (10, 60)])
def test_retry_delay_grows_exponentially_with_cap_and_jitter(retries: int, base: int) -> None:
    delay = retry_delay(retries)
    assert base <= delay <= base + 1
