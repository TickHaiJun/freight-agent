import re
from collections import defaultdict
TOP_N_PATTERN = re.compile(r"前\s*(\d+)|top\s*(\d+)", re.IGNORECASE)
SINGLE_RESULT_PATTERNS = [
    r"只要一条",
    r"给我一条",
    r"来一条",
    r"推荐一条",
    r"最便宜的一条",
    r"最低的一条",
    r"一条直飞",
    r"一条中转",
    r"一条数据",
    r"一条报价",
    r"一条结果",
    r"只看一条",
]
RESULT_REFERENCE_FIELD_PATTERNS = {
    "date": [r"多少号", r"几号", r"哪天", r"日期"],
    "carrier": [r"哪个航司", r"哪家航司", r"什么航司", r"\b航司\b"],
    "package_type": [r"什么包装", r"包装是什么", r"\b包装\b"],
    "route_type": [r"直飞还是中转", r"直达还是中转", r"是不是直飞", r"是不是中转"],
    "price_total": [r"多少钱", r"\b合计\b", r"总价"],
    "cheapest_reason": [r"为什么最便宜", r"为什么便宜", r"为什么最低"],
}


def build_standard_quote_result(api_result: dict) -> dict:
    """
    将原始运价接口结果收敛为统一的标准结构。

    目的：
    - 供结果分析链稳定复用
    - 让排序/筛选/分组只依赖一套字段
    """
    quotes = api_result.get("quotes") or []
    normalized_quotes = []

    for quote in quotes:
        routing_display = quote.get("routingDisplay") or "-"
        route_type = _detect_route_type(routing_display, quote)
        normalized_quotes.append(
            {
                "carrier": quote.get("twocode") or "-",
                "route": routing_display,
                "route_type": route_type,
                "cargo_type": quote.get("cargoType") or "-",
                "package_type": quote.get("packingDisplay") or "-",
                "unit_price": float(quote.get("unitPrice") or 0),
                "flight_price_total": float(quote.get("flightPriceTotal") or 0),
                "truck_price_total": float(quote.get("truckPriceTotal") or 0),
                "price_total": float(quote.get("priceTotal") or 0),
                "date": str(quote.get("hbrq") or api_result.get("hbrq") or "未知日期"),
                "raw": quote,
            }
        )

    return {
        "search_mode": api_result.get("search_mode"),
        "query": {
            "sfg": api_result.get("sfg"),
            "mdg": api_result.get("mdg"),
            "hbrq": api_result.get("hbrq"),
            "hbrqBegin": api_result.get("hbrqBegin"),
            "hbrqEnd": api_result.get("hbrqEnd"),
            "flightType": api_result.get("flightType"),
            "packageType": api_result.get("packageType"),
            "cargoType": api_result.get("cargoType"),
            "twoCode": api_result.get("twoCode"),
            "actual_weight": api_result.get("actual_weight"),
            "inputVol": api_result.get("inputVol"),
        },
        "quotes": normalized_quotes,
    }


def _detect_route_type(routing_display: str, raw_quote: dict) -> str:
    """
    根据 routingDisplay 稳定识别直达 / 中转。

    业务规则：
    - 2 段：直达，例如 PVG-AMS
    - 3 段及以上：中转，例如 PVG-FRA-AMS

    兜底规则：
    - 如果 routingDisplay 异常，再参考原始 zzg 字段
    - 仍无法判断时，默认按直达处理，避免把所有结果错误归到中转
    """
    normalized = (routing_display or "").strip().upper()
    if normalized and normalized != "-":
        parts = [part.strip() for part in normalized.split("-") if part.strip()]
        if len(parts) == 2:
            return "直达"
        if len(parts) >= 3:
            return "中转"

    # routingDisplay 不稳定时，回退参考原始中转港字段。
    zzg = str(raw_quote.get("zzg") or "").strip()
    if zzg and zzg != "直达":
        return "中转"

    return "直达"


def is_result_analysis_request(message: str, latest_quote_result: dict | None) -> bool:
    """判断当前消息是否更像“围绕上一批报价结果继续分析”。"""
    if not latest_quote_result or not latest_quote_result.get("quotes"):
        return False

    normalized = (message or "").strip()
    if not normalized:
        return False

    # 结果引用类问题优先交给结果解释链，不要和结果筛选/重查混用。
    if analyze_result_reference_request(normalized, latest_quote_result):
        return False

    analysis_keywords = [
        "最便宜",
        "最低",
        "单价",
        "全部数据",
        "所有数据",
        "全部报价",
        "所有报价",
        "全部明细",
        "完整报价",
        "展示全部",
        "全部展开",
        "全部列出来",
        "把所有方案给我看",
        "都列出来",
        "有哪些",
        "哪些",
        "直达",
        "中转",
        "散货",
        "托盘",
        "普货",
        "航司",
        "分别",
        "总结",
        "性价比",
        "推荐",
        "排一下",
        "前",
    ]
    if any(keyword in normalized for keyword in analysis_keywords):
        return True

    carriers = {quote["carrier"] for quote in latest_quote_result.get("quotes", []) if quote["carrier"] != "-"}
    return any(carrier.lower() in normalized.lower() for carrier in carriers)


def analyze_result_reference_request(message: str, latest_quote_result: dict | None) -> dict | None:
    """识别用户是否在引用当前结果里的某个字段，并附带简单选择器。"""
    if not latest_quote_result or not latest_quote_result.get("quotes"):
        return None

    normalized = (message or "").strip()
    if not normalized:
        return None

    compound_patterns = [
        (r"(最便宜|最低).*(包装类型|包装)", {"field": "package_type", "selector": "cheapest"}),
        (r"(最便宜|最低).*(哪个航司|哪家航司|什么航司|\b航司\b)", {"field": "carrier", "selector": "cheapest"}),
        (r"(最便宜|最低).*(多少号|几号|哪天|日期)", {"field": "date", "selector": "cheapest"}),
        (r"(最便宜|最低).*(直飞还是中转|直达还是中转|是不是直飞|是不是中转)", {"field": "route_type", "selector": "cheapest"}),
    ]
    for pattern, payload in compound_patterns:
        if re.search(pattern, normalized, re.IGNORECASE):
            return payload

    for field, patterns in RESULT_REFERENCE_FIELD_PATTERNS.items():
        if any(re.search(pattern, normalized, re.IGNORECASE) for pattern in patterns):
            return {"field": field, "selector": "current"}

    return None


def _extract_top_n(message: str) -> int | None:
    match = TOP_N_PATTERN.search(message)
    if not match:
        if "前三" in message:
            return 3
        return None
    return int(match.group(1) or match.group(2))


def _extract_carrier_filter(message: str, quotes: list[dict]) -> str | None:
    for quote in quotes:
        carrier = quote.get("carrier")
        if carrier and carrier != "-" and carrier.lower() in message.lower():
            return carrier
    return None


def _extract_package_filter(message: str, quotes: list[dict]) -> str | None:
    package_values = {quote.get("package_type") for quote in quotes}
    for package_value in package_values:
        if package_value and package_value != "-" and package_value in message:
            return package_value
    return None


def _extract_cargo_filter(message: str, quotes: list[dict]) -> str | None:
    cargo_values = {quote.get("cargo_type") for quote in quotes}
    for cargo_value in cargo_values:
        if cargo_value and cargo_value != "-" and cargo_value in message:
            return cargo_value
    return None


def _apply_filters(quotes: list[dict], filters: dict) -> list[dict]:
    filtered = list(quotes)

    route_type = filters.get("route_type")
    if route_type:
        filtered = [quote for quote in filtered if quote.get("route_type") == route_type]

    carrier = filters.get("carrier")
    if carrier:
        filtered = [quote for quote in filtered if quote.get("carrier") == carrier]

    package_type = filters.get("package_type")
    if package_type:
        filtered = [quote for quote in filtered if quote.get("package_type") == package_type]

    cargo_type = filters.get("cargo_type")
    if cargo_type:
        filtered = [quote for quote in filtered if quote.get("cargo_type") == cargo_type]

    return filtered


def _format_currency(value: float) -> str:
    return f"{value:.2f}CNY"


def _build_markdown_table(quotes: list[dict], include_unit_price: bool = True) -> str:
    headers = ["航司", "航线", "货类", "包装"]
    if include_unit_price:
        headers.append("预估运费单价")
    headers.extend(["预估运费总价", "预估卡车费", "合计"])

    rows = []
    for quote in quotes:
        row = [
            quote["carrier"],
            quote["route"],
            quote["cargo_type"],
            quote["package_type"],
        ]
        if include_unit_price:
            row.append(_format_currency(quote["unit_price"]))
        row.extend(
            [
                _format_currency(quote["flight_price_total"]),
                _format_currency(quote["truck_price_total"]),
                _format_currency(quote["price_total"]),
            ]
        )
        rows.append("| " + " | ".join(row) + " |")

    header_line = "| " + " | ".join(headers) + " |"
    separator_line = "| " + " | ".join(["---"] * len(headers)) + " |"
    return "\n".join([header_line, separator_line, *rows])


def _group_by_field(quotes: list[dict], field: str) -> dict[str, list[dict]]:
    grouped = defaultdict(list)
    for quote in quotes:
        grouped[str(quote.get(field) or "-")].append(quote)
    return dict(grouped)


def _detect_quantity_mode(message: str) -> str:
    normalized = (message or "").strip()
    if any(re.search(pattern, normalized, re.IGNORECASE) for pattern in SINGLE_RESULT_PATTERNS):
        return "single"
    # 允许“航司为 CK 且直达的一条数据 / 一条托盘的 / 一条散货的”这类口语表达稳定命中单条模式。
    if re.search(r"(一条|1条).*(数据|报价|结果|方案|直飞|直达|中转|托盘|散货|普货)", normalized, re.IGNORECASE):
        return "single"
    return "multi"


def analyze_result_request(message: str, latest_quote_result: dict) -> tuple[str, dict, str, str]:
    """
    解析结果分析请求，输出子意图和过滤条件。

    第一批只覆盖：
    - 价格最低类
    - 航线筛选类
    - 航司筛选类
    - 包装 / 货类筛选类
    - 结果摘要类
    """
    quotes = latest_quote_result.get("quotes") or []
    normalized = (message or "").strip()
    quantity_mode = _detect_quantity_mode(normalized)
    default_package_type = (
        ((latest_quote_result.get("query") or {}).get("packageType"))
        or ((latest_quote_result.get("query") or {}).get("package_type"))
    )

    filters = {
        "route_type": None,
        "carrier": _extract_carrier_filter(normalized, quotes),
        # 查询链已经明确选择过包装类型时，结果分析默认沿用这个约束；
        # 用户本轮如果再次明确说“只看散货/托盘”，则以当前表达覆盖默认值。
        "package_type": _extract_package_filter(normalized, quotes) or default_package_type,
        "cargo_type": _extract_cargo_filter(normalized, quotes),
        "top_n": _extract_top_n(normalized),
        "sort_by": "price_total",
    }

    if any(
        keyword in normalized
        for keyword in [
            "全部数据",
            "所有数据",
            "全部报价",
            "所有报价",
            "全部明细",
            "完整报价",
            "展示全部",
            "全部展开",
            "全部列出来",
            "把所有方案给我看",
            "都列出来",
        ]
    ):
        return "all_list", filters, "multi", "summary_plus_table"

    if "直达" in normalized and "中转" in normalized and "分别" in normalized:
        return "route_group_compare", filters, "multi", "summary_plus_table"

    if "直达" in normalized:
        filters["route_type"] = "直达"
    elif "中转" in normalized:
        filters["route_type"] = "中转"

    if "航司" in normalized and "包装" in normalized and not re.search(r"(最便宜|最低).*(包装类型|包装)", normalized):
        return "needs_clarification", filters, quantity_mode, "summary_plus_clarify"

    if "总结" in normalized or "性价比" in normalized or "推荐" in normalized:
        response_mode = "single_result" if quantity_mode == "single" else "summary_only"
        return "summary", filters, quantity_mode, response_mode

    if "分别" in normalized and ("航司" in normalized or "不同航司" in normalized):
        return "carrier_group_compare", filters, "multi", "summary_plus_table"

    if "单价" in normalized and ("最便宜" in normalized or "最低" in normalized):
        filters["sort_by"] = "unit_price"
        response_mode = "single_result" if quantity_mode == "single" else "summary_plus_table"
        return "lowest", filters, quantity_mode, response_mode

    if "最便宜" in normalized or "最低" in normalized or filters["top_n"]:
        filters["sort_by"] = "price_total"
        response_mode = "single_result" if quantity_mode == "single" else "summary_plus_table"
        return "lowest", filters, quantity_mode, response_mode

    # 当用户明确只要“一条”时，数量约束必须高于默认列表输出。
    # 这里统一解释为：先按条件筛选，再从筛选结果里选出一条最优方案。
    if quantity_mode == "single" and (
        filters["route_type"] or filters["carrier"] or filters["package_type"] or filters["cargo_type"]
    ):
        return "lowest", filters, "single", "single_result"

    if "有哪些" in normalized or "哪些" in normalized or filters["carrier"] or filters["package_type"] or filters["cargo_type"]:
        return "filter_list", filters, "multi", "summary_plus_table"

    if "排一下" in normalized:
        return "sorted_list", filters, "multi", "summary_plus_table"

    response_mode = "single_result" if quantity_mode == "single" else "summary_only"
    return "summary", filters, quantity_mode, response_mode


def _render_single_result_message(quotes: list[dict], intro: str | None = None) -> str:
    """单条结果模式：只给一条符合条件的结果，避免误输出排序列表。"""
    selected = quotes[:1]
    if not selected:
        return "抱歉，当前这批报价结果中没有找到符合条件的方案。"
    intro_text = intro or "已为您挑选出一条最符合当前条件的参考方案："
    return intro_text + "\n\n" + _build_markdown_table(selected)


def render_result_analysis_message(
    latest_quote_result: dict,
    analysis_intent: str,
    filters: dict,
    response_mode: str = "summary_plus_table",
    quantity_mode: str = "multi",
) -> str:
    """根据子意图、输出模式和数量模式，将上一批报价结果渲染为最终回复。"""
    quotes = latest_quote_result.get("quotes") or []
    filtered_quotes = _apply_filters(quotes, filters)

    if not filtered_quotes:
        return "抱歉，当前这批报价结果中没有找到符合筛选条件的方案。"

    if analysis_intent == "carrier_group_compare":
        sections = []
        for carrier, carrier_quotes in sorted(_group_by_field(filtered_quotes, "carrier").items()):
            sections.append(f"**{carrier}**\n\n{_build_markdown_table(sorted(carrier_quotes, key=lambda item: item['price_total']))}")
        return "已按航司为您分组展示当前报价结果：\n\n" + "\n\n".join(sections)

    if analysis_intent == "route_group_compare":
        sections = []
        for route_type in ["直达", "中转"]:
            route_quotes = [quote for quote in filtered_quotes if quote.get("route_type") == route_type]
            if route_quotes:
                sections.append(f"**{route_type}**\n\n{_build_markdown_table(sorted(route_quotes, key=lambda item: item['price_total']))}")
        return "已按直达 / 中转为您分组展示当前报价结果：\n\n" + "\n\n".join(sections)

    if analysis_intent == "summary":
        cheapest = min(filtered_quotes, key=lambda item: item["price_total"])
        intro = (
            f"当前这批结果共匹配到 {len(filtered_quotes)} 条方案。"
            f"如果按总价优先，当前最低参考方案为 {cheapest['carrier']} / {cheapest['route']}，"
            f"合计 {_format_currency(cheapest['price_total'])}。"
        )
        if response_mode == "single_result" or quantity_mode == "single":
            return _render_single_result_message(
                [cheapest],
                f"已为您优先推荐当前条件下最便宜的一条参考方案：",
            )
        return intro

    if analysis_intent == "needs_clarification" or response_mode == "summary_plus_clarify":
        return "您这句话里同时提到了航司和包装，但目标还不够明确。您是想看某个航司对应的包装类型，还是想看最便宜那条方案的包装类型？"

    if analysis_intent == "all_list":
        sorted_quotes = sorted(filtered_quotes, key=lambda item: item["price_total"])
        return "已为您展开当前这批报价的完整明细：\n\n" + _build_markdown_table(sorted_quotes)

    sort_by = filters.get("sort_by") or "price_total"
    sorted_quotes = sorted(filtered_quotes, key=lambda item: item.get(sort_by) or 0)
    if filters.get("top_n"):
        sorted_quotes = sorted_quotes[: filters["top_n"]]

    if response_mode == "single_result" or quantity_mode == "single":
        sort_label = "预估运费单价" if sort_by == "unit_price" else "合计"
        return _render_single_result_message(
            sorted_quotes,
            f"已按 {sort_label} 为您选出一条最符合当前条件的参考方案：",
        )

    if analysis_intent == "lowest":
        sort_label = "预估运费单价" if sort_by == "unit_price" else "合计"
        return (
            f"已按 {sort_label} 从低到高为您整理当前报价结果：\n\n"
            f"{_build_markdown_table(sorted_quotes)}"
        )

    if analysis_intent in {"filter_list", "sorted_list"}:
        return "已按您的条件筛选当前报价结果：\n\n" + _build_markdown_table(sorted_quotes)

    return "已整理当前报价结果：\n\n" + _build_markdown_table(sorted_quotes)


def render_result_reference_message(
    latest_quote_result: dict,
    result_reference_request: dict,
    result_display_mode: str | None = None,
) -> str:
    """
    基于最近一次完整报价结果解释某个字段，不重新查价。

    第一版不追踪“用户指的是表格里的第几行”，而是解释当前展示模式下默认会展示的那组结果，
    以保证能力稳定落地，避免引入新的前端定位依赖。
    """
    quotes = latest_quote_result.get("quotes") or []
    if not quotes:
        return "抱歉，当前没有可继续解释的报价结果。请先完成一次运价查询。"

    result_reference_field = result_reference_request.get("field") or "date"
    selector = result_reference_request.get("selector") or "current"
    display_quotes = _select_reference_quotes(quotes, result_display_mode, selector)
    if not display_quotes:
        display_quotes = sorted(quotes, key=lambda item: item["price_total"])[:1]

    if result_reference_field == "date":
        return _render_reference_dates(display_quotes, result_display_mode)
    if result_reference_field == "carrier":
        return _render_reference_carriers(display_quotes, result_display_mode)
    if result_reference_field == "package_type":
        return _render_reference_packages(display_quotes, result_display_mode)
    if result_reference_field == "route_type":
        return _render_reference_route_types(display_quotes, result_display_mode)
    if result_reference_field == "price_total":
        return _render_reference_totals(display_quotes, result_display_mode)
    if result_reference_field == "cheapest_reason":
        return _render_reference_cheapest_reason(display_quotes, result_display_mode)

    return "抱歉，我暂时还不能准确解释当前结果里的这个字段。"


def _select_reference_quotes(quotes: list[dict], result_display_mode: str | None, selector: str = "current") -> list[dict]:
    """按当前展示模式和引用选择器选出最适合被解释的报价结果。"""
    sorted_quotes = sorted(quotes, key=lambda item: item["price_total"])
    if selector == "cheapest":
        return sorted_quotes[:1]
    if result_display_mode == "direct_transit_pair":
        selected = []
        for route_type in ["直达", "中转"]:
            candidates = [quote for quote in sorted_quotes if quote.get("route_type") == route_type]
            if candidates:
                selected.append(candidates[0])
        return selected
    return sorted_quotes[:2]


def _render_reference_dates(quotes: list[dict], result_display_mode: str | None) -> str:
    if result_display_mode == "direct_transit_pair":
        return "；".join([f"{quote['route_type']}对应的航班日期是 {quote['date']}" for quote in quotes]) + "。"
    if len(quotes) == 1:
        return f"这条报价对应的航班日期是 {quotes[0]['date']}。"
    return (
        f"当前默认展示的结果里，{quotes[0]['package_type']}最低价对应日期是 {quotes[0]['date']}，"
        f"{quotes[1]['package_type']}最低价对应日期是 {quotes[1]['date']}。"
    )


def _render_reference_carriers(quotes: list[dict], result_display_mode: str | None) -> str:
    if result_display_mode == "direct_transit_pair":
        return "；".join([f"{quote['route_type']}对应的航司是 {quote['carrier']}" for quote in quotes]) + "。"
    if len(quotes) == 1:
        return f"这条报价对应的航司是 {quotes[0]['carrier']}。"
    return (
        f"当前默认展示的结果里，{quotes[0]['package_type']}最低价对应航司是 {quotes[0]['carrier']}，"
        f"{quotes[1]['package_type']}最低价对应航司是 {quotes[1]['carrier']}。"
    )


def _render_reference_packages(quotes: list[dict], result_display_mode: str | None) -> str:
    if result_display_mode == "direct_transit_pair":
        return "；".join([f"{quote['route_type']}这条报价的包装类型是 {quote['package_type']}" for quote in quotes]) + "。"
    if len(quotes) == 1:
        return f"这条报价的包装类型是 {quotes[0]['package_type']}。"
    return (
        f"当前默认展示的是两类结果：一条是 {quotes[0]['package_type']} 最低价，"
        f"另一条是 {quotes[1]['package_type']} 最低价。"
    )


def _render_reference_route_types(quotes: list[dict], result_display_mode: str | None) -> str:
    if result_display_mode == "direct_transit_pair":
        return "；".join([f"{quote['route']} 属于 {quote['route_type']}" for quote in quotes]) + "。"
    if len(quotes) == 1:
        return f"这条报价是 {quotes[0]['route_type']}，航线为 {quotes[0]['route']}。"
    return (
        f"当前默认展示的两条结果分别是：{quotes[0]['package_type']}最低价为 {quotes[0]['route_type']}，"
        f"{quotes[1]['package_type']}最低价为 {quotes[1]['route_type']}。"
    )


def _render_reference_totals(quotes: list[dict], result_display_mode: str | None) -> str:
    if result_display_mode == "direct_transit_pair":
        return "；".join([f"{quote['route_type']}这条报价的合计是 {_format_currency(quote['price_total'])}" for quote in quotes]) + "。"
    if len(quotes) == 1:
        return f"这条报价的合计是 {_format_currency(quotes[0]['price_total'])}。"
    return (
        f"当前默认展示的结果里，{quotes[0]['package_type']}最低价合计是 {_format_currency(quotes[0]['price_total'])}，"
        f"{quotes[1]['package_type']}最低价合计是 {_format_currency(quotes[1]['price_total'])}。"
    )


def _render_reference_cheapest_reason(quotes: list[dict], result_display_mode: str | None) -> str:
    if result_display_mode == "direct_transit_pair":
        return "当前这两条结果是分别按直达和中转各自的合计最低价选出来的。"
    if len(quotes) == 1:
        return "当前这条结果是按合计最低价选出来的。"
    return (
        "当前默认展示的不是全部结果，而是我按包装类型分桶后，"
        "分别选出了散货和托盘各自合计最低的一条报价。"
    )
