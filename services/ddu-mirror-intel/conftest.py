"""Pytest bootstrap — disable abuse limits so the suite can create many sessions."""

from __future__ import annotations

import os

# Must be set before app/limiter is consulted on each request.
os.environ["MIRROR_RATE_LIMIT"] = "0"
os.environ.setdefault("MIRROR_ENV", "development")
os.environ.pop("MIRROR_IDENTITY_REQUIRED", None)

import pytest

from mirror_intel.ratelimit import limiter, reset_for_tests


@pytest.fixture(autouse=True)
def _clear_rate_limit_state() -> None:
    limiter.enabled = False
    reset_for_tests()
    yield
    reset_for_tests()
