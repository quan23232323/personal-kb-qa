from datetime import datetime, timezone


def now_iso() -> str:
    """返回带时区的 ISO 8601 时间戳（微秒精度），用于入库与排序。"""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")
