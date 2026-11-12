from datetime import date, datetime

import jdatetime


def to_jalali(value: date | datetime | None, with_time: bool = False) -> str:
    """Format a Gregorian date/datetime as a Jalali (Shamsi) string, e.g. 1405/07/10."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        j = jdatetime.datetime.fromgregorian(datetime=value)
        return j.strftime("%Y/%m/%d %H:%M") if with_time else j.strftime("%Y/%m/%d")
    return jdatetime.date.fromgregorian(date=value).strftime("%Y/%m/%d")


def to_gregorian(value: date | jdatetime.date | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, jdatetime.date):
        return value.togregorian()
    return value
