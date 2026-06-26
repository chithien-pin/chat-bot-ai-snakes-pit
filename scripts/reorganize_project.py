#!/usr/bin/env python3
"""One-shot: move root .py into cps_bot/ + tests/, rewrite imports."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MOVES: dict[str, str] = {
    "cps_api.py": "cps_bot/cps/cps_api.py",
    "cps_store.py": "cps_bot/cps/cps_store.py",
    "cps_provinces.py": "cps_bot/cps/cps_provinces.py",
    "cps_installment.py": "cps_bot/cps/cps_installment.py",
    "cps_enrich.py": "cps_bot/cps/cps_enrich.py",
    "cps_menu.py": "cps_bot/cps/cps_menu.py",
    "cps_category_filter.py": "cps_bot/cps/cps_category_filter.py",
    "scraper.py": "cps_bot/cps/scraper.py",
    "category_resolver.py": "cps_bot/browse/category_resolver.py",
    "category_filter_browse.py": "cps_bot/browse/category_filter_browse.py",
    "budget_browse.py": "cps_bot/browse/budget_browse.py",
    "fast_reply.py": "cps_bot/browse/fast_reply.py",
    "product_map.py": "cps_bot/browse/product_map.py",
    "gemini_client.py": "cps_bot/llm/gemini_client.py",
    "deepseek_client.py": "cps_bot/llm/deepseek_client.py",
    "byteplus_client.py": "cps_bot/llm/byteplus_client.py",
    "message_intent.py": "cps_bot/llm/message_intent.py",
    "disambiguation.py": "cps_bot/llm/disambiguation.py",
    "conversation.py": "cps_bot/core/conversation.py",
    "session_store.py": "cps_bot/core/session_store.py",
    "location_flow.py": "cps_bot/core/location_flow.py",
    "metrics.py": "cps_bot/core/metrics.py",
    "feedback.py": "cps_bot/feedback/feedback.py",
    "feedback_training.py": "cps_bot/feedback/feedback_training.py",
    "lark_bitable.py": "cps_bot/feedback/lark_bitable.py",
    "lark_feedback_notify.py": "cps_bot/feedback/lark_feedback_notify.py",
    "lark_ws_patch.py": "cps_bot/lark/lark_ws_patch.py",
    "menu_category_sync.py": "cps_bot/sync/menu_category_sync.py",
    "category_attributes_sync.py": "cps_bot/sync/category_attributes_sync.py",
    "bot.py": "cps_bot/apps/telegram.py",
    "lark_bot.py": "cps_bot/apps/lark.py",
    "dashboard_api.py": "cps_bot/apps/dashboard.py",
}

TEST_FILES = [
    "test_cps_provinces.py", "test_product_links.py", "test_stock_availability.py",
    "test_message_intent.py", "test_scenario_matrix.py", "test_location_flow.py",
    "test_advanced_search.py", "test_variant_resolve.py", "test_disambiguation.py",
    "test_location_hint.py", "test_budget_browse.py", "test_lark_topic.py",
    "test_category_filter.py", "test_stock_browse.py", "test_context_follow_up.py",
    "test_shop_stock_keywords.py", "test_product_map.py", "test_extract_keywords.py",
    "test_byteplus_client.py", "test_scenario_classify.py", "scenario_matrix.py",
]
TEST_MOVES = {name: f"tests/{name}" for name in TEST_FILES}

# old top-level module -> new dotted path
IMPORT_MAP: dict[str, str] = {
    "budget_browse": "cps_bot.browse.budget_browse",
    "category_resolver": "cps_bot.browse.category_resolver",
    "category_filter_browse": "cps_bot.browse.category_filter_browse",
    "fast_reply": "cps_bot.browse.fast_reply",
    "product_map": "cps_bot.browse.product_map",
    "cps_api": "cps_bot.cps.cps_api",
    "cps_store": "cps_bot.cps.cps_store",
    "cps_provinces": "cps_bot.cps.cps_provinces",
    "cps_installment": "cps_bot.cps.cps_installment",
    "cps_enrich": "cps_bot.cps.cps_enrich",
    "cps_menu": "cps_bot.cps.cps_menu",
    "cps_category_filter": "cps_bot.cps.cps_category_filter",
    "scraper": "cps_bot.cps.scraper",
    "gemini_client": "cps_bot.llm.gemini_client",
    "deepseek_client": "cps_bot.llm.deepseek_client",
    "byteplus_client": "cps_bot.llm.byteplus_client",
    "message_intent": "cps_bot.llm.message_intent",
    "disambiguation": "cps_bot.llm.disambiguation",
    "conversation": "cps_bot.core.conversation",
    "session_store": "cps_bot.core.session_store",
    "location_flow": "cps_bot.core.location_flow",
    "metrics": "cps_bot.core.metrics",
    "feedback": "cps_bot.feedback.feedback",
    "feedback_training": "cps_bot.feedback.feedback_training",
    "lark_bitable": "cps_bot.feedback.lark_bitable",
    "lark_feedback_notify": "cps_bot.feedback.lark_feedback_notify",
    "lark_ws_patch": "cps_bot.lark.lark_ws_patch",
    "menu_category_sync": "cps_bot.sync.menu_category_sync",
    "category_attributes_sync": "cps_bot.sync.category_attributes_sync",
    "scenario_matrix": "tests.scenario_matrix",
}

SORTED_MODULES = sorted(IMPORT_MAP.keys(), key=len, reverse=True)


def _replace_imports(text: str) -> str:
    for mod in SORTED_MODULES:
        new = IMPORT_MAP[mod]
        text = re.sub(
            rf"\bfrom {re.escape(mod)} import\b",
            f"from {new} import",
            text,
        )
        text = re.sub(
            rf"\bimport {re.escape(mod)}\b",
            f"import {new}",
            text,
        )
    # dashboard_api uvicorn target
    text = text.replace('"cps_bot.apps.dashboard:app"', '"cps_bot.apps.dashboard:app"')
    # dashboard static path when in cps_bot/apps/
    text = text.replace(
        "ROOT = Path(__file__).resolve().parent\nSTATIC_DIR = ROOT / \"dashboard\" / \"static\"",
        "ROOT = Path(__file__).resolve().parent.parent.parent\nSTATIC_DIR = ROOT / \"dashboard\" / \"static\"",
    )
    return text


def move_files() -> None:
    for sub in (
        "cps_bot/cps", "cps_bot/browse", "cps_bot/llm", "cps_bot/core",
        "cps_bot/feedback", "cps_bot/lark", "cps_bot/sync", "cps_bot/apps", "tests",
    ):
        (ROOT / sub).mkdir(parents=True, exist_ok=True)

    for pkg in ("cps_bot", "cps_bot/cps", "cps_bot/browse", "cps_bot/llm",
                "cps_bot/core", "cps_bot/feedback", "cps_bot/lark", "cps_bot/sync",
                "cps_bot/apps", "tests"):
        init = ROOT / pkg / "__init__.py"
        if not init.exists():
            init.write_text('"""CPS Bot package."""\n', encoding="utf-8")

    for src, dst in {**MOVES, **TEST_MOVES}.items():
        s = ROOT / src
        d = ROOT / dst
        if not s.is_file():
            print(f"skip missing {src}")
            continue
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(s), str(d))
        print(f"moved {src} -> {dst}")


def rewrite_all_py() -> None:
    for path in list(ROOT.rglob("*.py")):
        if ".venv" in path.parts or "cps-nuxt-standard" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        new = _replace_imports(text)
        if new != text:
            path.write_text(new, encoding="utf-8")
            print(f"updated imports: {path.relative_to(ROOT)}")


def write_root_shims() -> None:
    shims = {
        "bot.py": '''"""Entry: Telegram bot."""
from cps_bot.apps.telegram import main

if __name__ == "__main__":
    main()
''',
        "lark_bot.py": '''"""Entry: Lark bot."""
from cps_bot.apps.lark import main

if __name__ == "__main__":
    main()
''',
        "dashboard_api.py": '''"""Entry: Bot operations dashboard API."""
from cps_bot.apps.dashboard import app, main

__all__ = ["app", "main"]

if __name__ == "__main__":
    main()
''',
        "menu_category_sync.py": '''"""Entry: sync menu → category map."""
from cps_bot.sync.menu_category_sync import main

if __name__ == "__main__":
    main()
''',
        "category_attributes_sync.py": '''"""Entry: sync category attribute filters."""
from cps_bot.sync.category_attributes_sync import main

if __name__ == "__main__":
    main()
''',
    }
    for name, body in shims.items():
        (ROOT / name).write_text(body, encoding="utf-8")
        print(f"shim {name}")


def fix_same_package_imports() -> None:
    """Use relative imports inside cps_bot subpackages where sensible."""
    rel_pairs = [
        ("cps_bot/feedback/feedback.py", "from cps_bot.feedback.feedback_training", "from .feedback_training"),
        ("cps_bot/llm/gemini_client.py", "from cps_bot.feedback.feedback_training", "from cps_bot.feedback.feedback_training"),
        ("cps_bot/core/conversation.py", "from cps_bot.core.session_store", "from .session_store"),
    ]
    for rel, old, new in rel_pairs:
        p = ROOT / rel
        if p.is_file():
            t = p.read_text(encoding="utf-8")
            if old in t:
                p.write_text(t.replace(old, new), encoding="utf-8")


def main() -> None:
    move_files()
    rewrite_all_py()
    fix_same_package_imports()
    write_root_shims()
    print("done")


if __name__ == "__main__":
    main()
