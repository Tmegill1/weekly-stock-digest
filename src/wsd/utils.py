import time
import threading
import functools
import requests
from wsd.config import Settings

_limiter_instance: "RateLimiter | None" = None
_limiter_lock = threading.Lock()


def _get_limiter(rate: int) -> "RateLimiter":
    global _limiter_instance
    with _limiter_lock:
        if _limiter_instance is None:
            _limiter_instance = RateLimiter(rate)
    return _limiter_instance


class RateLimiter:
    def __init__(self, rate: int) -> None:
        self.rate = rate
        self._tokens = float(rate)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            self._tokens = min(float(self.rate), self._tokens + elapsed * self.rate)
            self._last = now
            if self._tokens < 1:
                time.sleep((1.0 - self._tokens) / self.rate)
                self._tokens = 0.0
            else:
                self._tokens -= 1.0


def retry(attempts: int = 3, backoff: float = 2.0):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc: Exception | None = None
            for attempt in range(attempts):
                try:
                    return func(*args, **kwargs)
                except requests.HTTPError as exc:
                    wait = 60.0 if exc.response is not None and exc.response.status_code == 429 else backoff ** attempt
                    time.sleep(wait)
                    last_exc = exc
                except requests.RequestException as exc:
                    time.sleep(backoff ** attempt)
                    last_exc = exc
            raise last_exc  # type: ignore[misc]
        return wrapper
    return decorator


def edgar_get(url: str, settings: Settings) -> dict:
    limiter = _get_limiter(settings.edgar_rate_limit)

    @retry(attempts=3, backoff=2.0)
    def _fetch() -> dict:
        limiter.acquire()
        response = requests.get(url, headers={"User-Agent": settings.edgar_user_agent})
        response.raise_for_status()
        return response.json()

    return _fetch()
