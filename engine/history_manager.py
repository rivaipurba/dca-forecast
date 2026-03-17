import os
import pandas as pd
import numpy as np
from datetime import date, datetime

COLUMNS = ["date", "ticker", "lots", "price_per_share", "total_cost", "notes"]
DTYPES = {"ticker": str, "lots": int, "price_per_share": float, "total_cost": float, "notes": str}


def load_history(filepath: str) -> pd.DataFrame:
    """Load riwayat DCA dari CSV. Return DataFrame kosong jika file belum ada."""
    if not os.path.exists(filepath):
        return pd.DataFrame(columns=COLUMNS)
    try:
        df = pd.read_csv(filepath, dtype=DTYPES, parse_dates=["date"])
        # Pastikan total_cost selalu konsisten
        df["total_cost"] = df["lots"] * 100 * df["price_per_share"]
        df = df.sort_values("date").reset_index(drop=True)
        return df
    except Exception:
        return pd.DataFrame(columns=COLUMNS)


def save_transaction(
    filepath: str,
    tanggal: date,
    ticker: str,
    lots: int,
    price_per_share: float,
    notes: str = "",
) -> None:
    """Tambah satu transaksi baru ke CSV."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    total_cost = lots * 100 * price_per_share
    new_row = pd.DataFrame([{
        "date": pd.Timestamp(tanggal),
        "ticker": ticker,
        "lots": lots,
        "price_per_share": price_per_share,
        "total_cost": total_cost,
        "notes": notes,
    }])
    history = load_history(filepath)
    updated = pd.concat([history, new_row], ignore_index=True)
    updated.to_csv(filepath, index=False)


def save_history(filepath: str, df: pd.DataFrame) -> None:
    """Overwrite seluruh CSV dengan DataFrame yang diberikan (untuk delete)."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    df.to_csv(filepath, index=False)


def compute_holdings(history: pd.DataFrame) -> dict[str, int]:
    """Hitung total lot yang dimiliki per ticker dari riwayat transaksi."""
    if history.empty:
        return {}
    return history.groupby("ticker")["lots"].sum().to_dict()


def compute_cost_basis(history: pd.DataFrame) -> dict[str, dict]:
    """
    Hitung cost basis (HPP) per ticker.
    avg_price = VWAP = total_cost / total_lembar
    """
    if history.empty:
        return {}
    result = {}
    for ticker, group in history.groupby("ticker"):
        total_lots = int(group["lots"].sum())
        total_cost = float(group["total_cost"].sum())
        total_lembar = total_lots * 100
        avg_price = total_cost / total_lembar if total_lembar > 0 else 0
        result[ticker] = {
            "lots": total_lots,
            "total_cost": total_cost,
            "avg_price": round(avg_price, 0),
        }
    return result


def compute_unrealized_pl(
    cost_basis: dict[str, dict],
    live_prices: dict[str, float | None],
) -> dict[str, dict]:
    """Hitung unrealized P/L berdasarkan harga live vs cost basis."""
    result = {}
    for ticker, basis in cost_basis.items():
        price = live_prices.get(ticker)
        if price is None:
            result[ticker] = {
                "market_value": None,
                "unrealized_rp": None,
                "unrealized_pct": None,
            }
            continue
        market_value = basis["lots"] * 100 * price
        unrealized_rp = market_value - basis["total_cost"]
        unrealized_pct = (unrealized_rp / basis["total_cost"] * 100) if basis["total_cost"] > 0 else 0
        result[ticker] = {
            "market_value": round(market_value, 0),
            "unrealized_rp": round(unrealized_rp, 0),
            "unrealized_pct": round(unrealized_pct, 2),
        }
    return result


def compute_portfolio_trajectory(
    history: pd.DataFrame,
    live_prices: dict[str, float | None],
) -> pd.DataFrame:
    """
    Rekonstruksi nilai portfolio aktual per bulan dari riwayat transaksi.

    Untuk setiap bulan dari transaksi pertama hingga hari ini:
      - Hitung lot kumulatif per ticker yang sudah dimiliki sampai bulan itu
      - Estimasi nilai pasar menggunakan harga rata-rata beli sebagai proxy
        (karena harga historis per tanggal tidak disimpan)
      - Di bulan terakhir (hari ini), gunakan harga live

    Returns DataFrame: date, total_invested, estimated_market_value
    """
    if history.empty:
        return pd.DataFrame(columns=["date", "total_invested", "estimated_market_value"])

    # Buat range bulanan dari transaksi pertama hingga hari ini
    start = history["date"].min().to_period("M")
    end = pd.Timestamp(date.today()).to_period("M")
    months = pd.period_range(start=start, end=end, freq="M")

    rows = []
    for period in months:
        period_end = period.to_timestamp(how="end")
        # Semua transaksi sampai akhir bulan ini
        mask = history["date"] <= period_end
        subset = history[mask]

        if subset.empty:
            continue

        total_invested = float(subset["total_cost"].sum())

        # Estimasi nilai pasar: untuk bulan terakhir pakai harga live, sisanya pakai avg buy price
        is_current_month = (period == end)
        estimated_value = 0.0
        for ticker, group in subset.groupby("ticker"):
            lots = int(group["lots"].sum())
            if is_current_month and live_prices.get(ticker):
                price = live_prices[ticker]
            else:
                # Harga rata-rata beli sebagai proxy nilai pasar historis
                total_cost = float(group["total_cost"].sum())
                total_lembar = lots * 100
                price = total_cost / total_lembar if total_lembar > 0 else 0
            estimated_value += lots * 100 * price

        rows.append({
            "date": period.to_timestamp(),
            "total_invested": total_invested,
            "estimated_market_value": estimated_value,
        })

    return pd.DataFrame(rows)
