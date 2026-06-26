"""
Tìm sản phẩm theo ngân sách — vd: điện thoại dưới 15 triệu.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_BUDGET_AMOUNT_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*"
    r"(triệu|trieu|tr(?!\w)|tỷ|ty|nghìn|nghin|k(?!\w)|đ|dong|vnd)?",
    re.IGNORECASE,
)

_BUDGET_UNDER_RE = re.compile(
    r"\b(?:"
    r"dưới|duoi|không quá|khong qua|tối đa|toi da|chưa tới|chua toi|"
    r"khoảng dưới|khoang duoi|<=|dưới mức|duoi muc"
    r")\s+"
    r"(\d+(?:[.,]\d+)?)\s*(?:triệu|trieu|tr\b|tỷ|ty|nghìn|nghin|k\b)?",
    re.IGNORECASE,
)

_BUDGET_OVER_RE = re.compile(
    r"\b(?:"
    r"trên|tren|từ|tu(?!\s*van)|ít nhất|it nhat|tối thiểu|toi thieu|>=|"
    r"trên mức|tren muc"
    r")\s+"
    r"(\d+(?:[.,]\d+)?)\s*(?:triệu|trieu|tr\b|tỷ|ty|nghìn|nghin|k\b)?",
    re.IGNORECASE,
)

_BUDGET_RANGE_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(?:triệu|trieu|tr\b)?\s*"
    r"(?:-|đến|den|tới|toi)\s*"
    r"(\d+(?:[.,]\d+)?)\s*(?:triệu|trieu|tr\b)?",
    re.IGNORECASE,
)

_BUDGET_TAM_GIA_RE = re.compile(
    r"\btầm\s+(?:giá\s+)?(\d+(?:[.,]\d+)?)\s*(?:triệu|trieu|tr\b)",
    re.IGNORECASE,
)

_BUDGET_K_UNDER_RE = re.compile(
    r"(?:"
    r"giá|gia|dưới|duoi|tầm giá|tam gia|"
    r"trở xuống|tro xuong|đổ lại|do lai|khoảng|khoang"
    r")\s*"
    r"(\d+)\s*k\b",
    re.IGNORECASE,
)

_BUDGET_K_ONLY_RE = re.compile(r"\b(\d+)\s*k\b", re.IGNORECASE)

_BUDGET_STRIP_RES: tuple[re.Pattern[str], ...] = (
    _BUDGET_UNDER_RE,
    _BUDGET_OVER_RE,
    _BUDGET_RANGE_RE,
    _BUDGET_TAM_GIA_RE,
    _BUDGET_K_UNDER_RE,
    _BUDGET_K_ONLY_RE,
    re.compile(r"^(?:mua|tìm|tim|cho)\s+", re.IGNORECASE),
    re.compile(
        r"\b(?:đổ lại|do lai|trở xuống|tro xuong|khoảng|khoang)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:"
        r"dưới|duoi|trên|tren|từ|tu|đến|den|tới|toi|"
        r"tầm giá|tam gia|tối đa|toi da|tối thiểu|toi thieu|"
        r"triệu|trieu|tr\b|tỷ|ty|nghìn|nghin|ngàn|ngan"
        r")\b",
        re.IGNORECASE,
    ),
    re.compile(r"\btầm\s+(?=\d+\s*(?:triệu|trieu|tr\b|k\b))", re.IGNORECASE),
    re.compile(r"\btầm\s+(?=\d+\s*lít)", re.IGNORECASE),
    re.compile(r"^(?:tầm|tam)\s+", re.IGNORECASE),
)

_CATEGORY_HINTS: tuple[str, ...] = (
    "điện thoại",
    "dien thoai",
    "smartphone",
    "laptop",
    "máy tính",
    "may tinh",
    "máy tính bảng",
    "may tinh bang",
    "tablet",
    "tai nghe",
    "loa",
    "smartwatch",
    "đồng hồ",
    "dong ho",
    "macbook",
    "ipad",
    "phụ kiện",
    "phu kien",
    "màn hình",
    "man hinh",
    "tivi",
    "tv",
    "máy ảnh",
    "may anh",
    "camera",
    "nồi chiên",
    "noi chien",
    "máy lạnh",
    "may lanh",
)


@dataclass(frozen=True)
class BudgetConstraint:
    min_vnd: int | None = None
    max_vnd: int | None = None
    category: str = ""

    @property
    def label(self) -> str:
        if self.min_vnd and self.max_vnd:
            return f"{_fmt_million(self.min_vnd)} – {_fmt_million(self.max_vnd)}"
        if self.max_vnd:
            return f"dưới {_fmt_million(self.max_vnd)}"
        if self.min_vnd:
            return f"trên {_fmt_million(self.min_vnd)}"
        return ""


def _fmt_million(vnd: int) -> str:
    trieu = vnd / 1_000_000
    if trieu == int(trieu):
        return f"{int(trieu)} triệu"
    return f"{trieu:.1f} triệu"


def _to_vnd(amount_str: str, unit: str = "") -> int:
    raw = amount_str.replace(",", ".")
    value = float(raw)
    unit_l = (unit or "").lower().strip()
    if unit_l in ("tỷ", "ty"):
        return int(value * 1_000_000_000)
    if unit_l in ("triệu", "trieu", "tr"):
        return int(value * 1_000_000)
    if unit_l in ("nghìn", "nghin", "k"):
        return int(value * 1_000)
    if unit_l in ("đ", "dong", "vnd"):
        return int(value)
    # Không có đơn vị — số nhỏ thường là triệu trong ngữ cảnh VN
    if value < 1000:
        return int(value * 1_000_000)
    return int(value)


def is_budget_browse_query(text: str) -> bool:
    """Câu hỏi tìm SP theo ngân sách / tầm giá."""
    value = (text or "").strip()
    if not value:
        return False
    if parse_budget_constraint(value) is not None:
        return True
    lower = value.lower()
    if re.search(r"\d+\s*k\b", lower) and _extract_category(value):
        return True
    return False


def parse_budget_constraint(text: str) -> BudgetConstraint | None:
    value = (text or "").strip()
    if not value:
        return None

    min_vnd: int | None = None
    max_vnd: int | None = None

    range_match = _BUDGET_RANGE_RE.search(value)
    if range_match:
        min_vnd = _to_vnd(range_match.group(1), "triệu")
        max_vnd = _to_vnd(range_match.group(2), "triệu")
    else:
        under = _BUDGET_UNDER_RE.search(value)
        if under:
            max_vnd = _to_vnd(under.group(1), "triệu")
        over = _BUDGET_OVER_RE.search(value)
        if over:
            min_vnd = _to_vnd(over.group(1), "triệu")
        tam = _BUDGET_TAM_GIA_RE.search(value)
        if tam and max_vnd is None and min_vnd is None:
            center = _to_vnd(tam.group(1), "triệu")
            min_vnd = int(center * 0.85)
            max_vnd = int(center * 1.15)
        k_under = _BUDGET_K_UNDER_RE.search(value)
        if k_under:
            max_vnd = int(k_under.group(1)) * 1_000
        elif max_vnd is None and min_vnd is None:
            k_only = _BUDGET_K_ONLY_RE.search(value)
            if k_only:
                max_vnd = int(k_only.group(1)) * 1_000

    if min_vnd is None and max_vnd is None:
        return None

    category = _extract_category(value)
    return BudgetConstraint(min_vnd=min_vnd, max_vnd=max_vnd, category=category)


def _extract_category(text: str) -> str:
    lower = text.lower()
    for hint in sorted(_CATEGORY_HINTS, key=len, reverse=True):
        if hint in lower:
            return hint
    return ""


def strip_budget_phrases_for_keywords(text: str) -> str:
    """Giữ danh mục/hãng + dung tích — bỏ cụm ngân sách."""
    value = (text or "").strip()
    for pattern in _BUDGET_STRIP_RES:
        value = pattern.sub(" ", value)
    value = re.sub(r"\s+", " ", value).strip(" ,.-")
    category = _extract_category(text)
    if category and category not in value.lower():
        value = f"{category} {value}".strip()
    return value or category


def price_from_display(price_str: str) -> int | None:
    digits = re.sub(r"[^\d]", "", price_str or "")
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def filter_results_by_budget(
    results: list[dict[str, Any]],
    constraint: BudgetConstraint,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for row in results:
        amount = price_from_display(str(row.get("price") or ""))
        if amount is None:
            continue
        if constraint.min_vnd is not None and amount < constraint.min_vnd:
            continue
        if constraint.max_vnd is not None and amount > constraint.max_vnd:
            continue
        filtered.append(row)
    return filtered
