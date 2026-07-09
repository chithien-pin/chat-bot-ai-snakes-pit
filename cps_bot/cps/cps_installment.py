"""
API trả góp CellphoneS — tham chiếu cps-nuxt-standard/store/installment-offers.js,
company-installment-quote.js, login.js (guest-token).
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any

import httpx

from config import (
    CPS_API_BASE_URL,
    CPS_PAYMENT_VER,
    CPS_PROVINCE_ID,
    CPS_SSO_GUEST_TOKEN_URL,
)
from cps_bot.cps.cps_api import (
    STOCK_AVAILABLE_PRE_ORDER,
    company_id_for_province,
    resolve_province_from_text,
)
from cps_bot.cps.cps_provinces import province_name
from cps_bot.cps.scraper import _format_price

logger = logging.getLogger(__name__)

_HTTP_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
}

# Map tên khách hỏi → key CTTC (installment-offers via_company.companies[].key)
FINANCE_COMPANY_ALIASES: dict[str, str] = {
    "home credit": "home_credit",
    "homecredit": "home_credit",
    "home-credit": "home_credit",
    "mcredit": "mcredit",
    "m credit": "mcredit",
    "fecredit": "fecredit",
    "fe credit": "fecredit",
    "hd saison": "hd_saison",
    "hd-saison": "hd_saison",
    "shinhan": "shinhan_finance",
    "lotte finance": "lotte_finance",
    "lotte": "lotte_finance",
    "mirae asset": "mirae_asset",
    "acs": "acs",
    "jaccs": "jaccs",
}

# Map tên khách hỏi → mã lọc ngân hàng (resolve SWIFT qua onepay list_bank)
BANK_ALIASES: dict[str, str] = {
    "vib": "VIB",
    "techcombank": "TCB",
    "tcb": "TCB",
    "vietcombank": "VCB",
    "vcb": "VCB",
    "mbbank": "MB",
    "mb bank": "MB",
    "bidv": "BIDV",
    "shb": "SHB",
    "sacombank": "STB",
    "hsbc": "HSBC",
    "home credit": "HOMECREDIT",
    "vietinbank": "VTB",
    "vtb": "VTB",
    "acb": "ACB",
    "vpbank": "VPB",
    "tpbank": "TPB",
    "msb": "MSB",
    "eximbank": "EXIM",
    "shinhan": "SHINHAN",
}

# Loại thẻ — khớp list_card trong payment-installment/info (onepay)
CARD_ALIASES: dict[str, str] = {
    "visa": "Visa",
    "mastercard": "Mastercard",
    "master card": "Mastercard",
    "master": "Mastercard",
    "jcb": "JCB",
    "american express": "American Express",
    "amex": "American Express",
    "napas": "Napas",
}

PAY_LATER_ALIASES: dict[str, str] = {
    "kredivo": "kredivo",
    "fundiin": "fundiin",
    "momo": "momo_vts",
    "momo vts": "momo_vts",
    "vay muon": "vaymuon",
}

CREDIT_CARD_METHOD_ALIASES: dict[str, str] = {
    "onepay": "onepay",
    "alepay": "alepay",
    "thẻ tín dụng": "onepay",
    "the tin dung": "onepay",
    "thẻ ngân hàng": "onepay",
    "the ngan hang": "onepay",
    "chuyển đổi trả góp": "onepay",
    "chuyen doi tra gop": "onepay",
}

_CREDIT_CARD_QUERY_RE = re.compile(
    r"\b("
    r"thẻ tín dụng|the tin dung|thẻ ngân hàng|the ngan hang|"
    r"chuyển đổi trả góp|chuyen doi tra gop|"
    r"onepay|visa|mastercard|jcb|napas"
    r")\b",
    re.IGNORECASE,
)

_guest_token_cache: dict[str, Any] = {"token": "", "expires_at": 0.0}


def _payment_base() -> str:
    base = CPS_API_BASE_URL.rstrip("/")
    ver = CPS_PAYMENT_VER.strip("/")
    return f"{base}/{ver}/payment-installment"


def _int_amount(value: Any) -> int | None:
    if value is None:
        return None
    try:
        amount = int(float(value))
    except (TypeError, ValueError):
        return None
    return amount if amount > 0 else None


def _float_rate(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def extract_installment_hints(text: str) -> dict[str, str]:
    """Trích CTTC / ngân hàng / ví trả sau khách đề cập."""
    lower = (text or "").lower()
    hints: dict[str, str] = {}
    for alias, key in sorted(FINANCE_COMPANY_ALIASES.items(), key=lambda x: -len(x[0])):
        if alias in lower:
            hints["finance_company"] = key
            break
    for alias, code in sorted(BANK_ALIASES.items(), key=lambda x: -len(x[0])):
        if alias in lower and alias not in ("home credit",):
            hints["bank"] = code
            break
    for alias, code in sorted(PAY_LATER_ALIASES.items(), key=lambda x: -len(x[0])):
        if alias in lower:
            hints["pay_later"] = code
            break
    for alias, code in sorted(CREDIT_CARD_METHOD_ALIASES.items(), key=lambda x: -len(x[0])):
        if alias in lower:
            hints["credit_card_method"] = code
            break
    for alias, card in sorted(CARD_ALIASES.items(), key=lambda x: -len(x[0])):
        if alias in lower:
            hints["card_type"] = card
            break
    term_match = re.search(r"(\d+)\s*tháng", lower)
    if term_match:
        hints["term_months"] = term_match.group(1)
    if re.search(r"\b0\s*%|0%|miễn lãi|mien lai", lower):
        hints["zero_interest"] = "1"
    if _CREDIT_CARD_QUERY_RE.search(lower) or hints.get("bank"):
        hints["credit_card"] = "1"
    return hints


def wants_credit_card_installment(hints: dict[str, str], user_question: str = "") -> bool:
    """Khách hỏi trả góp qua thẻ ngân hàng / OnePay."""
    if hints.get("credit_card") or hints.get("bank") or hints.get("credit_card_method"):
        return True
    return bool(_CREDIT_CARD_QUERY_RE.search(user_question or ""))


def is_installment_query(text: str) -> bool:
    """
    Câu liên quan trả góp — kể cả chỉ gửi bank/kỳ/loại thẻ (vd: 'hsbc 12 tháng VISA').
    """
    from cps_bot.cps.cps_api import _INSTALLMENT_QUESTION_RE

    t = (text or "").strip()
    if not t:
        return False
    if _INSTALLMENT_QUESTION_RE.search(t):
        return True
    hints = extract_installment_hints(t)
    if hints.get("finance_company") or hints.get("pay_later"):
        return True
    if hints.get("bank"):
        return True
    if hints.get("card_type") and hints.get("term_months"):
        return True
    if hints.get("bank") and (hints.get("term_months") or hints.get("card_type")):
        return True
    return False


_GENERAL_INSTALLMENT_RE = re.compile(
    r"\b("
    r"trả góp được|tra gop duoc|có gói trả góp|co goi tra gop|"
    r"hình thức trả góp|hinh thuc tra gop|các gói trả góp|cac goi tra gop|"
    r"những hình thức|nhung hinh thuc|có trả góp|co tra gop"
    r")\b",
    re.IGNORECASE,
)
_PAY_LATER_GENERIC_RE = re.compile(
    r"\b(mua trước trả sau|mua truoc tra sau)\b",
    re.IGNORECASE,
)
_LOWEST_PREPAY_RE = re.compile(
    r"\b("
    r"trả trước|tra truoc|ít nhất|it nhat|thấp nhất|thap nhat|"
    r"ưu đãi nhất|uu dai nhat|tốt nhất|tot nhat|rẻ nhất|re nhat"
    r")\b",
    re.IGNORECASE,
)

_CREDIT_CARD_REQUIRED = ("bank", "term_months", "card_type")


def is_general_installment_query(text: str) -> bool:
    return bool(_GENERAL_INSTALLMENT_RE.search(text or ""))


def classify_installment_fetch_intent(
    hints: dict[str, str],
    user_question: str = "",
) -> str:
    q = user_question or ""
    if hints.get("pay_later") or _PAY_LATER_GENERIC_RE.search(q):
        return "pay_later_calculate"
    if wants_credit_card_installment(hints, q):
        return "credit_card_calculate"
    if hints.get("finance_company"):
        return "finance_calculate"
    if _LOWEST_PREPAY_RE.search(q):
        return "lowest_prepaid"
    if is_general_installment_query(q):
        return "general"
    from cps_bot.cps.cps_api import _INSTALLMENT_QUESTION_RE

    if _INSTALLMENT_QUESTION_RE.search(q):
        return "general"
    return "general"


def _missing_field_labels() -> dict[str, str]:
    return {
        "bank": "ngân hàng phát hành thẻ",
        "term_months": "kỳ hạn trả góp (vd: 3, 6, 12 tháng)",
        "card_type": "loại thẻ (Visa, Mastercard, JCB…)",
        "finance_company": "công ty tài chính (Home Credit, MCredit…)",
        "pay_later_provider": "hình thức mua trước trả sau (Kredivo, Fundiin, Momo VTS)",
    }


def _build_clarification_message(
    missing: list[str],
    *,
    catalog: dict[str, Any] | None = None,
    hints: dict[str, str] | None = None,
) -> str:
    labels = _missing_field_labels()
    parts = [labels.get(field, field) for field in missing]
    msg = f"Để tính trả góp chính xác, bạn cho mình biết thêm: {'; '.join(parts)}."
    if "bank" in missing and catalog:
        names = [
            str(meta.get("short_name") or "")
            for meta in (catalog.get("banks_by_swift") or {}).values()
            if meta.get("short_name")
        ]
        if names:
            msg += f"\nNgân hàng OnePay hỗ trợ: {', '.join(names[:12])}"
            if len(names) > 12:
                msg += ", ..."
    if "card_type" in missing and catalog:
        cards = [
            str(c.get("name") or c.get("code") or "")
            for c in (catalog.get("list_card") or [])
            if c.get("name") or c.get("code")
        ]
        if cards:
            msg += f"\nLoại thẻ: {', '.join(cards)}."
    if "pay_later_provider" in missing:
        msg += "\nHình thức: Kredivo, Fundiin, hoặc Momo VTS."
    if hints and hints.get("finance_company") and "term_months" in missing:
        msg += f"\n(Bạn đang hỏi về {hints['finance_company']})"
    return msg


def assess_installment_query(
    user_question: str,
    hints: dict[str, str],
    *,
    catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    intent = classify_installment_fetch_intent(hints, user_question)
    missing: list[str] = []
    q = user_question or ""

    if intent == "credit_card_calculate":
        has_specific = any(hints.get(k) for k in _CREDIT_CARD_REQUIRED)
        if has_specific or not is_general_installment_query(q):
            for field in _CREDIT_CARD_REQUIRED:
                if not hints.get(field):
                    missing.append(field)
        else:
            missing.append("bank")

    elif intent == "finance_calculate":
        if not hints.get("term_months"):
            missing.append("term_months")

    elif intent == "pay_later_calculate":
        if not hints.get("pay_later"):
            missing.append("pay_later_provider")

    complete = not missing
    result: dict[str, Any] = {
        "intent": intent,
        "complete": complete,
        "missing_fields": missing,
        "needs_clarification": not complete,
    }
    if missing:
        result["clarification_message"] = _build_clarification_message(
            missing,
            catalog=catalog,
            hints=hints,
        )
    return result


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "").strip()


def _normalize_lookup(text: str) -> str:
    return re.sub(r"[\s\._-]+", "", (text or "").lower())


def build_onepay_catalog(info_raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """
    Danh mục ngân hàng/loại thẻ từ payment-installment/info → onepay.information.
    list_bank: code (SWIFT), short_name, full_name
    list_card: code, name, type (VC/MC/JC…)
    """
    if not info_raw or not isinstance(info_raw, dict):
        return None
    methods = info_raw.get("payment_methods") or []
    onepay = next(
        (m for m in methods if str(m.get("code") or "").lower() == "onepay"),
        None,
    )
    if not onepay or not isinstance(onepay, dict):
        return None

    information = onepay.get("information") or {}
    list_bank = information.get("list_bank") or []
    list_card = information.get("list_card") or []

    banks_by_swift: dict[str, dict[str, Any]] = {}
    bank_lookup: dict[str, set[str]] = {}

    def _register_bank_alias(key: str, swift: str) -> None:
        norm = _normalize_lookup(key)
        if norm and swift:
            bank_lookup.setdefault(norm, set()).add(swift.upper())

    for bank in list_bank:
        if not isinstance(bank, dict):
            continue
        swift = str(bank.get("code") or "").upper()
        if not swift:
            continue
        short_name = str(bank.get("short_name") or "").strip()
        full_name = str(bank.get("full_name") or "").strip()
        banks_by_swift[swift] = {
            "code": swift,
            "short_name": short_name,
            "full_name": full_name,
            "logo": bank.get("logo") or "",
        }
        for label in (swift, short_name, full_name):
            _register_bank_alias(label, swift)

    for alias, code in BANK_ALIASES.items():
        alias_norm = _normalize_lookup(alias)
        code_norm = _normalize_lookup(code)
        for swift, meta in banks_by_swift.items():
            short_norm = _normalize_lookup(meta.get("short_name") or "")
            full_norm = _normalize_lookup(meta.get("full_name") or "")
            if (
                alias_norm in short_norm
                or alias_norm in full_norm
                or code_norm in short_norm
                or short_norm.startswith(code_norm)
            ):
                _register_bank_alias(alias, swift)
                _register_bank_alias(code, swift)

    cards_by_code: dict[str, dict[str, Any]] = {}
    card_lookup: dict[str, str] = {}
    for card in list_card:
        if not isinstance(card, dict):
            continue
        code = str(card.get("code") or card.get("name") or "").strip()
        if not code:
            continue
        cards_by_code[code] = {
            "code": code,
            "name": str(card.get("name") or code),
            "type": str(card.get("type") or ""),
            "logo": card.get("logo") or "",
        }
        for label in (code, card.get("name") or ""):
            card_lookup[_normalize_lookup(str(label))] = code

    for alias, canonical in CARD_ALIASES.items():
        card_lookup[_normalize_lookup(alias)] = canonical

    return {
        "banks_by_swift": banks_by_swift,
        "bank_lookup": bank_lookup,
        "cards_by_code": cards_by_code,
        "card_lookup": card_lookup,
        "list_bank": list_bank,
        "list_card": list_card,
    }


def resolve_bank_swifts(
    bank_filter: str | None,
    catalog: dict[str, Any] | None,
) -> set[str] | None:
    """Map mã/tên ngân hàng khách hỏi → SWIFT code từ onepay list_bank."""
    if not bank_filter or not catalog:
        return None
    lookup = catalog.get("bank_lookup") or {}
    keys = [
        _normalize_lookup(bank_filter),
        _normalize_lookup(BANK_ALIASES.get(bank_filter.lower(), bank_filter)),
    ]
    swifts: set[str] = set()
    for key in keys:
        if key in lookup:
            swifts.update(lookup[key])

    if not swifts:
        alias = bank_filter.lower()
        for swift, meta in (catalog.get("banks_by_swift") or {}).items():
            short = (meta.get("short_name") or "").lower()
            full = (meta.get("full_name") or "").lower()
            if alias in short or alias in full:
                swifts.add(swift)
    return swifts or None


def resolve_card_code(
    card_filter: str | None,
    catalog: dict[str, Any] | None,
) -> str | None:
    if not card_filter or not catalog:
        return card_filter
    lookup = catalog.get("card_lookup") or {}
    keys = [
        _normalize_lookup(card_filter),
        _normalize_lookup(CARD_ALIASES.get(card_filter.lower(), card_filter)),
    ]
    for key in keys:
        if key in lookup:
            return lookup[key]
    return card_filter


def _bank_meta_from_catalog(
    swift: str,
    catalog: dict[str, Any] | None,
) -> dict[str, str]:
    if catalog:
        meta = (catalog.get("banks_by_swift") or {}).get(swift.upper())
        if meta:
            return {
                "short_name": str(meta.get("short_name") or ""),
                "full_name": str(meta.get("full_name") or ""),
            }
    return {"short_name": "", "full_name": ""}


def _summarize_onepay_catalog(catalog: dict[str, Any] | None) -> dict[str, Any]:
    if not catalog:
        return {}
    banks = [
        {
            "code": meta.get("code"),
            "short_name": meta.get("short_name"),
            "full_name": meta.get("full_name"),
        }
        for meta in (catalog.get("banks_by_swift") or {}).values()
    ]
    cards = [
        {
            "code": meta.get("code"),
            "name": meta.get("name"),
            "type": meta.get("type"),
        }
        for meta in (catalog.get("cards_by_code") or {}).values()
    ]
    return {"list_bank": banks, "list_card": cards}


def _summarize_installment_info(data: dict[str, Any] | None) -> dict[str, Any]:
    """Tóm tắt GET payment-installment/info — danh mục CTTC & hình thức trả góp."""
    if not data or not isinstance(data, dict):
        return {}
    companies: list[dict[str, Any]] = []
    for co in data.get("companies") or []:
        if not isinstance(co, dict) or co.get("is_active") is False:
            continue
        info = co.get("information") or {}
        docs = _strip_html(str(info.get("required_documents") or ""))
        companies.append(
            {
                "key": co.get("key"),
                "name": co.get("name"),
                "term_months": co.get("term_in_months") or [],
                "min_prepaid_percent": co.get("min_prepaid_percent"),
                "max_prepaid_percent": co.get("max_prepaid_percent"),
                "monthly_interest_rate": co.get("monthly_interest_rate"),
                "min_installment_price": co.get("min_installment_price"),
                "max_installment_price": co.get("max_installment_price"),
                "default_term": info.get("default_term"),
                "default_prepaid_percent": info.get("default_prepaid_percent"),
                "required_documents_summary": docs[:400] if docs else "",
            }
        )
    methods: list[dict[str, Any]] = []
    for m in data.get("payment_methods") or []:
        if not isinstance(m, dict):
            continue
        methods.append(
            {
                "code": m.get("code"),
                "name": m.get("name") or m.get("title"),
                "title": m.get("title") or m.get("name"),
                "min_installment_amount": m.get("min_installment_amount"),
                "max_installment_amount": m.get("max_installment_amount"),
            }
        )
    onepay_catalog = build_onepay_catalog(data)
    summary: dict[str, Any] = {
        "finance_companies_catalog": companies,
        "payment_methods_catalog": methods,
    }
    if onepay_catalog:
        summary["onepay"] = _summarize_onepay_catalog(onepay_catalog)
    return summary


async def fetch_installment_info() -> dict[str, Any] | None:
    """Danh mục CTTC + hình thức trả góp — GET payment-installment/info."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            f"{_payment_base()}/info",
            headers={**_HTTP_HEADERS, "x-client-type": "web"},
        )
        response.raise_for_status()
        return response.json()


def _resolve_credit_card_method_codes(
    via_card: dict[str, Any],
    hints: dict[str, str],
) -> list[str]:
    """Chọn cổng tính thẻ — ưu tiên onepay (Visa/Master/JCB/Napas trên web)."""
    from_offers = [
        str(m.get("code")).strip().lower()
        for m in (via_card.get("payment_methods") or [])
        if isinstance(m, dict) and m.get("code")
    ]
    requested = (hints.get("credit_card_method") or "").strip().lower()
    if requested:
        if requested in from_offers:
            return [requested]
        if requested in ("onepay", "alepay"):
            return [requested]
    if "onepay" in from_offers:
        return ["onepay"]
    return from_offers[:2] or ["onepay"]


def _promotion_pack_id_from_detail(detail: dict[str, Any]) -> str | None:
    promos = detail.get("promotions") or {}
    km_rieng = promos.get("km_rieng") or []
    if isinstance(km_rieng, list) and km_rieng:
        first = km_rieng[0]
        if isinstance(first, dict) and first.get("id"):
            return str(first["id"])
    return None


async def get_guest_token(*, force_refresh: bool = False) -> str:
    """Guest token — POST sso/v1/auth/guest-token (cache ~50 phút)."""
    now = time.time()
    if (
        not force_refresh
        and _guest_token_cache.get("token")
        and now < float(_guest_token_cache.get("expires_at") or 0)
    ):
        return str(_guest_token_cache["token"])

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(CPS_SSO_GUEST_TOKEN_URL, headers=_HTTP_HEADERS)
        response.raise_for_status()
        payload = response.json()

    data = payload.get("data") if isinstance(payload, dict) else {}
    token = ""
    expires_in = 3600
    if isinstance(data, dict):
        token = str(data.get("token") or "")
        try:
            expires_in = int(data.get("expires_in") or 3600)
        except (TypeError, ValueError):
            expires_in = 3600
    if not token:
        raise ValueError("Không lấy được guest_token từ SSO")

    _guest_token_cache["token"] = token
    _guest_token_cache["expires_at"] = now + max(expires_in - 600, 300)
    return token


async def fetch_installment_offers(
    *,
    product_id: str | int,
    province_id: int,
    company_id: int,
    promotion_pack_id: str | None = None,
    token: str | None = None,
) -> dict[str, Any] | None:
    auth = token or await get_guest_token()
    params: dict[str, Any] = {
        "product_id": int(product_id),
        "province_id": province_id,
        "company_id": company_id,
        "is_quote": "false",
    }
    if promotion_pack_id:
        params["promotion_pack_id"] = promotion_pack_id

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{_payment_base()}/installment-offers",
            params=params,
            headers={**_HTTP_HEADERS, "Authorization": f"Bearer {auth}"},
        )
        response.raise_for_status()
        return response.json()


async def fetch_company_calculate(
    *,
    product_id: str | int,
    province_id: int,
    company_key: str,
    term: int,
    prepaid_percent: float | int,
    promotion_pack_id: str | None = None,
    has_insurance: bool = False,
    token: str | None = None,
) -> dict[str, Any] | None:
    auth = token or await get_guest_token()
    params: dict[str, Any] = {
        "product_id": int(product_id),
        "province_id": province_id,
        "key": company_key,
        "term": term,
        "prepaid_percent": prepaid_percent,
        "has_insurance": str(has_insurance).lower(),
        "is_quote": "false",
    }
    if promotion_pack_id:
        params["promotion_pack_id"] = promotion_pack_id

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{_payment_base()}/company-calculate",
            params=params,
            headers={**_HTTP_HEADERS, "Authorization": f"Bearer {auth}"},
        )
        response.raise_for_status()
        return response.json()


async def fetch_online_calculate(
    payment_key: str,
    *,
    product_id: str | int,
    province_id: int,
    company_id: int,
    amount: int | float | None = None,
    promotion_pack_id: str | None = None,
    prepaid_percent: float | None = None,
    token: str | None = None,
) -> dict[str, Any] | None:
    """Thẻ tín dụng (onepay/alepay) và ví trả sau (kredivo/fundiin/momo_vts)."""
    auth = token or await get_guest_token()
    params: dict[str, Any] = {
        "product_id": int(product_id),
        "province_id": province_id,
        "company_id": company_id,
        "is_quote": "false",
    }
    if amount is not None:
        params["amount"] = amount
    if promotion_pack_id:
        params["promotion_pack_id"] = promotion_pack_id
    if prepaid_percent is not None:
        params["prepaid_percent"] = prepaid_percent

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{_payment_base()}/online-calculate/{payment_key}",
            params=params,
            headers={**_HTTP_HEADERS, "Authorization": f"Bearer {auth}"},
        )
        response.raise_for_status()
        return response.json()


def _normalize_best_package(item: dict[str, Any], companies: list[dict[str, Any]]) -> dict[str, Any]:
    company_code = str(
        item.get("company_code") or item.get("company") or item.get("key") or ""
    ).strip()
    company_name = str(item.get("company") or item.get("company_name") or "")
    if not company_name and company_code:
        for co in companies:
            if str(co.get("key") or "") == company_code:
                company_name = str(co.get("name") or company_code)
                break

    prepaid = _int_amount(item.get("prepaid_amount"))
    monthly = _int_amount(item.get("monthly"))
    rate = _float_rate(item.get("monthly_rate"))
    term = _int_amount(item.get("term"))

    row: dict[str, Any] = {
        "company_key": company_code,
        "company_name": company_name or company_code,
        "term_months": term,
        "prepaid_percent": item.get("prepaid_percent"),
        "prepaid_amount": prepaid,
        "prepaid_amount_formatted": _format_price(prepaid) if prepaid else "",
        "monthly_payment": monthly,
        "monthly_payment_formatted": _format_price(monthly) if monthly else "",
        "monthly_rate": rate,
        "is_zero_percent": rate == 0.0 if rate is not None else False,
    }
    return row


def _parse_best_zero_percent(
    best_interest_rate: list[Any],
    companies: list[dict[str, Any]],
    *,
    company_key: str | None = None,
) -> list[dict[str, Any]]:
    packages: list[dict[str, Any]] = []
    for item in best_interest_rate or []:
        if not isinstance(item, dict):
            continue
        pkg = _normalize_best_package(item, companies)
        rate = pkg.get("monthly_rate")
        if rate is not None and rate != 0.0:
            continue
        if company_key and pkg.get("company_key") != company_key:
            continue
        packages.append(pkg)
    packages.sort(key=lambda p: int(p.get("prepaid_amount") or 999999999999))
    return packages


def _summarize_companies(companies: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for co in companies or []:
        if not isinstance(co, dict):
            continue
        if co.get("is_active") is False:
            continue
        rows.append(
            {
                "key": co.get("key"),
                "name": co.get("name"),
                "min_prepaid_percent": co.get("min_prepaid_percent"),
                "max_prepaid_percent": co.get("max_prepaid_percent"),
                "default_term": (co.get("information") or {}).get("default_term"),
            }
        )
    return rows


def _parse_kredivo_terms(response: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not response or not isinstance(response, dict):
        return []
    if response.get("error") and response.get("message_error"):
        return [{"error": str(response.get("message_error"))}]

    terms: list[dict[str, Any]] = []
    for month_key, data in response.items():
        if not str(month_key).isdigit() or not isinstance(data, dict):
            continue
        rate = data.get("interest_rate")
        monthly = _int_amount(data.get("monthly_installment"))
        terms.append(
            {
                "term_months": int(month_key),
                "interest_rate": rate,
                "monthly_payment": monthly,
                "monthly_payment_formatted": _format_price(monthly) if monthly else "",
                "total_payment": _int_amount(data.get("payback_amount")),
                "processing_fee": _int_amount(data.get("processing_fee")),
                "is_zero_percent": str(rate) in ("0", "0.0", "0%") or rate == 0,
            }
        )
    terms.sort(key=lambda t: t.get("term_months") or 0)
    return terms


def _parse_card_period_rows(
    card_info: dict[str, Any],
    *,
    zero_fee_only: bool = True,
) -> list[dict[str, Any]]:
    """Parse kỳ trả góp từ card — hỗ trợ onepay v3 (times) và legacy (periods)."""
    rows: list[dict[str, Any]] = []
    times = card_info.get("times")
    if isinstance(times, list) and times:
        for row in times:
            if not isinstance(row, dict):
                continue
            fee = _int_amount(row.get("fee_amount"))
            if zero_fee_only and fee is not None and fee > 0:
                continue
            term = _int_amount(row.get("time"))
            monthly = _int_amount(row.get("monthly_amount"))
            total = (monthly or 0) * (term or 0) if monthly and term else None
            rows.append(
                {
                    "term_months": term,
                    "monthly_payment": monthly,
                    "monthly_payment_formatted": _format_price(monthly) if monthly else "",
                    "fee_amount": fee or 0,
                    "fee_amount_formatted": _format_price(fee) if fee else "0₫",
                    "total_payment": total,
                    "total_payment_formatted": _format_price(total) if total else "",
                    "is_zero_fee": not fee,
                }
            )
        return rows

    periods = card_info.get("periods") or {}
    if isinstance(periods, dict):
        for month, period in periods.items():
            if not isinstance(period, dict):
                continue
            fee = period.get("fee") or period.get("fee_percent") or period.get("interest")
            fee_num = _float_rate(fee)
            fee_amt = _int_amount(period.get("fee_amount"))
            if zero_fee_only:
                if fee_num is not None and fee_num != 0:
                    continue
                if fee_amt is not None and fee_amt > 0:
                    continue
            term = _int_amount(month) or month
            monthly = _int_amount(period.get("monthly") or period.get("monthly_payment"))
            total = (monthly or 0) * int(term or 0) if monthly and term else None
            rows.append(
                {
                    "term_months": term,
                    "monthly_payment": monthly,
                    "monthly_payment_formatted": _format_price(monthly) if monthly else "",
                    "fee_amount": fee_amt or 0,
                    "fee_amount_formatted": _format_price(fee_amt) if fee_amt else "0₫",
                    "total_payment": total,
                    "total_payment_formatted": _format_price(total) if total else "",
                    "is_zero_fee": not fee_amt,
                }
            )
    return rows


def _bank_swift_id(bank_code: str, bank_data: dict[str, Any]) -> str:
    return str(bank_data.get("bank_id") or bank_code or "").upper()


def _card_matches_filter(
    card_code: str,
    card_info: dict[str, Any],
    card_filter: str | None,
    catalog: dict[str, Any] | None,
) -> bool:
    if not card_filter:
        return True
    resolved = resolve_card_code(card_filter, catalog) or card_filter
    name = str(card_info.get("name") or card_code)
    filter_norm = _normalize_lookup(resolved)
    return filter_norm in {_normalize_lookup(card_code), _normalize_lookup(name)}


def _bank_matches_filter(
    bank_code: str,
    bank_data: dict[str, Any],
    *,
    bank_filter: str | None = None,
    allowed_swifts: set[str] | None = None,
    catalog: dict[str, Any] | None = None,
) -> bool:
    swift = _bank_swift_id(bank_code, bank_data)
    if allowed_swifts is not None:
        return swift in allowed_swifts
    if not bank_filter:
        return True
    resolved = resolve_bank_swifts(bank_filter, catalog)
    if resolved:
        return swift in resolved
    return False


def _parse_credit_card_banks(
    response: dict[str, Any] | None,
    *,
    bank_filter: str | None = None,
    card_filter: str | None = None,
    term_months: int | None = None,
    catalog: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Tóm tắt gói trả góp thẻ OnePay — map bank/card từ list_bank & list_card."""
    if not response or not isinstance(response, dict):
        return []

    allowed_swifts = resolve_bank_swifts(bank_filter, catalog) if bank_filter else None
    resolved_card = resolve_card_code(card_filter, catalog) if card_filter else None

    banks: list[dict[str, Any]] = []
    for bank_code, bank_data in response.items():
        if not isinstance(bank_data, dict):
            continue
        if not _bank_matches_filter(
            bank_code,
            bank_data,
            bank_filter=bank_filter,
            allowed_swifts=allowed_swifts,
            catalog=catalog,
        ):
            continue

        list_cards = bank_data.get("listCards") or {}
        cards_detail: list[dict[str, Any]] = []
        if isinstance(list_cards, dict):
            for card_code, card_info in list_cards.items():
                if not isinstance(card_info, dict):
                    continue
                if not _card_matches_filter(card_code, card_info, resolved_card, catalog):
                    continue
                catalog_card = (catalog or {}).get("cards_by_code", {}).get(card_code) or {}
                card_name = str(card_info.get("name") or catalog_card.get("name") or card_code)
                all_periods = _parse_card_period_rows(card_info, zero_fee_only=False)
                zero_periods = _parse_card_period_rows(card_info, zero_fee_only=True)
                card_row: dict[str, Any] = {
                    "card_code": card_code,
                    "card_name": card_name,
                    "card_type": str(
                        card_info.get("type") or catalog_card.get("type") or ""
                    ),
                    "all_periods": all_periods,
                    "zero_fee_periods": zero_periods,
                }
                if term_months:
                    matched = [p for p in all_periods if p.get("term_months") == term_months]
                    card_row["requested_term_months"] = term_months
                    card_row["requested_term_periods"] = matched
                if zero_periods or (term_months and card_row.get("requested_term_periods")):
                    cards_detail.append(card_row)

        if not cards_detail:
            continue

        # Tóm tắt gộp theo kỳ (ưu tiên thẻ khách hỏi nếu có)
        card_periods: list[dict[str, Any]] = []
        for card in cards_detail:
            for period in card.get("zero_fee_periods") or []:
                card_periods.append({**period, "card_type": card.get("card_name")})

        by_term: dict[Any, dict[str, Any]] = {}
        for row in card_periods:
            term = row.get("term_months")
            monthly = row.get("monthly_payment") or 0
            prev = by_term.get(term)
            if not prev or monthly < (prev.get("monthly_payment") or 0):
                by_term[term] = row

        zero_periods = sorted(by_term.values(), key=lambda r: int(r.get("term_months") or 0))
        swift = _bank_swift_id(bank_code, bank_data)
        meta = _bank_meta_from_catalog(swift, catalog)
        short_name = meta.get("short_name") or swift
        display_name = short_name or meta.get("full_name") or swift
        row: dict[str, Any] = {
            "bank_code": swift,
            "bank_id": bank_data.get("bank_id") or swift,
            "short_name": short_name,
            "full_name": meta.get("full_name") or "",
            "bank_name": display_name,
            "bank_display_name": display_name,
            "card_types": sorted({c.get("card_name") or c.get("card_code") for c in cards_detail}),
            "cards": cards_detail,
            "zero_fee_periods": zero_periods[:8],
        }
        if term_months:
            matched = [p for p in zero_periods if p.get("term_months") == term_months]
            row["requested_term_months"] = term_months
            row["requested_term_periods"] = matched
            if resolved_card:
                for card in cards_detail:
                    if card.get("requested_term_periods"):
                        row["requested_card"] = card.get("card_name")
                        row["requested_term_periods"] = card["requested_term_periods"]
                        break
        banks.append(row)
    return banks


def _company_calculate_summary(data: dict[str, Any] | None) -> dict[str, Any]:
    if not data:
        return {}
    prepaid = _int_amount(data.get("prepaid_amount"))
    monthly = _int_amount(data.get("monthly"))
    rate = _float_rate(data.get("monthly_rate"))
    return {
        "prepaid_amount": prepaid,
        "prepaid_amount_formatted": _format_price(prepaid) if prepaid else "",
        "prepaid_percent": data.get("prepaid_percent"),
        "term_months": _int_amount(data.get("term")),
        "monthly_payment": monthly,
        "monthly_payment_formatted": _format_price(monthly) if monthly else "",
        "monthly_rate": rate,
        "is_zero_percent": rate == 0.0 if rate is not None else False,
        "applied_price": _int_amount(data.get("applied_price")),
        "total_with_install": _int_amount(data.get("total_with_install")),
    }


async def fetch_installment_context(
    detail: dict[str, Any],
    *,
    user_question: str = "",
    province_id: int | None = None,
) -> dict[str, Any]:
    """
    Gói dữ liệu trả góp đầy đủ cho Gemini — CTTC, thẻ, ví trả sau.
    """
    hints = extract_installment_hints(user_question)
    pid_province = province_id or resolve_province_from_text(user_question) or CPS_PROVINCE_ID
    company_id = company_id_for_province(pid_province)
    product_id = detail.get("product_id")
    sale_price = detail.get("price_value")

    ctx: dict[str, Any] = {
        "province_id": pid_province,
        "province_name": province_name(pid_province) or str(pid_province),
        "product_name": detail.get("name") or "",
        "sale_price": sale_price,
        "sale_price_formatted": detail.get("price") or _format_price(sale_price),
        "hints": hints,
    }

    onepay_catalog: dict[str, Any] | None = None
    try:
        info_raw = await fetch_installment_info()
        onepay_catalog = build_onepay_catalog(info_raw)
        info_summary = _summarize_installment_info(info_raw)
        if info_summary:
            ctx["installment_info"] = info_summary
    except Exception as exc:
        logger.warning("payment-installment/info lỗi: %s", exc)
        info_raw = None
        onepay_catalog = None

    query_assessment = assess_installment_query(
        user_question,
        hints,
        catalog=onepay_catalog,
    )
    ctx["query_assessment"] = query_assessment
    fetch_intent = query_assessment.get("intent") or "general"
    fetch_complete = bool(query_assessment.get("complete"))
    if query_assessment.get("needs_clarification"):
        ctx["needs_clarification"] = True
        ctx["missing_fields"] = query_assessment.get("missing_fields") or []
        ctx["clarification_message"] = query_assessment.get("clarification_message") or ""

    stock_available_id = detail.get("stock_available_id")
    if stock_available_id == STOCK_AVAILABLE_PRE_ORDER:
        ctx["available"] = False
        ctx["reason"] = "Sản phẩm đặt trước — thường không hỗ trợ trả góp."
        return ctx

    if detail.get("is_installment") is False:
        ctx["available"] = False
        ctx["reason"] = "Sản phẩm không hỗ trợ trả góp trên CellphoneS."
        return ctx

    if not product_id:
        ctx["available"] = False
        ctx["reason"] = "Không xác định được product_id."
        return ctx

    promotion_pack_id = _promotion_pack_id_from_detail(detail)

    try:
        token = await get_guest_token()
        offers = await fetch_installment_offers(
            product_id=product_id,
            province_id=pid_province,
            company_id=company_id,
            promotion_pack_id=promotion_pack_id,
            token=token,
        )
    except Exception as exc:
        logger.warning("installment-offers lỗi: %s", exc)
        ctx["available"] = False
        ctx["reason"] = f"Không gọi được API trả góp: {exc}"
        ctx["fallback"] = detail.get("promotion_info") or ""
        return ctx

    if not offers:
        ctx["available"] = False
        ctx["reason"] = "API trả góp không trả dữ liệu."
        return ctx

    ctx["available"] = True
    ctx["promotion_pack_id"] = promotion_pack_id

    via_company = offers.get("via_company") or {}
    companies_raw = via_company.get("companies") or []
    best_interest = via_company.get("best_interest_rate") or []
    companies_summary = _summarize_companies(companies_raw)

    requested_fc = hints.get("finance_company")
    zero_packages = _parse_best_zero_percent(
        best_interest, companies_raw, company_key=requested_fc
    )
    if not zero_packages and requested_fc:
        zero_packages = _parse_best_zero_percent(best_interest, companies_raw)
    elif not zero_packages:
        zero_packages = _parse_best_zero_percent(best_interest, companies_raw)[:8]

    finance_block: dict[str, Any] = {
        "installment_note": via_company.get("installment_note") or "",
        "companies": companies_summary,
        "best_zero_percent_packages": zero_packages[:10],
    }

    # Chi tiết company-calculate cho CTTC được hỏi hoặc gói 0% rẻ nhất
    def _resolve_prepaid_percent(company_key: str, co: dict[str, Any] | None) -> float:
        for pkg in zero_packages:
            if pkg.get("company_key") == company_key and pkg.get("prepaid_percent") is not None:
                return float(pkg["prepaid_percent"])
        if co:
            pct = co.get("min_prepaid_percent")
            if pct is not None and float(pct) > 0:
                return float(pct)
            default_pct = (co.get("information") or {}).get("default_prepaid_percent")
            if default_pct is not None and float(default_pct) > 0:
                return float(default_pct)
        return 20.0

    calc_targets: list[tuple[str, int, float]] = []
    if fetch_complete and fetch_intent == "finance_calculate" and requested_fc:
        co = next((c for c in companies_raw if c.get("key") == requested_fc), None)
        if co:
            term = int(hints.get("term_months") or 6)
            pct = _resolve_prepaid_percent(requested_fc, co)
            calc_targets.append((requested_fc, term, pct))

    company_details: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for key, term, pct in calc_targets[:4]:
        if key in seen_keys:
            continue
        seen_keys.add(key)
        try:
            calc = await fetch_company_calculate(
                product_id=product_id,
                province_id=pid_province,
                company_key=key,
                term=term,
                prepaid_percent=pct,
                promotion_pack_id=promotion_pack_id,
                token=token,
            )
            summary = _company_calculate_summary(calc)
            if summary:
                co_name = next(
                    (c.get("name") for c in companies_raw if c.get("key") == key),
                    key,
                )
                company_details.append({"company_key": key, "company_name": co_name, **summary})
        except Exception as exc:
            logger.warning("company-calculate %s lỗi: %s", key, exc)

    finance_block["calculated_packages"] = company_details
    ctx["finance_companies"] = finance_block

    # --- Thẻ tín dụng ---
    via_card = offers.get("via_credit_card") or {}
    card_methods = via_card.get("payment_methods") or []
    card_block: dict[str, Any] = {
        "installment_note": via_card.get("installment_note") or "",
        "payment_methods": [
            {"code": m.get("code"), "name": m.get("name") or m.get("title")}
            for m in card_methods
            if isinstance(m, dict)
        ],
    }
    bank_filter = hints.get("bank")
    card_filter = hints.get("card_type")
    requested_term = _int_amount(hints.get("term_months"))
    card_amount = _int_amount(sale_price)
    card_summaries: list[dict[str, Any]] = []
    credit_card_query = wants_credit_card_installment(hints, user_question)
    method_codes = _resolve_credit_card_method_codes(via_card, hints)
    should_fetch_card = (
        fetch_complete
        and fetch_intent == "credit_card_calculate"
        and card_amount
        and credit_card_query
    )
    if should_fetch_card:
        for method_code in method_codes:
            if not method_code:
                continue
            try:
                card_resp = await fetch_online_calculate(
                    method_code,
                    product_id=product_id,
                    province_id=pid_province,
                    company_id=company_id,
                    amount=card_amount,
                    promotion_pack_id=promotion_pack_id,
                    token=token,
                )
                banks = _parse_credit_card_banks(
                    card_resp,
                    bank_filter=bank_filter,
                    card_filter=card_filter,
                    term_months=requested_term,
                    catalog=onepay_catalog,
                )
                if banks:
                    card_summaries.append(
                        {
                            "method": method_code,
                            "amount_used": card_amount,
                            "amount_formatted": _format_price(card_amount),
                            "banks": banks,
                        }
                    )
            except Exception as exc:
                logger.warning("online-calculate/%s lỗi: %s", method_code, exc)
    elif credit_card_query and not fetch_complete:
        card_block["awaiting_fields"] = query_assessment.get("missing_fields") or []
    card_block["zero_fee_by_bank"] = card_summaries
    if onepay_catalog:
        card_block["onepay_catalog"] = _summarize_onepay_catalog(onepay_catalog)
    if bank_filter:
        card_block["requested_bank"] = bank_filter
        resolved_swifts = resolve_bank_swifts(bank_filter, onepay_catalog)
        if resolved_swifts:
            card_block["requested_bank_swift"] = sorted(resolved_swifts)
            if onepay_catalog:
                card_block["requested_bank_names"] = [
                    (onepay_catalog.get("banks_by_swift") or {})
                    .get(swift, {})
                    .get("short_name")
                    or swift
                    for swift in sorted(resolved_swifts)
                ]
    if card_filter:
        card_block["requested_card"] = resolve_card_code(card_filter, onepay_catalog) or card_filter
    if requested_term:
        card_block["requested_term_months"] = requested_term
    if credit_card_query and fetch_complete and not card_summaries and card_amount:
        card_block["note"] = (
            "Không lấy được bảng trả góp thẻ OnePay cho sản phẩm này — "
            "gợi ý khách xem modal trả góp trên trang sản phẩm."
        )
    ctx["credit_card"] = card_block

    # --- Ví trả sau (Kredivo, Fundiin, Momo…) ---
    via_pay_later = offers.get("via_pay_later") or {}
    pay_methods = via_pay_later.get("payment_methods") or []
    pay_block: dict[str, Any] = {
        "installment_note": via_pay_later.get("installment_note") or "",
        "payment_methods": [
            {"code": m.get("code"), "name": m.get("name") or m.get("title")}
            for m in pay_methods
            if isinstance(m, dict)
        ],
    }

    pay_targets: list[str] = []
    if fetch_complete and fetch_intent == "pay_later_calculate" and hints.get("pay_later"):
        pay_targets.append(hints["pay_later"])
    elif not fetch_complete and fetch_intent == "pay_later_calculate":
        pay_block["awaiting_fields"] = query_assessment.get("missing_fields") or []

    pay_details: dict[str, Any] = {}
    for code in pay_targets[:3]:
        method = next((m for m in pay_methods if m.get("code") == code), None)
        amount: int | None = None
        if method and isinstance(method.get("options"), list) and method["options"]:
            first_opt = method["options"][0]
            if isinstance(first_opt, dict):
                amount = _int_amount(first_opt.get("value") or first_opt.get("amount"))
        if amount is None:
            amount = _int_amount(sale_price)
        try:
            resp = await fetch_online_calculate(
                code,
                product_id=product_id,
                province_id=pid_province,
                company_id=company_id,
                amount=amount,
                promotion_pack_id=promotion_pack_id,
                prepaid_percent=0.3 if code == "fundiin" else None,
                token=token,
            )
            if code == "kredivo":
                pay_details[code] = {
                    "amount_used": amount,
                    "terms": _parse_kredivo_terms(resp),
                }
            elif isinstance(resp, dict):
                pay_details[code] = {"amount_used": amount, "raw_keys": list(resp.keys())[:10]}
        except Exception as exc:
            logger.warning("online-calculate/%s lỗi: %s", code, exc)

    pay_block["details"] = pay_details
    ctx["pay_later"] = pay_block

    # Tóm tắt trả trước thấp nhất (gói 0%) — trả lời trực tiếp câu CSV
    candidates: list[tuple[int, str, dict[str, Any]]] = []
    for pkg in zero_packages:
        amt = _int_amount(pkg.get("prepaid_amount"))
        if amt:
            label = (
                f"{pkg.get('company_name')} {pkg.get('term_months')} tháng "
                f"({pkg.get('monthly_rate') or 0}%/tháng)"
            )
            candidates.append((amt, label, pkg))
    for det in company_details:
        if det.get("is_zero_percent"):
            amt = _int_amount(det.get("prepaid_amount"))
            if amt:
                label = (
                    f"{det.get('company_name')} {det.get('term_months')} tháng "
                    f"(company-calculate)"
                )
                candidates.append((amt, label, det))

    if candidates and not (
        query_assessment.get("needs_clarification")
        and fetch_intent
        in ("credit_card_calculate", "finance_calculate", "pay_later_calculate")
    ):
        candidates.sort(key=lambda x: x[0])
        best_amt, best_label, best_pkg = candidates[0]
        ctx["lowest_zero_prepaid"] = {
            "amount": best_amt,
            "amount_formatted": _format_price(best_amt),
            "source": best_label,
            "package": best_pkg,
        }

    ctx["note"] = (
        "Giá trả góp tham chiếu API payment-installment CellphoneS; "
        "chưa gồm chiết khấu Smember nếu khách chưa đăng nhập."
    )
    return ctx
