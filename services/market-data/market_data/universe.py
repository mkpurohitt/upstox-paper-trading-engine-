"""Static reference universe used by the mock provider (and as metadata
fallback in live mode). Prices are illustrative anchors only."""

from __future__ import annotations

from dataclasses import dataclass, field

# Anchor dates for the deterministic Brownian-bridge history
HISTORY_START = "2019-01-01"
ANCHOR_DATE = "2026-11-13"


@dataclass(frozen=True)
class Asset:
    symbol: str  # canonical spot symbol
    name: str
    kind: str  # index | equity | commodity
    price: float  # anchor price at ANCHOR_DATE
    p0: float  # price at HISTORY_START
    vol: float  # annualised volatility
    sector: str | None = None
    industry: str | None = None
    mcap_cr: float | None = None
    lot_size: int | None = None  # F&O lot size; None = no derivatives
    freeze_qty: int | None = None
    beta: float = 1.0
    base_volume: float = 2_000_000
    indices: tuple[str, ...] = field(default_factory=tuple)

    @property
    def tradingsymbol(self) -> str:
        return self.symbol.split(":", 1)[1]

    @property
    def exchange(self) -> str:
        return self.symbol.split(":", 1)[0]


INDICES: list[Asset] = [
    Asset("NSE_INDEX:NIFTY", "Nifty 50", "index", 26_180, 10_860, 0.14, lot_size=65, freeze_qty=1800, base_volume=0),
    Asset("NSE_INDEX:BANKNIFTY", "Nifty Bank", "index", 59_820, 27_390, 0.17, lot_size=30, freeze_qty=900, beta=1.15, base_volume=0),
    Asset("NSE_INDEX:FINNIFTY", "Nifty Financial Services", "index", 27_940, 11_330, 0.16, lot_size=60, freeze_qty=1800, beta=1.1, base_volume=0),
    Asset("NSE_INDEX:MIDCPNIFTY", "Nifty Midcap Select", "index", 13_880, 5_400, 0.18, lot_size=120, freeze_qty=2800, beta=1.2, base_volume=0),
    Asset("NSE_INDEX:NIFTYIT", "Nifty IT", "index", 36_400, 14_400, 0.2, beta=0.8, base_volume=0),
    Asset("NSE_INDEX:NIFTYPHARMA", "Nifty Pharma", "index", 22_800, 8_900, 0.17, beta=0.6, base_volume=0),
    Asset("NSE_INDEX:NIFTYAUTO", "Nifty Auto", "index", 27_100, 10_600, 0.19, beta=1.0, base_volume=0),
    Asset("NSE_INDEX:NIFTYFMCG", "Nifty FMCG", "index", 56_200, 29_800, 0.13, beta=0.6, base_volume=0),
    Asset("NSE_INDEX:NIFTYMETAL", "Nifty Metal", "index", 10_150, 3_300, 0.25, beta=1.3, base_volume=0),
    Asset("NSE_INDEX:NIFTYREALTY", "Nifty Realty", "index", 960, 240, 0.28, beta=1.4, base_volume=0),
    Asset("NSE_INDEX:NIFTYENERGY", "Nifty Energy", "index", 36_900, 14_500, 0.19, beta=1.0, base_volume=0),
    Asset("NSE_INDEX:INDIAVIX", "India VIX", "index", 12.8, 16.3, 0.85, beta=-1.0, base_volume=0),
    Asset("BSE_INDEX:SENSEX", "S&P BSE Sensex", "index", 85_640, 36_070, 0.14, lot_size=20, freeze_qty=1000, base_volume=0),
    Asset("BSE_INDEX:BANKEX", "S&P BSE Bankex", "index", 66_100, 30_800, 0.17, lot_size=30, freeze_qty=900, beta=1.15, base_volume=0),
]

_E = "equity"
EQUITIES: list[Asset] = [
    Asset("NSE:RELIANCE", "Reliance Industries", _E, 1_524, 560, 0.24, "Energy", "Refineries & Telecom", 2_062_000, 500, beta=1.0, base_volume=9e6),
    Asset("NSE:HDFCBANK", "HDFC Bank", _E, 1_008, 530, 0.2, "Financial Services", "Private Bank", 1_545_000, 550, beta=1.0, base_volume=1.5e7),
    Asset("NSE:ICICIBANK", "ICICI Bank", _E, 1_382, 360, 0.22, "Financial Services", "Private Bank", 985_000, 700, beta=1.1, base_volume=1.2e7),
    Asset("NSE:TCS", "Tata Consultancy Services", _E, 3_148, 1_880, 0.21, "Information Technology", "IT Services", 1_139_000, 175, beta=0.7, base_volume=2.5e6),
    Asset("NSE:INFY", "Infosys", _E, 1_562, 660, 0.24, "Information Technology", "IT Services", 648_000, 400, beta=0.75, base_volume=7e6),
    Asset("NSE:BHARTIARTL", "Bharti Airtel", _E, 2_084, 310, 0.22, "Telecommunication", "Telecom Services", 1_250_000, 475, beta=0.8, base_volume=6e6),
    Asset("NSE:SBIN", "State Bank of India", _E, 942, 295, 0.26, "Financial Services", "Public Bank", 869_000, 750, beta=1.2, base_volume=1.4e7),
    Asset("NSE:ITC", "ITC", _E, 412, 280, 0.19, "FMCG", "Diversified FMCG", 515_000, 1600, beta=0.6, base_volume=1.3e7),
    Asset("NSE:LT", "Larsen & Toubro", _E, 3_948, 1_340, 0.23, "Capital Goods", "Construction & Engineering", 543_000, 175, beta=1.1, base_volume=2e6),
    Asset("NSE:HINDUNILVR", "Hindustan Unilever", _E, 2_452, 1_780, 0.18, "FMCG", "Personal Products", 576_000, 300, beta=0.5, base_volume=1.6e6),
    Asset("NSE:KOTAKBANK", "Kotak Mahindra Bank", _E, 2_148, 1_230, 0.22, "Financial Services", "Private Bank", 427_000, 400, beta=0.9, base_volume=3e6),
    Asset("NSE:AXISBANK", "Axis Bank", _E, 1_222, 620, 0.25, "Financial Services", "Private Bank", 378_000, 625, beta=1.2, base_volume=6e6),
    Asset("NSE:BAJFINANCE", "Bajaj Finance", _E, 1_018, 245, 0.3, "Financial Services", "NBFC", 632_000, 750, beta=1.3, base_volume=5e6),
    Asset("NSE:MARUTI", "Maruti Suzuki", _E, 16_210, 7_460, 0.24, "Automobile", "Passenger Cars", 509_000, 50, beta=0.9, base_volume=5e5),
    Asset("NSE:SUNPHARMA", "Sun Pharmaceutical", _E, 1_748, 430, 0.22, "Healthcare", "Pharmaceuticals", 419_000, 350, beta=0.6, base_volume=2.5e6),
    Asset("NSE:TITAN", "Titan Company", _E, 3_802, 980, 0.25, "Consumer Durables", "Jewellery", 337_000, 175, beta=0.9, base_volume=1.2e6),
    Asset("NSE:ASIANPAINT", "Asian Paints", _E, 2_548, 1_380, 0.23, "Consumer Durables", "Paints", 244_000, 250, beta=0.7, base_volume=1.5e6),
    Asset("NSE:ULTRACEMCO", "UltraTech Cement", _E, 12_080, 3_850, 0.24, "Construction Materials", "Cement", 356_000, 50, beta=0.9, base_volume=3e5),
    Asset("NSE:NESTLEIND", "Nestle India", _E, 1_248, 560, 0.18, "FMCG", "Packaged Foods", 120_000, 500, beta=0.5, base_volume=8e5),
    Asset("NSE:WIPRO", "Wipro", _E, 256, 110, 0.26, "Information Technology", "IT Services", 268_000, 3000, beta=0.8, base_volume=1e7),
    Asset("NSE:HCLTECH", "HCL Technologies", _E, 1_618, 480, 0.24, "Information Technology", "IT Services", 439_000, 350, beta=0.75, base_volume=3e6),
    Asset("NSE:TECHM", "Tech Mahindra", _E, 1_522, 720, 0.27, "Information Technology", "IT Services", 149_000, 600, beta=0.85, base_volume=2e6),
    Asset("NSE:POWERGRID", "Power Grid Corporation", _E, 291, 90, 0.22, "Power", "Power Transmission", 270_000, 3800, beta=0.7, base_volume=1.2e7),
    Asset("NSE:NTPC", "NTPC", _E, 342, 100, 0.24, "Power", "Power Generation", 331_000, 1500, beta=0.8, base_volume=1.4e7),
    Asset("NSE:ONGC", "Oil & Natural Gas Corporation", _E, 249, 130, 0.29, "Oil Gas & Consumable Fuels", "Oil Exploration", 313_000, 2250, beta=1.0, base_volume=1.5e7),
    Asset("NSE:COALINDIA", "Coal India", _E, 389, 190, 0.27, "Oil Gas & Consumable Fuels", "Coal", 240_000, 1350, beta=0.8, base_volume=9e6),
    Asset("NSE:TATASTEEL", "Tata Steel", _E, 176, 50, 0.32, "Metals & Mining", "Steel", 220_000, 5500, beta=1.4, base_volume=3e7),
    Asset("NSE:JSWSTEEL", "JSW Steel", _E, 1_152, 290, 0.29, "Metals & Mining", "Steel", 282_000, 675, beta=1.3, base_volume=2.5e6),
    Asset("NSE:HINDALCO", "Hindalco Industries", _E, 821, 220, 0.31, "Metals & Mining", "Aluminium", 184_000, 700, beta=1.4, base_volume=7e6),
    Asset("NSE:ADANIENT", "Adani Enterprises", _E, 2_452, 380, 0.42, "Metals & Mining", "Trading & Infra", 283_000, 300, beta=1.6, base_volume=3e6),
    Asset("NSE:ADANIPORTS", "Adani Ports & SEZ", _E, 1_448, 380, 0.34, "Services", "Ports", 313_000, 475, beta=1.4, base_volume=3.5e6),
    Asset("NSE:M&M", "Mahindra & Mahindra", _E, 3_604, 750, 0.26, "Automobile", "Passenger Cars & SUVs", 448_000, 200, beta=1.1, base_volume=3e6),
    Asset("NSE:EICHERMOT", "Eicher Motors", _E, 6_980, 2_250, 0.27, "Automobile", "2/3 Wheelers", 191_000, 175, beta=0.9, base_volume=7e5),
    Asset("NSE:BAJAJ-AUTO", "Bajaj Auto", _E, 9_040, 2_710, 0.25, "Automobile", "2/3 Wheelers", 252_000, 75, beta=0.9, base_volume=6e5),
    Asset("NSE:HEROMOTOCO", "Hero MotoCorp", _E, 5_510, 3_170, 0.27, "Automobile", "2/3 Wheelers", 110_000, 150, beta=0.9, base_volume=7e5),
    Asset("NSE:DRREDDY", "Dr. Reddy's Laboratories", _E, 1_252, 530, 0.23, "Healthcare", "Pharmaceuticals", 104_000, 625, beta=0.6, base_volume=1.5e6),
    Asset("NSE:CIPLA", "Cipla", _E, 1_548, 520, 0.24, "Healthcare", "Pharmaceuticals", 125_000, 375, beta=0.6, base_volume=2e6),
    Asset("NSE:APOLLOHOSP", "Apollo Hospitals", _E, 7_610, 1_270, 0.27, "Healthcare", "Hospitals", 109_000, 125, beta=0.8, base_volume=4e5),
    Asset("NSE:GRASIM", "Grasim Industries", _E, 2_802, 820, 0.25, "Construction Materials", "Cement & VSF", 190_000, 250, beta=1.0, base_volume=8e5),
    Asset("NSE:BRITANNIA", "Britannia Industries", _E, 6_005, 3_100, 0.2, "FMCG", "Packaged Foods", 145_000, 125, beta=0.5, base_volume=4e5),
    Asset("NSE:TATACONSUM", "Tata Consumer Products", _E, 1_148, 220, 0.25, "FMCG", "Tea & Coffee", 113_000, 550, beta=0.7, base_volume=1.8e6),
    Asset("NSE:INDUSINDBK", "IndusInd Bank", _E, 782, 1_550, 0.38, "Financial Services", "Private Bank", 61_000, 700, beta=1.5, base_volume=5e6),
    Asset("NSE:SHRIRAMFIN", "Shriram Finance", _E, 752, 250, 0.33, "Financial Services", "NBFC", 141_000, 825, beta=1.3, base_volume=4e6),
    Asset("NSE:BEL", "Bharat Electronics", _E, 421, 30, 0.33, "Capital Goods", "Defence", 307_000, 1425, beta=1.2, base_volume=1.6e7),
    Asset("NSE:HDFCLIFE", "HDFC Life Insurance", _E, 772, 360, 0.23, "Financial Services", "Life Insurance", 166_000, 1100, beta=0.8, base_volume=3e6),
    Asset("NSE:SBILIFE", "SBI Life Insurance", _E, 1_948, 610, 0.22, "Financial Services", "Life Insurance", 195_000, 375, beta=0.8, base_volume=1.2e6),
    Asset("NSE:BAJAJFINSV", "Bajaj Finserv", _E, 2_052, 650, 0.27, "Financial Services", "Holding / Insurance", 327_000, 250, beta=1.1, base_volume=1.5e6),
    Asset("NSE:TRENT", "Trent", _E, 4_702, 340, 0.36, "Consumer Services", "Retail", 167_000, 100, beta=1.2, base_volume=1.2e6),
    Asset("NSE:ETERNAL", "Eternal (Zomato)", _E, 322, 55, 0.42, "Consumer Services", "Food Delivery", 311_000, 2425, beta=1.4, base_volume=4e7),
    Asset("NSE:JIOFIN", "Jio Financial Services", _E, 312, 230, 0.35, "Financial Services", "NBFC", 198_000, 2350, beta=1.2, base_volume=1.8e7),
    Asset("NSE:HAL", "Hindustan Aeronautics", _E, 4_702, 380, 0.38, "Capital Goods", "Defence", 314_000, 150, beta=1.3, base_volume=1.8e6),
    Asset("NSE:DLF", "DLF", _E, 781, 180, 0.36, "Realty", "Real Estate", 193_000, 825, beta=1.5, base_volume=5e6),
    Asset("NSE:VEDL", "Vedanta", _E, 502, 200, 0.36, "Metals & Mining", "Diversified Metals", 196_000, 1150, beta=1.4, base_volume=1.1e7),
    Asset("NSE:PNB", "Punjab National Bank", _E, 116, 75, 0.36, "Financial Services", "Public Bank", 133_000, 8000, beta=1.4, base_volume=4e7),
    Asset("NSE:BANKBARODA", "Bank of Baroda", _E, 271, 120, 0.33, "Financial Services", "Public Bank", 140_000, 2925, beta=1.4, base_volume=1.2e7),
    Asset("NSE:IOC", "Indian Oil Corporation", _E, 151, 120, 0.3, "Oil Gas & Consumable Fuels", "Refineries", 213_000, 4875, beta=1.0, base_volume=2e7),
    Asset("NSE:DMART", "Avenue Supermarts", _E, 4_205, 1_480, 0.27, "Consumer Services", "Retail", 273_000, 150, beta=0.8, base_volume=5e5),
    Asset("NSE:IRCTC", "Indian Railway Catering & Tourism", _E, 721, 140, 0.33, "Consumer Services", "Travel Services", 57_000, 875, beta=1.1, base_volume=3e6),
    Asset("NSE:PIDILITIND", "Pidilite Industries", _E, 1_502, 570, 0.22, "Chemicals", "Adhesives", 152_000, 500, beta=0.6, base_volume=9e5),
    Asset("NSE:LICI", "Life Insurance Corporation", _E, 902, 940, 0.27, "Financial Services", "Life Insurance", 571_000, 700, beta=0.9, base_volume=2e6),
]

COMMODITY_ASSETS: list[Asset] = [
    Asset("MCX:CRUDEOIL", "Crude Oil (MCX)", "commodity", 5_620, 3_900, 0.38, "Commodities", "Energy", lot_size=100, base_volume=1.5e4),
    Asset("MCX:NATURALGAS", "Natural Gas (MCX)", "commodity", 318, 260, 0.6, "Commodities", "Energy", lot_size=1250, base_volume=4e4),
    Asset("MCX:GOLD", "Gold (MCX, ₹/10g)", "commodity", 124_500, 31_500, 0.15, "Commodities", "Bullion", lot_size=1, base_volume=8e3),
    Asset("MCX:SILVER", "Silver (MCX, ₹/kg)", "commodity", 154_000, 39_000, 0.25, "Commodities", "Bullion", lot_size=1, base_volume=1e4),
    Asset("MCX:COPPER", "Copper (MCX, ₹/kg)", "commodity", 1_012, 440, 0.24, "Commodities", "Base Metals", lot_size=2500, base_volume=5e3),
]

ALL_ASSETS: list[Asset] = INDICES + EQUITIES + COMMODITY_ASSETS
BY_SYMBOL: dict[str, Asset] = {a.symbol: a for a in ALL_ASSETS}

# sector index -> constituent sectors (for the heatmap / overview)
SECTOR_INDEX = {
    "Financial Services": "NSE_INDEX:FINNIFTY",
    "Information Technology": "NSE_INDEX:NIFTYIT",
    "Healthcare": "NSE_INDEX:NIFTYPHARMA",
    "Automobile": "NSE_INDEX:NIFTYAUTO",
    "FMCG": "NSE_INDEX:NIFTYFMCG",
    "Metals & Mining": "NSE_INDEX:NIFTYMETAL",
    "Realty": "NSE_INDEX:NIFTYREALTY",
    "Energy": "NSE_INDEX:NIFTYENERGY",
}

NIFTY50 = [a.symbol for a in EQUITIES][:50]
NIFTY_BANK = ["NSE:HDFCBANK", "NSE:ICICIBANK", "NSE:SBIN", "NSE:KOTAKBANK", "NSE:AXISBANK", "NSE:INDUSINDBK",
              "NSE:PNB", "NSE:BANKBARODA"]

UNIVERSES: dict[str, list[str]] = {
    "NIFTY50": NIFTY50,
    "NIFTY100": [a.symbol for a in EQUITIES],
    "BANKNIFTY": NIFTY_BANK,
    "FNO": [a.symbol for a in EQUITIES if a.lot_size],
    "COMMODITIES": [a.symbol for a in COMMODITY_ASSETS],
}

DERIVATIVE_UNDERLYINGS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"] + [
    a.tradingsymbol for a in EQUITIES if a.lot_size
] + [a.tradingsymbol for a in COMMODITY_ASSETS]

# Mock implied-volatility base levels by underlying (decimal)
BASE_IV = {"NIFTY": 0.12, "BANKNIFTY": 0.145, "FINNIFTY": 0.14, "MIDCPNIFTY": 0.17, "SENSEX": 0.125, "BANKEX": 0.15}


def asset_for_underlying(underlying: str) -> Asset | None:
    from market_data.symbols import underlying_spot_symbol

    return BY_SYMBOL.get(underlying_spot_symbol(underlying))
