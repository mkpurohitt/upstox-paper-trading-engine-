from datetime import date

from broker_gateway.symbols import TOKENS, default_map, kite_tradingsymbol, noren_tradingsymbol, to_canonical
from market_data.symbols import future_symbol, option_symbol, parse


def test_kite_weekly_vs_monthly():
    weekly = parse(option_symbol("NIFTY", date(2026, 11, 17), 26200, "CE"))
    monthly = parse(option_symbol("NIFTY", date(2026, 11, 23), 26200, "PE"))  # last Tuesday (24th) is a holiday -> 23rd
    assert kite_tradingsymbol(weekly) == "NIFTY26N1726200CE"
    assert kite_tradingsymbol(monthly) == "NIFTY26NOV26200PE"
    assert kite_tradingsymbol(parse(future_symbol("BANKNIFTY", date(2026, 12, 29)))) == "BANKNIFTY26DECFUT"


def test_noren_and_angel_and_fyers():
    o = option_symbol("NIFTY", date(2026, 11, 17), 26200, "PE")
    assert noren_tradingsymbol(parse(o)) == "NIFTY17NOV26P26200"
    assert noren_tradingsymbol(parse("NSE:SBIN")) == "SBIN-EQ"
    assert default_map("angel", "NSE:SBIN")["tradingsymbol"] == "SBIN-EQ"
    assert default_map("fyers", "NSE:SBIN")["tradingsymbol"] == "NSE:SBIN-EQ"
    assert default_map("fyers", o)["tradingsymbol"] == "NSE:NIFTY26N1726200PE"
    assert default_map("dhan", o)["exchange"] == "NSE_FNO"
    assert default_map("kotak", "NSE:SBIN")["exchange"] == "nse_cm"


def test_reverse_mapping():
    assert to_canonical("zerodha", "NFO", "NIFTY26N1726200CE") == "NFO:NIFTY17NOV2626200CE"
    assert to_canonical("zerodha", "NFO", "NIFTY26NOV26200PE") == "NFO:NIFTY23NOV2626200PE"
    assert to_canonical("angel", "NSE", "SBIN-EQ") == "NSE:SBIN"
    assert to_canonical("fyers", "", "NSE:RELIANCE-EQ") == "NSE:RELIANCE"
    assert to_canonical("shoonya", "NFO", "NIFTY17NOV26C26200") == "NFO:NIFTY17NOV2626200CE"
    TOKENS.set("dhan", {"NSE:SBIN": "3045"})
    assert to_canonical("dhan", "NSE_EQ", "SBIN", token="3045") == "NSE:SBIN"
