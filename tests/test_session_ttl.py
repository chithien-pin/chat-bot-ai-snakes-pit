"""Test TTL session 24h."""
from __future__ import annotations

import time

from cps_bot.core.conversation import (
    append_turn,
    get_session,
    has_product_context,
    session_is_expired,
)
from cps_bot.core.session_store import is_session_stale, session_expiry_cutoff


def test_session_stale_after_ttl() -> None:
    now = time.time()
    old = now - 25 * 3600
    assert is_session_stale(old, now=now)
    assert not is_session_stale(now - 3600, now=now)


def test_get_session_resets_expired() -> None:
    store: dict = {}
    sess = get_session(store, "chat1", "user1")
    sess["last_keywords"] = "iphone 17"
    sess["turns"] = [{"user": "q", "assistant": "a", "keywords": "iphone 17"}]
    sess["updated_at"] = session_expiry_cutoff() - 100

    refreshed = get_session(store, "chat1", "user1")
    assert not has_product_context(refreshed)
    assert refreshed["turns"] == []


def test_append_turn_refreshes_updated_at() -> None:
    store: dict = {}
    sess = get_session(store, "c", "u")
    before = sess["updated_at"]
    time.sleep(0.01)
    append_turn(sess, user="hi", assistant="ok", keywords="test")
    assert sess["updated_at"] >= before
    assert not session_is_expired(sess)
