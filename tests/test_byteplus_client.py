"""Tests — resolve BytePlus model / base URL."""
from __future__ import annotations

import importlib
import os
import sys


def _reload_byteplus(monkeypatch: dict[str, str]):
    for key, val in monkeypatch.items():
        if val is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = val
    for name in ("config", "byteplus_client"):
        if name in sys.modules:
            importlib.reload(sys.modules[name])
    from cps_bot.llm.byteplus_client import resolve_byteplus_settings

    return resolve_byteplus_settings


def test_gpt_oss_alias() -> None:
    resolve = _reload_byteplus(
        {
            "BYTEPLUS_API_MODE": "modelark",
            "BYTEPLUS_MODEL": "gpt-oss-120b",
            "BYTEPLUS_BASE_URL": "https://ark.ap-southeast.bytepluses.com/api/v3",
            "BYTEPLUS_ENDPOINT_ID": "",
        }
    )
    mode, base, model = resolve()
    assert mode == "modelark"
    assert model == "gpt-oss-120b-250805"
    assert base.endswith("/api/v3")


def test_kimi_uses_coding_url() -> None:
    resolve = _reload_byteplus(
        {
            "BYTEPLUS_API_MODE": "modelark",
            "BYTEPLUS_MODEL": "kimi-k2.5",
            "BYTEPLUS_BASE_URL": "https://ark.ap-southeast.bytepluses.com/api/v3",
            "BYTEPLUS_ENDPOINT_ID": "",
        }
    )
    mode, base, model = resolve()
    assert mode == "coding"
    assert model == "kimi-k2.5"
    assert "/api/coding/v3" in base


def test_endpoint_id_priority() -> None:
    resolve = _reload_byteplus(
        {
            "BYTEPLUS_API_MODE": "modelark",
            "BYTEPLUS_MODEL": "gpt-oss-120b",
            "BYTEPLUS_BASE_URL": "https://ark.ap-southeast.bytepluses.com/api/v3",
            "BYTEPLUS_ENDPOINT_ID": "ep-test-123",
        }
    )
    _, _, model = resolve()
    assert model == "ep-test-123"


if __name__ == "__main__":
    test_gpt_oss_alias()
    test_kimi_uses_coding_url()
    test_endpoint_id_priority()
    print("OK — byteplus resolve tests passed")
