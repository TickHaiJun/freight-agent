"""反馈落盘前的轻量脱敏与截断处理。"""

import re


_PHONE_PATTERN = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_ID_CARD_PATTERN = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_ORDER_PATTERN = re.compile(r"\b(?:order|订单)[-_:# ]?[A-Za-z0-9-]{6,}\b", re.IGNORECASE)


def sanitize_text(value: str, max_length: int) -> str:
    """遮罩常见敏感片段，防止反馈文件成为原始个人信息副本。"""
    text = value[:max_length]
    text = _PHONE_PATTERN.sub("[手机号已脱敏]", text)
    text = _EMAIL_PATTERN.sub("[邮箱已脱敏]", text)
    text = _ID_CARD_PATTERN.sub("[身份证号已脱敏]", text)
    return _ORDER_PATTERN.sub("[订单号已脱敏]", text)
