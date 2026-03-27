import os
import pandas as pd
import numpy as np
from datetime import date

GOTRADE_COLUMNS = [
    "date", "ticker", "shares", "price_usd",
    "usd_idr_rate", "total_cost_usd", "total_cost_idr", "notes",
]
GOTRADE_DTYPES = {
    "ticker": str,
    "shares": float,        # bisa fractional
    "price_usd": float,
    "usd_idr_rate": float,
    "total_cost_usd": float,
    "total_cost_idr": float,
    "notes": str,
}


def load_gotrade_history(filepath: str) -> pd.DataFrame:
    """Load riwayat GoTrade dari CSV. Return DataFrame kosong jika file belum ada."""
    if not os.path.exists(filepath):
        return pd.DataFrame(columns=GOTRADE_COLUMNS)
    try:
        df = pd.read_csv(filepath, dtype=GOTRADE_DTYPES, parse_dates=["date"])
        df["total_cost_usd"] = df["shares"] * df["price_usd"]
        df["total_cost_idr"] = df["total_cost_usd"] * df["usd_idr_rate"]
        df = df.sort_values("date").reset_index(drop=True)
        return df
    except Exception:
        return pd.DataFrame(columns=GOTRADE_COLUMNS)


def save_gotrade_transaction(
    filepath: str,
    tanggal: date,
    ticker: str,
    shares: float,
    price_usd: float,
    usd_idr_rate: float,
    notes: str = "",
) -> None:
    """Tambah satu transaksi GoTrade baru ke CSV."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    total_cost_usd = shares * price_usd
    total_cost_idr = total_cost_usd * usd_idr_rate
    new_row = pd.DataFrame([{
        "date": pd.Timestamp(tanggal),
        "ticker": ticker,
        "shares": shares,
        "price_usd": price_usd,
        "usd_idr_rate": usd_idr_rate,
        "total_cost_usd": total_cost_usd,
        "total_cost_idr": total_cost_idr,
        "notes": notes,
    }])
    history = load_gotrade_history(filepath)
    updated = pd.concat([history, new_row], ignore_index=True)
    updated.to_csv(filepath, index=False)


def save_gotrade_history(filepath: str, df: pd.DataFrame) -> None:
    """Overwrite seluruh CSV GoTrade (untuk delete)."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    df.to_csv(filepath, index=False)


def compute_gotrade_holdings(history: pd.DataFrame) -> dict[str, float]:
    """Hitung total shares per ticker."""
    if history.empty:
        return {}
    return history.groupby("ticker")["shares"].sum().to_dict()


def compute_gotrade_cost_basis(history: pd.DataFrame) -> dict[str, dict]:
    """
    Hitung cost basis GoTrade per ticker.
    avg_price_usd = VWAP dalam USD
    total_cost_idr = akumulasi IDR saat pembelian (pakai kurs historis)
    """
    if history.empty:
        return {}
    result = {}
    for ticker, group in history.groupby("ticker"):
        total_shares = float(group["shares"].sum())
        total_cost_usd = float(group["total_cost_usd"].sum())
        total_cost_idr = float(group["total_cost_idr"].sum())
        avg_price_usd = total_cost_usd / total_shares if total_shares > 0 else 0
        avg_rate = total_cost_idr / total_cost_usd if total_cost_usd > 0 else 0
        result[ticker] = {
            "shares": round(total_shares, 6),
            "total_cost_usd": round(total_cost_usd, 2),
            "total_cost_idr": round(total_cost_idr, 0),
            "avg_price_usd": round(avg_price_usd, 2),
            "avg_usd_idr_rate": round(avg_rate, 0),
        }
    return result


def compute_gotrade_unrealized_pl(
    cost_basis: dict[str, dict],
    live_prices_usd: dict[str, float | None],
    current_usd_idr_rate: float,
) -> dict[str, dict]:
    """
    Hitung unrealized P/L GoTrade dalam USD dan IDR.
    Gunakan kurs saat ini untuk konversi ke IDR.
    """
    result = {}
    for ticker, basis in cost_basis.items():
        price_usd = live_prices_usd.get(ticker)
        if price_usd is None:
            result[ticker] = {
                "market_value_usd": None,
                "market_value_idr": None,
                "unrealized_usd": None,
                "unrealized_idr": None,
                "unrealized_pct": None,
            }
            continue
        market_value_usd = basis["shares"] * price_usd
        market_value_idr = market_value_usd * current_usd_idr_rate
        unrealized_usd = market_value_usd - basis["total_cost_usd"]
        unrealized_idr = market_value_idr - basis["total_cost_idr"]
        unrealized_pct = (unrealized_usd / basis["total_cost_usd"] * 100) if basis["total_cost_usd"] > 0 else 0
        result[ticker] = {
            "market_value_usd": round(market_value_usd, 2),
            "market_value_idr": round(market_value_idr, 0),
            "unrealized_usd": round(unrealized_usd, 2),
            "unrealized_idr": round(unrealized_idr, 0),
            "unrealized_pct": round(unrealized_pct, 2),
        }
    return result


def compute_gotrade_trajectory(
    history: pd.DataFrame,
    live_prices_usd: dict[str, float | None],
    current_usd_idr_rate: float,
) -> pd.DataFrame:
    """
    Rekonstruksi nilai GoTrade portfolio per bulan.
    Nilai IDR menggunakan kurs historis saat pembelian sebagai proxy,
    kecuali bulan terakhir pakai harga live + kurs saat ini.
    """
    if history.empty:
        return pd.DataFrame(columns=["date", "total_invested_idr", "estimated_market_value_idr"])

    start = history["date"].min().to_period("M")
    end = pd.Timestamp(date.today()).to_period("M")
    months = pd.period_range(start=start, end=end, freq="M")

    rows = []
    for period in months:
        period_end = period.to_timestamp(how="end")
        mask = history["date"] <= period_end
        subset = history[mask]

        if subset.empty:
            continue

        total_invested_idr = float(subset["total_cost_idr"].sum())
        is_current_month = (period == end)
        estimated_value_idr = 0.0

        for ticker, group in subset.groupby("ticker"):
            shares = float(group["shares"].sum())
            if is_current_month and live_prices_usd.get(ticker):
                price_usd = live_prices_usd[ticker]
                rate = current_usd_idr_rate
            else:
                total_cost_usd = float(group["total_cost_usd"].sum())
                price_usd = total_cost_usd / shares if shares > 0 else 0
                total_cost_idr = float(group["total_cost_idr"].sum())
                rate = total_cost_idr / total_cost_usd if total_cost_usd > 0 else current_usd_idr_rate
            estimated_value_idr += shares * price_usd * rate

        rows.append({
            "date": period.to_timestamp(),
            "total_invested_idr": total_invested_idr,
            "estimated_market_value_idr": estimated_value_idr,
        })

    return pd.DataFrame(rows)
