"""Process-local sliding-window admission. Anonymous callers share one bucket."""
from collections import deque
from dataclasses import dataclass, field
from threading import RLock
from typing import Protocol
import math
import time

from backend.domain.errors import ApplicationError


class RateLimitExceeded(ApplicationError):
    def __init__(self, retry_after_ms):
        super().__init__(code="AGENT_RATE_LIMITED", message="Too many Agent requests. Please wait and try again.",
                         status_code=429, processing_mode="agent", retryable=True,
                         retry_after_ms=max(1, retry_after_ms), action="Wait before starting another Agent request.")


@dataclass
class _Bucket:
    requests: deque = field(default_factory=deque)
    active: int = 0


class _Lease:
    def __init__(self, limiter, bucket, concurrent):
        self.limiter, self.bucket, self.concurrent = limiter, bucket, concurrent
        self.released = False

    def release(self):
        with self.limiter._lock:
            if not self.released:
                if self.concurrent:
                    self.bucket.active -= 1
                self.released = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.release()


class RateLimiter(Protocol):
    def acquire(self, user_id, policy, *, concurrent=True): ...


class ProcessRateLimiter:
    def __init__(self, *, clock=time.monotonic, max_buckets=10000):
        if max_buckets < 1:
            raise ValueError("Bucket capacity must be positive")
        self.clock, self.max_buckets = clock, max_buckets
        self._lock = RLock()
        self._buckets = {}

    def acquire(self, user_id, policy, *, concurrent=True):
        # Tuple keys prevent a real username from colliding with anonymous traffic.
        key = ("user", user_id) if user_id else ("anonymous", None)
        with self._lock:
            now = self.clock()
            for bucket in self._buckets.values():
                while bucket.requests and bucket.requests[0] <= now - 60:
                    bucket.requests.popleft()
            if key not in self._buckets:
                for old_key in tuple(self._buckets):
                    bucket = self._buckets[old_key]
                    if not bucket.active and not bucket.requests:
                        del self._buckets[old_key]
                if len(self._buckets) >= self.max_buckets:
                    raise RateLimitExceeded(60000)
                self._buckets[key] = _Bucket()
            bucket = self._buckets[key]
            request_limit = policy.requests_per_minute if user_id else min(policy.requests_per_minute, policy.anonymous_requests_per_minute)
            concurrency = policy.concurrent_runs if user_id else min(policy.concurrent_runs, policy.anonymous_concurrent_runs)
            if len(bucket.requests) >= request_limit:
                raise RateLimitExceeded(math.ceil((bucket.requests[0] + 60 - now) * 1000))
            if concurrent and bucket.active >= concurrency:
                raise RateLimitExceeded(1000)
            bucket.requests.append(now)
            if concurrent:
                bucket.active += 1
            return _Lease(self, bucket, concurrent)
