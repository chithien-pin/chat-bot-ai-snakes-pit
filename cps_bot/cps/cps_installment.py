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

# Map tên ngân hàng → mã trong response online-calculate
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
    "thẻ tín dụng": "alepay",
    "the tin dung": "alepay",
}

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
    term_match = re.search(r"(\d+)\s*tháng", lower)
    if term_match:
        hints["term_months"] = term_match.group(1)
    if re.search(r"\b0\s*%|0%|miễn lãi|mien lai", lower):
        hints["zero_interest"] = "1"
    return hints


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


def _parse_credit_card_banks(
    response: dict[str, Any] | None,
    *,
    bank_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Tóm tắt gói trả góp thẻ — lọc ngân hàng nếu khách hỏi VIB/TCB…"""
    if not response or not isinstance(response, dict):
        return []

    banks: list[dict[str, Any]] = []
    for bank_code, bank_data in response.items():
        if not isinstance(bank_data, dict):
            continue
        code_upper = str(bank_code).upper()
        if bank_filter and bank_filter.upper() not in code_upper:
            continue

        zero_periods: list[dict[str, Any]] = []
        list_cards = bank_data.get("listCards") or {}
        if isinstance(list_cards, dict):
            for _card_code, card_info in list_cards.items():
                if not isinstance(card_info, dict):
                    continue
                periods = card_info.get("periods") or {}
                if not isinstance(periods, dict):
                    continue
                for month, period in periods.items():
                    if not isinstance(period, dict):
                        continue
                    fee = period.get("fee") or period.get("fee_percent") or period.get("interest")
                    fee_num = _float_rate(fee)
                    if fee_num is not None and fee_num != 0:
                        continue
                    monthly = _int_amount(
                        period.get("monthly") or period.get("monthly_payment")
                    )
                    zero_periods.append(
                        {
                            "term_months": _int_amount(month) or month,
                            "monthly_payment": monthly,
                            "monthly_payment_formatted": _format_price(monthly)
                            if monthly
                            else "",
                        }
                    )

        if zero_periods:
            banks.append(
                {
                    "bank_code": bank_code,
                    "zero_fee_periods": zero_periods[:6],
                }
            )
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
    if requested_fc:
        co = next((c for c in companies_raw if c.get("key") == requested_fc), None)
        if co:
            term = int(
                hints.get("term_months")
                or (co.get("information") or {}).get("default_term")
                or 6
            )
            pct = _resolve_prepaid_percent(requested_fc, co)
            calc_targets.append((requested_fc, term, pct))
    elif zero_packages:
        top = zero_packages[0]
        key = str(top.get("company_key") or "")
        term = int(top.get("term_months") or 6)
        pct = float(top.get("prepaid_percent") or 20)
        if key:
            calc_targets.append((key, term, pct))
    else:
        for co in companies_summary[:2]:
            key = str(co.get("key") or "")
            if not key:
                continue
            raw_co = next((c for c in companies_raw if c.get("key") == key), None)
            term = int(hints.get("term_months") or co.get("default_term") or 6)
            pct = _resolve_prepaid_percent(key, raw_co or {})
            calc_targets.append((key, term, pct))

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
    card_amount = _int_amount(sale_price)
    card_summaries: list[dict[str, Any]] = []
    if card_amount:
        method_codes = (
            [hints.get("credit_card_method")]
            if hints.get("credit_card_method")
            else ["alepay", "onepay"]
        )
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
                banks = _parse_credit_card_banks(card_resp, bank_filter=bank_filter)
                if banks:
                    card_summaries.append({"method": method_code, "banks": banks})
            except Exception as exc:
                logger.warning("online-calculate/%s lỗi: %s", method_code, exc)
    card_block["zero_fee_by_bank"] = card_summaries
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
    if hints.get("pay_later"):
        pay_targets.append(hints["pay_later"])
    else:
        pay_targets = ["kredivo", "fundiin", "momo_vts"]

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

    if candidates:
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
