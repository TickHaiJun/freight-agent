import re

ALL_ORIGIN_CODES = [
    "xmn",
    "can",
    "szx",
    "hkg",
    "sgn",
    "sin",
    "lax",
    "nkg",
    "hgh",
    "hfe",
    "ntg",
    "wux",
    "pvg",
    "ckg",
    "wuh",
    "ctu",
    "xiy",
    "kmg",
    "pek",
    "pkx",
    "tao",
    "cgo",
]
ALL_ORIGIN_CODES_TEXT = ",".join(ALL_ORIGIN_CODES)
ALL_ORIGIN_LABELS = {
    "xmn": "厦门",
    "can": "广州",
    "szx": "深圳",
    "hkg": "香港",
    "sgn": "胡志明",
    "sin": "新加坡",
    "lax": "洛杉矶",
    "nkg": "南京",
    "hgh": "杭州",
    "hfe": "合肥",
    "ntg": "南通",
    "wux": "无锡",
    "pvg": "上海",
    "ckg": "重庆",
    "wuh": "武汉",
    "ctu": "成都",
    "xiy": "西安",
    "kmg": "昆明",
    "pek": "北京首都",
    "pkx": "北京大兴",
    "tao": "青岛",
    "cgo": "郑州",
}
ALL_ORIGIN_SCOPE_TEXT = "、".join(f"{ALL_ORIGIN_LABELS[code]}({code.upper()})" for code in ALL_ORIGIN_CODES)

# 白名单里包含业务侧指定的分公司口岸，第一版不按常识裁剪。
CITY_ALIAS_TO_CODE = {
    "上海": "pvg",
    "浦东": "pvg",
    "广州": "can",
    "深圳": "szx",
    "香港": "hkg",
    "胡志明": "sgn",
    "胡志明市": "sgn",
    "西贡": "sgn",
    "新加坡": "sin",
    "洛杉矶": "lax",
    "南京": "nkg",
    "杭州": "hgh",
    "合肥": "hfe",
    "南通": "ntg",
    "无锡": "wux",
    "重庆": "ckg",
    "武汉": "wuh",
    "成都": "ctu",
    "西安": "xiy",
    "昆明": "kmg",
    "北京": "pek",
    "首都": "pek",
    "北京首都": "pek",
    "大兴": "pkx",
    "北京大兴": "pkx",
    "青岛": "tao",
    "郑州": "cgo",
    "厦门": "xmn",
}

ALL_ORIGIN_PATTERNS = [
    "全部港口",
    "全部查询",
    "全部始发港",
    "所有始发港",
    "所有港口",
    "全口岸",
    "全部口岸",
    "分公司口岸都查",
    "分公司港口都查",
]
ORIGIN_ROLE_MARKERS = ["从", "始发港", "起运港", "始发地", "出发地", "出发", "发货", "起飞"]
DESTINATION_MARKERS = ["发往", "发去", "送往", "去往", "运往", "到", "飞", "运到", "去", "至", "抵达"]


def is_all_origin_query(message: str) -> bool:
    normalized = _normalize_message(message)
    if not normalized:
        return False
    return any(pattern in normalized for pattern in ALL_ORIGIN_PATTERNS)


def normalize_origin_codes(value: str | list[str] | None) -> str | None:
    if value is None:
        return None

    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = re.split(r"[\s,，/、;；]+", str(value).strip())

    normalized_codes: list[str] = []
    for item in raw_items:
        token = str(item or "").strip().lower()
        if not token:
            continue
        if token in ALL_ORIGIN_CODES and token not in normalized_codes:
            normalized_codes.append(token)

    return ",".join(normalized_codes) if normalized_codes else None


def extract_origin_codes(message: str) -> str | None:
    if is_all_origin_query(message):
        return ALL_ORIGIN_CODES_TEXT

    segment = _extract_origin_segment(message)
    if not segment:
        return None

    codes = _extract_codes_from_segment(segment)
    return normalize_origin_codes(codes)


def looks_like_origin_reply(message: str, missing_slots: list[str] | None = None) -> bool:
    normalized = _normalize_message(message)
    if not normalized:
        return False

    if is_all_origin_query(normalized):
        return True

    if any(marker in normalized for marker in ORIGIN_ROLE_MARKERS):
        return True

    if (missing_slots or []) and "sfg" in (missing_slots or []):
        return bool(extract_origin_codes(normalized))

    return False


def _normalize_message(message: str) -> str:
    return str(message or "").strip()


def _extract_origin_segment(message: str) -> str:
    normalized = _normalize_message(message)
    if not normalized:
        return ""

    lowered = normalized.lower()
    if re.fullmatch(r"[a-z,\s/、，;；]+", lowered):
        return normalized

    from_index = normalized.find("从")
    if from_index >= 0:
        normalized = normalized[from_index + 1 :]

    for marker in DESTINATION_MARKERS:
        marker_index = normalized.find(marker)
        if marker_index > 0:
            return normalized[:marker_index]

    return normalized


def _extract_codes_from_segment(segment: str) -> list[str]:
    codes: list[str] = []
    compact_segment = re.sub(r"[\s，,、/;；]", "", segment)

    for code in re.findall(r"\b[A-Za-z]{3}\b", segment):
        lowered = code.lower()
        if lowered in ALL_ORIGIN_CODES and lowered not in codes:
            codes.append(lowered)

    alias_pattern = "|".join(sorted((re.escape(alias) for alias in CITY_ALIAS_TO_CODE), key=len, reverse=True))
    for match in re.finditer(alias_pattern, compact_segment):
        lowered = CITY_ALIAS_TO_CODE[match.group(0)]
        if lowered not in codes:
            codes.append(lowered)

    return codes
