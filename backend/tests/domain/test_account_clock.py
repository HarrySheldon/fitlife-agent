from datetime import date, datetime, timezone

from backend.domain.account_clock import local_today, local_week_bounds


def test_account_clock_resolves_date_and_week_in_user_timezone():
    now = datetime(2026, 7, 13, 0, 30, tzinfo=timezone.utc)

    assert local_today("Asia/Shanghai", now=now) == date(2026, 7, 13)
    assert local_today("America/Los_Angeles", now=now) == date(2026, 7, 12)
    assert local_week_bounds("Asia/Shanghai", now=now) == (date(2026, 7, 13), date(2026, 7, 19))
    assert local_week_bounds("America/Los_Angeles", now=now) == (date(2026, 7, 6), date(2026, 7, 12))


def test_account_clock_accepts_explicit_local_date_for_week_selection():
    assert local_week_bounds("Asia/Shanghai", selected=date(2026, 7, 8)) == (
        date(2026, 7, 6),
        date(2026, 7, 12),
    )

