from __future__ import annotations

from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

WINDOW_POLICY_MONTH = "MONTH"
WINDOW_POLICY_DAYS = "DAYS"


def _as_int_or_default(raw, default: int) -> int:
    try:
        return int(raw)
    except Exception:
        return default


def normalize_lag_days(lag_days) -> int:
    return max(1, _as_int_or_default(lag_days, 1))


def compute_default_window(as_of_date: date, lag_days, policy: str = WINDOW_POLICY_MONTH, window_days: int = 30):
    """
    Default window rule:
      end = as_of_date - lag_days
      MONTH: start = (end + 1 day) - 1 month
      DAYS : start = end - (window_days - 1)
    """
    lag = normalize_lag_days(lag_days)
    end_dt = as_of_date - timedelta(days=lag)

    if (policy or WINDOW_POLICY_MONTH).upper() == WINDOW_POLICY_DAYS:
        wd = max(1, _as_int_or_default(window_days, 30))
        start_dt = end_dt - timedelta(days=wd - 1)
    else:
        start_dt = (end_dt + timedelta(days=1)) - relativedelta(months=1)

    return start_dt, end_dt


def days_in_window(start_dt: date, end_dt: date) -> int:
    return (end_dt - start_dt).days + 1


def next_refresh_date(today: date, refresh_days=(1, 15)) -> date:
    days = sorted({int(d) for d in refresh_days if 1 <= int(d) <= 31}) or [1, 15]
    for d in days:
        if today.day < d:
            return today.replace(day=d)
    first_next = today.replace(day=1) + relativedelta(months=1)
    return first_next.replace(day=days[0])


def first_validation_business_date(today: date, validation_delay_days):
    lag = normalize_lag_days(validation_delay_days)
    return today - timedelta(days=lag)
