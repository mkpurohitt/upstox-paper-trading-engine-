from datetime import date, datetime

from algo_common.timeutils import IST, expiry_from_date, upcoming_expiries


def test_expiry_rolls_after_close():
    tue = date(2026, 11, 17)  # NIFTY weekly expiry day
    assert expiry_from_date(datetime(2026, 11, 17, 15, 29, tzinfo=IST)) == tue
    assert expiry_from_date(datetime(2026, 11, 17, 15, 30, tzinfo=IST)) == date(2026, 11, 18)
    assert expiry_from_date(datetime(2026, 11, 17, 18, 0, tzinfo=IST), "MCX") == tue
    nxt = upcoming_expiries("NIFTY", expiry_from_date(datetime(2026, 11, 17, 18, 0, tzinfo=IST)), 1)[0]
    assert tue < nxt <= date(2026, 11, 24)  # next weekly (moved back if the Tuesday is a holiday)
