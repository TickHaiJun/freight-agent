from datetime import datetime, timedelta, timezone


# 北京时间固定为 UTC+8，且没有夏令时。
# 这里显式使用 UTC 偏移计算，避免依赖运行环境里的 zoneinfo / tzdata 数据。
BEIJING_TZ = timezone(timedelta(hours=8))


def get_current_beijing_datetime() -> datetime:
    """返回当前北京时间。"""
    return datetime.now(timezone.utc).astimezone(BEIJING_TZ)


def get_current_beijing_date_str() -> str:
    """返回当前北京时间日期字符串 YYYY-MM-DD。"""
    return get_current_beijing_datetime().strftime("%Y-%m-%d")
