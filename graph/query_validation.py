import re

from graph.origin_parser import ALL_ORIGIN_CODES, normalize_origin_codes

IATA_CODE_PATTERN = re.compile(r"^[a-z]{3}$")
ORIGIN_CLARIFY_MESSAGE = (
    "这票货目前还缺始发港。我需要先确认您从哪个城市/机场发货。"
    "您可以回复一个始发港、多个始发港，或者直接回复“全部港口”。"
)
REQUIRED_RATE_FIELDS = ["sfg", "mdg", "inputWeight", "inputVol", "packageType"]


def build_origin_clarify_message() -> str:
    """统一始发港追问文案，避免在多个节点里各写一份。"""
    return ORIGIN_CLARIFY_MESSAGE


def validate_rate_slots(slots: dict) -> dict:
    """
    在 tool 调用前做一层确定性校验。

    这一层的职责不是“猜值”，而是：
    1. 清洗明显脏数据
    2. 阻止 sfg/mdg 错配直接放行
    3. 把需要重新追问的情况转成统一结果
    """
    normalized = dict(slots)
    clarify_message = None
    clarify_slot = None

    normalized["sfg"], origin_issue = _normalize_origin_slot(normalized.get("sfg"))
    normalized["mdg"] = _normalize_iata_code(normalized.get("mdg"))
    normalized["inputWeight"] = _normalize_positive_number(normalized.get("inputWeight"))
    normalized["inputVol"] = _normalize_positive_number(normalized.get("inputVol"))

    if origin_issue:
        clarify_message = ORIGIN_CLARIFY_MESSAGE
        clarify_slot = "sfg"

    normalized["sfg"], origin_issue = _drop_destination_from_origin(
        normalized.get("sfg"),
        normalized.get("mdg"),
    )
    if origin_issue:
        clarify_message = ORIGIN_CLARIFY_MESSAGE
        clarify_slot = "sfg"

    missing_slots = _build_missing_required_slots(normalized)

    if not normalized.get("sfg") and "sfg" in missing_slots:
        clarify_message = clarify_message or ORIGIN_CLARIFY_MESSAGE
        clarify_slot = clarify_slot or "sfg"

    return {
        "valid": len(missing_slots) == 0,
        "normalized_slots": normalized,
        "missing_slots": missing_slots,
        "clarify_message": clarify_message,
        "clarify_slot": clarify_slot,
    }


def _normalize_origin_slot(value) -> tuple[str | None, str | None]:
    """始发港只允许出现在固定白名单里；无效时直接清空并转追问。"""
    if value in (None, ""):
        return None, None

    normalized = normalize_origin_codes(value)
    if normalized:
        return normalized, None
    return None, "invalid_origin"


def _normalize_iata_code(value) -> str | None:
    if value in (None, ""):
        return None

    normalized = str(value).strip().lower()
    return normalized if IATA_CODE_PATTERN.fullmatch(normalized) else None


def _normalize_positive_number(value) -> float | None:
    if value in (None, ""):
        return None

    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return None

    return normalized if normalized > 0 else None


def _drop_destination_from_origin(sfg: str | None, mdg: str | None) -> tuple[str | None, str | None]:
    """
    当目的港误混进始发港时，优先保留 mdg，清洗 sfg。

    例如：
    - sfg=lax, mdg=lax -> 清空 sfg
    - sfg=nkg,pvg,lax, mdg=lax -> 清洗为 nkg,pvg
    """
    if not sfg or not mdg:
        return sfg, None

    origin_codes = [code for code in str(sfg).split(",") if code]
    filtered_codes = [code for code in origin_codes if code != mdg]

    if len(filtered_codes) == len(origin_codes):
        return sfg, None

    cleaned = ",".join(filtered_codes) if filtered_codes else None
    return cleaned, "origin_contains_destination"


def _build_missing_required_slots(slots: dict) -> list[str]:
    missing = [field for field in REQUIRED_RATE_FIELDS if not slots.get(field)]

    has_date = bool(slots.get("hbrq") or (slots.get("hbrqBegin") and slots.get("hbrqEnd")))
    if not has_date:
        missing.append("hbrq")

    return missing
