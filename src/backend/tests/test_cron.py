from datetime import datetime, timezone
from backend.cron import _is_due

NOW = datetime(2026, 6, 17, 12, 0, 0, tzinfo=timezone.utc)


def _job(schedule_type, schedule_value, last_run_at=None, created_at=None):
    return {
        "schedule_type": schedule_type,
        "schedule_value": schedule_value,
        "last_run_at": last_run_at,
        "created_at": created_at or datetime(2026, 1, 1, tzinfo=timezone.utc),
    }


def test_at_fires_when_time_has_passed():
    assert _is_due(_job("at", "2026-06-17T11:00:00+00:00"), NOW)


def test_at_does_not_fire_before_scheduled_time():
    assert not _is_due(_job("at", "2026-06-17T13:00:00+00:00"), NOW)


def test_at_does_not_fire_if_already_ran():
    job = _job("at", "2026-06-17T11:00:00+00:00", last_run_at=datetime(2026, 6, 17, 11, 0, tzinfo=timezone.utc))
    assert not _is_due(job, NOW)


def test_cron_fires_when_overdue():
    last = datetime(2026, 6, 17, 11, 58, 0, tzinfo=timezone.utc)  # 2 min ago, every-minute schedule
    assert _is_due(_job("cron", "* * * * *", last_run_at=last), NOW)


def test_cron_does_not_fire_before_next_tick():
    # last ran at 12:00 exactly; next hourly tick is 13:00, which is after NOW (12:00)
    last = datetime(2026, 6, 17, 12, 0, 0, tzinfo=timezone.utc)
    assert not _is_due(_job("cron", "0 * * * *", last_run_at=last), NOW)


def test_cron_uses_created_at_when_never_run():
    created = datetime(2026, 6, 17, 11, 58, 0, tzinfo=timezone.utc)
    assert _is_due(_job("cron", "* * * * *", last_run_at=None, created_at=created), NOW)
