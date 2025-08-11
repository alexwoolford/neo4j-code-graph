from __future__ import annotations

import time


class FakeNVDClient:
    def __init__(self, with_key: bool):
        self.with_key = with_key
        self.calls = 0

    def fetch(self, gav: str) -> dict:
        self.calls += 1
        # Simulate rate limits: with key, no sleep; without key, sleep 0.01s
        if not self.with_key:
            time.sleep(0.01)
        # Return tiny CVE-like payload
        return {"id": "CVE-TEST", "configurations": []}


def test_fake_nvd_rate_has_key_is_faster():
    c1 = FakeNVDClient(with_key=True)
    c2 = FakeNVDClient(with_key=False)

    t0 = time.time()
    for _ in range(5):
        c1.fetch("g:a:v")
    t_key = time.time() - t0

    t0 = time.time()
    for _ in range(5):
        c2.fetch("g:a:v")
    t_no_key = time.time() - t0

    assert t_no_key > t_key
