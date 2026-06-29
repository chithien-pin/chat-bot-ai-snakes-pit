"""Test tra cứu product map."""
from __future__ import annotations

import tempfile
from pathlib import Path

import config
import cps_bot.browse.product_map as pm
from cps_bot.browse.product_map import ProductMapEntry, _score_entry, clear_product_map_cache, resolve_product_from_map


def _write_sample_map(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "30031-Ốp lưng iPhone 12 Pro Max Memumi Slim",
                "30092-iPhone 12 Pro Chính Hãng (VN/A)",
                "30116-iPhone 12 mini 128GB-Đen",
                "59234-iPhone 16 Pro Max 256GB Titan Tự Nhiên",
                "59235-iPhone 16 Pro Max 512GB Titan Tự Nhiên",
                "59240-Samsung Galaxy S24 Ultra 512GB",
            ]
        ),
        encoding="utf-8",
    )


def test_resolve_iphone_16_pro_max_from_map() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        sample = Path(tmp) / "product_map.txt"
        _write_sample_map(sample)
        old_path = config.PRODUCT_MAP_PATH
        try:
            config.PRODUCT_MAP_PATH = str(sample)
            pm.PRODUCT_MAP_PATH = str(sample)
            pm.PRODUCT_MAP_ENABLED = True
            pm.PRODUCT_MAP_MIN_SCORE = 20
            clear_product_map_cache()

            hit = resolve_product_from_map(
                "iphone 16 pro max 256gb titan tự nhiên"
            )
            assert hit is not None
            assert hit.product_id == "59234"
            assert "16 Pro Max" in hit.name

            case = resolve_product_from_map("s24 ultra 512gb")
            assert case is not None
            assert case.product_id == "59240"
        finally:
            config.PRODUCT_MAP_PATH = old_path
            pm.PRODUCT_MAP_PATH = old_path
            clear_product_map_cache()


def test_score_penalizes_used_unless_asked() -> None:
    entry = ProductMapEntry(
        product_id="1",
        name="iPhone 12 Pro Cũ",
        tokens=frozenset({"iphone", "12", "pro", "cu"}),
        text_folded="iphone 12 pro cu",
    )
    score_new = _score_entry(
        entry,
        {"iphone", "12", "pro"},
        "iphone 12 pro",
        query_storage=set(),
        wants_used=False,
        phone_query=True,
    )
    score_used = _score_entry(
        entry,
        {"iphone", "12", "pro", "cu"},
        "iphone 12 pro cu",
        query_storage=set(),
        wants_used=True,
        phone_query=True,
    )
    assert score_used > score_new


def test_real_map_has_iphone_16() -> None:
    if not Path(config.PRODUCT_MAP_PATH).is_file():
        return
    clear_product_map_cache()
    hit = resolve_product_from_map("iphone 16 pro max")
    assert hit is not None
    assert hit.product_id == "59258"


def test_real_map_iphone_16_256gb_pink() -> None:
    if not Path(config.PRODUCT_MAP_PATH).is_file():
        return
    clear_product_map_cache()
    hit = resolve_product_from_map("iphone 16 hồng 256g")
    assert hit is not None, "phải resolve iPhone 16 256GB từ map"
    assert hit.product_id == "90112", hit
    assert "16" in hit.name
    assert "256" in hit.name


def test_real_map_iphone_16_128gb_prefers_base_over_plus() -> None:
    if not Path(config.PRODUCT_MAP_PATH).is_file():
        return
    clear_product_map_cache()
    hit = resolve_product_from_map("iphone 16 xanh mỏng két 128g")
    assert hit is not None, "phải resolve iPhone 16 (không Plus)"
    assert "Plus" not in hit.name, hit.name
    assert hit.product_id in {"59254", "90112"}, hit


def test_real_map_iphone_16_xanh_luu_ly() -> None:
    if not Path(config.PRODUCT_MAP_PATH).is_file():
        return
    clear_product_map_cache()
    hit = resolve_product_from_map("iphone 16 xanh lưu ly")
    assert hit is not None
    assert hit.product_id == "59254"
    assert hit.name == "iPhone 16"


def test_real_map_s26_ultra_den_not_apple_watch() -> None:
    """s26 ultra đen không được map nhầm Apple Watch Ultra."""
    if not Path(config.PRODUCT_MAP_PATH).is_file():
        return
    clear_product_map_cache()
    hit = resolve_product_from_map("s26 ultra đen có hàng ở q5 không")
    assert hit is not None, "phải resolve Galaxy S26 Ultra từ map"
    assert "Galaxy S26 Ultra" in hit.name, hit.name
    assert "Apple Watch" not in hit.name, hit.name
    assert hit.product_id in {"125121", "125128", "125131"}, hit


def test_tokenize_vietnamese_den() -> None:
    from cps_bot.browse.product_map import _tokenize

    assert "den" in _tokenize("s26 ultra đen")


def test_expand_galaxy_s_shorthand() -> None:
    from cps_bot.browse.product_term_synonyms import normalize_product_terms

    assert normalize_product_terms("s26 ultra đen") == "samsung galaxy s26 ultra đen"
    assert normalize_product_terms("s26u") == "samsung galaxy s26 ultra"


if __name__ == "__main__":
    test_resolve_iphone_16_pro_max_from_map()
    test_score_penalizes_used_unless_asked()
    test_real_map_has_iphone_16()
    test_real_map_s26_ultra_den_not_apple_watch()
    test_tokenize_vietnamese_den()
    test_expand_galaxy_s_shorthand()
    print("OK — product map tests passed")
