STOCKS = {
    "BBRI": {
        "ticker": "BBRI.JK",
        "name": "Bank BRI",
        "target_alloc": 0.50,
        "initial_lots": 2,
        "color": "#1f77b4",
        "default_cagr": 0.12,
        "default_div_yield": 0.045,
        "default_volatility": 0.25,
    },
    "ADRO": {
        "ticker": "ADRO.JK",
        "name": "Adaro Energy",
        "target_alloc": 0.30,
        "initial_lots": 4,
        "color": "#ff7f0e",
        "default_cagr": 0.13,
        "default_div_yield": 0.055,
        "default_volatility": 0.32,
    },
    "TLKM": {
        "ticker": "TLKM.JK",
        "name": "Telkom Indonesia",
        "target_alloc": 0.20,
        "initial_lots": 1,
        "color": "#2ca02c",
        "default_cagr": 0.09,
        "default_div_yield": 0.040,
        "default_volatility": 0.20,
    },
}

DCA_MONTHLY = 500_000       # Rp
INVESTMENT_YEARS = 25
LOT_SIZE = 100              # lembar per lot
N_SIMULATIONS = 500

HISTORY_FILE = "data/dca_history.csv"
GOTRADE_HISTORY_FILE = "data/gotrade_history.csv"

# Override default: None = pakai data live, isi angka untuk override
OVERRIDE_DEFAULTS = {
    "BBRI": {"cagr": None, "div_yield": None},
    "ADRO": {"cagr": None, "div_yield": None},
    "TLKM": {"cagr": None, "div_yield": None},
}

# ─── Foreign ETF (GoTrade) ────────────────────────────────────────────────────
FOREIGN_STOCKS = {
    # VTI — tersedia di GoTrade Indonesia, expense ratio 0.03%, cakupan seluruh pasar AS (~4000 saham)
    "VTI": {
        "ticker": "VTI",
        "name": "Vanguard Total Stock Market ETF",
        "currency": "USD",
        "color": "#9467bd",
        "default_cagr": 0.10,
        "default_div_yield": 0.013,
        "default_volatility": 0.18,
        "target_alloc": 0.70,
    },
    "QQQ": {
        "ticker": "QQQ",
        "name": "Invesco Nasdaq 100 ETF",
        "currency": "USD",
        "color": "#e377c2",
        "default_cagr": 0.14,
        "default_div_yield": 0.006,
        "default_volatility": 0.22,
        "target_alloc": 0.30,
    },
}

# Kurs USD/IDR
USD_IDR_BASE = 16_000       # kurs awal (Rp per 1 USD)
IDR_DEPRECIATION = 0.035    # depresiasi IDR 3.5%/tahun (historis)

# Alokasi DCA bulanan default
IDX_DCA_RATIO = 0.40        # 40% dari total DCA ke saham IDX
GOTRADE_DCA_RATIO = 0.60    # 60% dari total DCA ke GoTrade (ETF asing)
