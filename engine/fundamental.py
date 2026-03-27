import yfinance as yf
import streamlit as st
import requests


def _make_session() -> requests.Session:
    """Session dengan User-Agent agar tidak diblokir Yahoo Finance."""
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    })
    return s


# ── Data fundamental manual (fallback jika Yahoo Finance tidak tersedia) ──────
# Sumber: Laporan Keuangan Q4 2024 / IDX / Stockbit
# Update terakhir: Maret 2026
MANUAL_FUNDAMENTALS = {
    "BBRI": {
        "PER": 8.5,
        "PBV": 1.7,
        "ROE": 19.2,
        "EPS": 318.0,
        "Forward PER": 8.2,
        "Market Cap": 510_000_000_000_000,  # ~Rp 510 T
    },
    "ADRO": {
        "PER": 4.2,
        "PBV": 1.1,
        "ROE": 26.5,
        "EPS": 890.0,
        "Forward PER": 5.0,
        "Market Cap": 78_000_000_000_000,   # ~Rp 78 T
    },
    "TLKM": {
        "PER": 14.5,
        "PBV": 2.3,
        "ROE": 16.8,
        "EPS": 198.0,
        "Forward PER": 13.8,
        "Market Cap": 273_000_000_000_000,  # ~Rp 273 T
    },
}
MANUAL_DATA_DATE = "Maret 2026"

# Rentang valuasi historis per saham untuk sinyal Murah/Wajar/Mahal
# Sumber: rata-rata historis IDX, disesuaikan per sektor
VALUATION_RANGES = {
    "BBRI": {
        "PER": {"murah": (0, 8),    "wajar": (8, 14),   "mahal": (14, 9999)},
        "PBV": {"murah": (0, 1.5),  "wajar": (1.5, 2.5), "mahal": (2.5, 9999)},
        "ROE": {"rendah": (0, 10),  "normal": (10, 18),  "tinggi": (18, 9999)},
    },
    "ADRO": {
        "PER": {"murah": (0, 5),    "wajar": (5, 10),   "mahal": (10, 9999)},
        "PBV": {"murah": (0, 1.0),  "wajar": (1.0, 2.0), "mahal": (2.0, 9999)},
        "ROE": {"rendah": (0, 8),   "normal": (8, 20),   "tinggi": (20, 9999)},
    },
    "TLKM": {
        "PER": {"murah": (0, 12),   "wajar": (12, 20),  "mahal": (20, 9999)},
        "PBV": {"murah": (0, 2.0),  "wajar": (2.0, 4.0), "mahal": (4.0, 9999)},
        "ROE": {"rendah": (0, 12),  "normal": (12, 22),  "tinggi": (22, 9999)},
    },
}

SIGNAL_EMOJI = {
    "murah":  ("🟢", "Murah"),
    "wajar":  ("🟡", "Wajar"),
    "mahal":  ("🔴", "Mahal"),
    "rendah": ("🔴", "Rendah"),
    "normal": ("🟡", "Normal"),
    "tinggi": ("🟢", "Tinggi"),
    "n/a":    ("⚪", "N/A"),
}


def _classify(value: float | None, ranges: dict) -> str:
    """Klasifikasi nilai ke kategori berdasarkan rentang."""
    if value is None or value <= 0:
        return "n/a"
    for label, (lo, hi) in ranges.items():
        if lo <= value < hi:
            return label
    return "n/a"


def _build_result(per, pbv, roe_pct, eps, fpe, mcap, stock_code, source) -> dict:
    ranges = VALUATION_RANGES.get(stock_code, {})
    per_signal = _classify(per,     ranges.get("PER", {}))
    pbv_signal = _classify(pbv,     ranges.get("PBV", {}))
    roe_signal = _classify(roe_pct, ranges.get("ROE", {}))
    score = _calculate_dca_score(per_signal, pbv_signal, roe_signal)
    return {
        "PER":         round(per, 2) if per else None,
        "PBV":         round(pbv, 2) if pbv else None,
        "ROE":         round(roe_pct, 1) if roe_pct else None,
        "EPS":         round(eps, 0) if eps else None,
        "Forward PER": round(fpe, 2) if fpe else None,
        "Market Cap":  mcap,
        "per_signal":  per_signal,
        "pbv_signal":  pbv_signal,
        "roe_signal":  roe_signal,
        "dca_score":   score,
        "source":      source,
    }


@st.cache_data(ttl=3600)
def fetch_fundamentals(ticker: str, stock_code: str) -> dict:
    """
    Ambil data fundamental. Prioritas:
    1. Yahoo Finance (live)
    2. Data manual dari laporan keuangan terbaru (fallback)
    """
    # Coba Yahoo Finance dulu
    try:
        session = _make_session()
        info = yf.Ticker(ticker, session=session).info
        per  = info.get("trailingPE")
        pbv  = info.get("priceToBook")
        roe  = info.get("returnOnEquity")
        eps  = info.get("trailingEps")
        fpe  = info.get("forwardPE")
        mcap = info.get("marketCap")
        roe_pct = roe * 100 if roe is not None else None

        # Hanya pakai jika minimal ada 2 dari 3 metrik utama
        available = sum(1 for v in [per, pbv, roe_pct] if v is not None)
        if available >= 2:
            return _build_result(per, pbv, roe_pct, eps, fpe, mcap, stock_code, "live")
    except Exception:
        pass

    # Fallback: data manual dari laporan keuangan
    if stock_code in MANUAL_FUNDAMENTALS:
        m = MANUAL_FUNDAMENTALS[stock_code]
        return _build_result(
            m["PER"], m["PBV"], m["ROE"],
            m["EPS"], m["Forward PER"], m["Market Cap"],
            stock_code, f"manual ({MANUAL_DATA_DATE})",
        )

    return {
        "PER": None, "PBV": None, "ROE": None,
        "EPS": None, "Forward PER": None, "Market Cap": None,
        "per_signal": "n/a", "pbv_signal": "n/a", "roe_signal": "n/a",
        "dca_score": 0,
        "source": "error",
    }


def _calculate_dca_score(per_signal: str, pbv_signal: str, roe_signal: str) -> int:
    """
    Hitung skor ketertarikan DCA (0–100).
    PER dan PBV rendah = bagus (murah), ROE tinggi = bagus.
    Bobot: PER 40%, PBV 40%, ROE 20%.
    """
    per_score = {"murah": 100, "wajar": 50, "mahal": 0,  "n/a": 25}.get(per_signal, 25)
    pbv_score = {"murah": 100, "wajar": 50, "mahal": 0,  "n/a": 25}.get(pbv_signal, 25)
    roe_score = {"tinggi": 100, "normal": 60, "rendah": 20, "n/a": 25}.get(roe_signal, 25)
    return int(per_score * 0.40 + pbv_score * 0.40 + roe_score * 0.20)


def format_market_cap(value: float | None) -> str:
    if value is None:
        return "N/A"
    if value >= 1e12:
        return f"Rp {value/1e12:.1f} T"
    if value >= 1e9:
        return f"Rp {value/1e9:.1f} M"
    return f"Rp {value/1e6:.0f} jt"
