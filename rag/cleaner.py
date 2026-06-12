import re


_PAGE_NOISE_PATTERNS = [
    re.compile(r"^\s*第?\s*\d+\s*页\s*$"),
    re.compile(r"^\s*page\s*\d+\s*$", re.IGNORECASE),
]


def clean_text(text: str) -> str:
    # 这里只做“轻清洗”，不改写业务文本，避免表单/声明类资料失真。
    lines = []
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        if any(pattern.match(line) for pattern in _PAGE_NOISE_PATTERNS):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def clean_documents(documents: list[dict]) -> list[dict]:
    cleaned = []
    for item in documents:
        page_content = clean_text(item.get("page_content", ""))
        if not page_content:
            continue
        cleaned.append({
            **item,
            "page_content": page_content,
        })
    return cleaned
