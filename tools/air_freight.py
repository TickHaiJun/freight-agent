import httpx
import logging
import time
from datetime import datetime, timedelta

from pydantic import BaseModel, Field
from langchain_core.tools import tool

from config import settings
from logging_schema import log_event, summarize_quotes

logger = logging.getLogger(__name__)

SIMILAR_DATE_FORWARD_DAYS = 7


class AirFreightInput(BaseModel):
    sfg: str = Field(
        description=(
            "始发港机场三字代码，小写。支持单个机场代码，"
            "也支持多个代码用逗号拼接，例如 `pvg,hkg,nkg`。"
            "根据用户提到的城市或地区推断最近的国际机场代码。"
            "例：上海/浦东→pvg，深圳→szx，广州→can，北京/首都→pek，北京大兴→pkx，"
            "杭州→hgh，成都→ctu，重庆→ckg，厦门→xmn，武汉→wuh，西安→xiy，"
            "南京→nkg，昆明→kmg，郑州→cgo，天津→tna。"
            "如用户所在城市无国际机场，推荐距离最近的机场，并在回复中说明。"
            "必须是小写三字代码。"
        )
    )
    mdg: str = Field(
        description=(
            "目的港机场三字代码，小写。"
            "根据用户提到的目的地城市/国家推断最近的主要国际机场代码。"
            "例：洛杉矶/LA→lax，纽约→jfk，芝加哥→ord，迈阿密→mia，"
            "法兰克福→fra，伦敦→lhr，巴黎→cdg，阿姆斯特丹→ams，"
            "马德里→mad，米兰→mxp，东京→nrt，大阪→kix，首尔→icn，"
            "悉尼→syd，迪拜→dxb，多伦多→yyz，温哥华→yvr，墨西哥城→mex。"
            "如用户说的是国家而非城市，选该国最主要的货运机场。"
            "必须是小写三字代码。"
        )
    )
    inputWeight: float = Field(
        description=(
            "货物毛重，单位：kg（公斤）。"
            "用户可能说'500公斤'、'0.5吨'、'500kg'，统一换算为 kg 的数值。"
            "1吨=1000kg。必须大于0。"
        )
    )
    inputVol: float = Field(
        description=(
            "货物体积，单位：CBM（立方米）。"
            "用户可能说'1.5方'、'1.5立方'、'1.5CBM'，统一换算为 CBM 数值。"
            "如用户提供的是长×宽×高(cm)，换算：长×宽×高÷1000000=CBM。"
            "必须大于0。"
        )
    )
    hbrq: str | None = Field(
        default=None,
        description=(
            "单个期望航班日期，格式 YYYY-MM-DD。"
            "用户可能说'下周一'、'3月10号'、'越快越好'等，转换为具体日期字符串。"
        ),
    )
    hbrqBegin: str | None = Field(
        default=None,
        description="区间查询开始日期，格式 YYYY-MM-DD。",
    )
    hbrqEnd: str | None = Field(
        default=None,
        description="区间查询结束日期，格式 YYYY-MM-DD。",
    )
    flightType: str | None = Field(
        default=None,
        description="航班类型，可选值如：直达、中转。",
    )
    packageType: str | None = Field(
        default=None,
        description="包装类型，可选值如：散货、托盘。",
    )
    cargoType: str | None = Field(
        default=None,
        description="货类，可选值如：普货。",
    )
    twoCode: str | None = Field(
        default=None,
        description="航司二字码，如 CA、CZ、MU。",
    )
    gid: int | None = Field(
        default=None,
        description="客户报价ID，不传或 -1 表示公布运价。",
    )


def _parse_date(value: str) -> datetime:
    """将 YYYY-MM-DD 转成 datetime，便于生成类似运价日期范围。"""
    return datetime.strptime(value, "%Y-%m-%d")


def _call_air_freight_api(params: dict) -> dict:
    """统一封装空运报价接口调用，便于复用精确查询和类似查询。"""
    url = f"{settings.freight_api_base}/fee/api/airFreightFee/getUnitPrice"
    started = time.perf_counter()

    transport = httpx.HTTPTransport(proxy=None)
    with httpx.Client(timeout=15.0, transport=transport) as client:
        response = client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

    logger.info(
        "air_freight api finished | elapsed=%.3fs | url=%s | statussuccess=%s | params=%s",
        time.perf_counter() - started,
        url,
        data.get("resultsuccess", False),
        params,
    )
    log_event(
        logger,
        event="quote_api_finished",
        elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        tool_name="search_air_freight_rate",
        api_base=settings.freight_api_base,
        api_path="/fee/api/airFreightFee/getUnitPrice",
        api_status_success=data.get("resultsuccess", False),
        request_params_summary=params,
        **summarize_quotes(data.get("resultdata") or []),
    )
    return data


def _build_query_params(
    *,
    sfg: str,
    mdg: str,
    inputWeight: float,
    inputVol: float,
    hbrq: str | None,
    hbrqBegin: str | None,
    hbrqEnd: str | None,
    flightType: str | None,
    packageType: str | None,
    cargoType: str | None,
    twoCode: str | None,
    gid: int | None,
) -> dict:
    """构造接口查询参数，只传有值字段。"""
    # `sfg` 第一版仍保持字符串协议，但允许多个始发港用逗号拼接。
    normalized_sfg = ",".join([code.strip().lower() for code in str(sfg).split(",") if code.strip()])
    params = {
        "sfg": normalized_sfg,
        "mdg": mdg.lower(),
        "inputWeight": inputWeight,
        "inputVol": inputVol,
    }

    if hbrq:
        params["hbrq"] = hbrq
    if hbrqBegin and hbrqEnd:
        params["hbrqBegin"] = hbrqBegin
        params["hbrqEnd"] = hbrqEnd
    if flightType:
        params["flightType"] = flightType
    if packageType:
        params["packageType"] = packageType
    if cargoType:
        params["cargoType"] = cargoType
    if twoCode:
        params["twoCode"] = twoCode.upper()
    if gid is not None:
        params["gid"] = gid

    return params


def _build_similar_date_range(hbrq: str) -> tuple[str, str]:
    """类似运价仅向后放宽 7 天，不跨目的港、不放宽重量体积。"""
    target_date = _parse_date(hbrq)
    begin = target_date + timedelta(days=1)
    end = target_date + timedelta(days=SIMILAR_DATE_FORWARD_DAYS)
    return begin.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


@tool(args_schema=AirFreightInput)
def search_air_freight_rate(
    sfg: str,
    mdg: str,
    inputWeight: float,
    inputVol: float,
    hbrq: str | None = None,
    hbrqBegin: str | None = None,
    hbrqEnd: str | None = None,
    flightType: str | None = None,
    packageType: str | None = None,
    cargoType: str | None = None,
    twoCode: str | None = None,
    gid: int | None = None,
) -> dict:
    """
    查询空运运价。

    规则：
    - 必填字段为始发港、目的港、重量、体积，以及单日期或日期区间
    - 先执行精确查询
    - 若单日期精确查询无结果，则自动查询“向后7天”的类似运价
    """
    volume_weight = round(inputVol * 1000 / 6, 2)
    charge_weight = max(inputWeight, volume_weight)

    exact_params = _build_query_params(
        sfg=sfg,
        mdg=mdg,
        inputWeight=inputWeight,
        inputVol=inputVol,
        hbrq=hbrq,
        hbrqBegin=hbrqBegin,
        hbrqEnd=hbrqEnd,
        flightType=flightType,
        packageType=packageType,
        cargoType=cargoType,
        twoCode=twoCode,
        gid=gid,
    )

    try:
        exact_data = _call_air_freight_api(exact_params)
    except httpx.TimeoutException:
        logger.warning("air_freight api timeout | params=%s", exact_params)
        return {"success": False, "error": "TIMEOUT", "message": "运价接口请求超时，请稍后重试"}
    except httpx.HTTPError as e:
        logger.warning("air_freight api http error | params=%s | error=%s", exact_params, str(e))
        return {"success": False, "error": "HTTP_ERROR", "message": f"接口请求失败：{str(e)}"}
    except Exception as e:
        logger.exception("air_freight api unknown error | params=%s", exact_params)
        return {"success": False, "error": "UNKNOWN", "message": f"系统异常：{str(e)}"}

    if not exact_data.get("resultsuccess", False):
        return {
            "success": False,
            "error": "API_ERROR",
            "message": exact_data.get("resultmessage", "运价接口返回失败"),
        }

    exact_quotes = exact_data.get("resultdata", []) or []
    if exact_quotes:
        return {
            "success": exact_data.get("resultsuccess", False),
            "status": exact_data.get("resultstatus"),
            "message": exact_data.get("resultmessage"),
            "quotes": exact_quotes,
            "charge_weight": charge_weight,
            "actual_weight": inputWeight,
            "volume_weight": volume_weight,
            "sfg": sfg.lower(),
            "mdg": mdg.lower(),
            "hbrq": hbrq,
            "hbrqBegin": hbrqBegin,
            "hbrqEnd": hbrqEnd,
            "flightType": flightType,
            "packageType": packageType,
            "cargoType": cargoType,
            "twoCode": twoCode,
            "gid": gid,
            "search_mode": "exact",
            "exact_quotes": exact_quotes,
            "similar_quotes": [],
            "similar_hbrqBegin": None,
            "similar_hbrqEnd": None,
        }

    # 用户明确传了区间查询时，不再做“类似日期”自动扩展，避免和用户意图冲突。
    if hbrqBegin and hbrqEnd:
        return {
            "success": exact_data.get("resultsuccess", False),
            "status": exact_data.get("resultstatus"),
            "message": exact_data.get("resultmessage"),
            "quotes": [],
            "charge_weight": charge_weight,
            "actual_weight": inputWeight,
            "volume_weight": volume_weight,
            "sfg": sfg.lower(),
            "mdg": mdg.lower(),
            "hbrq": hbrq,
            "hbrqBegin": hbrqBegin,
            "hbrqEnd": hbrqEnd,
            "flightType": flightType,
            "packageType": packageType,
            "cargoType": cargoType,
            "twoCode": twoCode,
            "gid": gid,
            "search_mode": "none",
            "exact_quotes": [],
            "similar_quotes": [],
            "similar_hbrqBegin": None,
            "similar_hbrqEnd": None,
        }

    if not hbrq:
        return {
            "success": exact_data.get("resultsuccess", False),
            "status": exact_data.get("resultstatus"),
            "message": exact_data.get("resultmessage"),
            "quotes": [],
            "charge_weight": charge_weight,
            "actual_weight": inputWeight,
            "volume_weight": volume_weight,
            "sfg": sfg.lower(),
            "mdg": mdg.lower(),
            "hbrq": hbrq,
            "hbrqBegin": hbrqBegin,
            "hbrqEnd": hbrqEnd,
            "flightType": flightType,
            "packageType": packageType,
            "cargoType": cargoType,
            "twoCode": twoCode,
            "gid": gid,
            "search_mode": "none",
            "exact_quotes": [],
            "similar_quotes": [],
            "similar_hbrqBegin": None,
            "similar_hbrqEnd": None,
        }

    similar_begin, similar_end = _build_similar_date_range(hbrq)
    similar_params = _build_query_params(
        sfg=sfg,
        mdg=mdg,
        inputWeight=inputWeight,
        inputVol=inputVol,
        hbrq=hbrq,
        hbrqBegin=similar_begin,
        hbrqEnd=similar_end,
        flightType=flightType,
        packageType=packageType,
        cargoType=cargoType,
        twoCode=twoCode,
        gid=gid,
    )

    try:
        similar_data = _call_air_freight_api(similar_params)
    except httpx.TimeoutException:
        logger.warning("air_freight similar api timeout | params=%s", similar_params)
        return {"success": False, "error": "TIMEOUT", "message": "运价接口请求超时，请稍后重试"}
    except httpx.HTTPError as e:
        logger.warning("air_freight similar api http error | params=%s | error=%s", similar_params, str(e))
        return {"success": False, "error": "HTTP_ERROR", "message": f"接口请求失败：{str(e)}"}
    except Exception as e:
        logger.exception("air_freight similar api unknown error | params=%s", similar_params)
        return {"success": False, "error": "UNKNOWN", "message": f"系统异常：{str(e)}"}

    if not similar_data.get("resultsuccess", False):
        return {
            "success": False,
            "error": "API_ERROR",
            "message": similar_data.get("resultmessage", "运价接口返回失败"),
        }

    similar_quotes = similar_data.get("resultdata", []) or []
    search_mode = "similar" if similar_quotes else "none"

    return {
        "success": similar_data.get("resultsuccess", False),
        "status": similar_data.get("resultstatus"),
        "message": similar_data.get("resultmessage"),
        "quotes": similar_quotes,
        "charge_weight": charge_weight,
        "actual_weight": inputWeight,
        "volume_weight": volume_weight,
        "sfg": sfg.lower(),
        "mdg": mdg.lower(),
        "hbrq": hbrq,
        "hbrqBegin": hbrqBegin,
        "hbrqEnd": hbrqEnd,
        "flightType": flightType,
        "packageType": packageType,
        "cargoType": cargoType,
        "twoCode": twoCode,
        "gid": gid,
        "search_mode": search_mode,
        "exact_quotes": [],
        "similar_quotes": similar_quotes,
        "similar_hbrqBegin": similar_begin,
        "similar_hbrqEnd": similar_end,
    }
