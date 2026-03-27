import numpy as np
import pandas as pd
from datetime import date
from dateutil.relativedelta import relativedelta


def simulate_dca(
    initial_value: float,
    monthly_dca: float,
    years: int,
    annual_return: float,
    annual_volatility: float,
    annual_div_yield: float,
    reinvest_div: bool = True,
    n_simulations: int = 500,
    seed: int = 42,
) -> dict:
    """
    Monte Carlo simulation untuk DCA portfolio.

    Setiap bulan:
      1. Portfolio tumbuh sesuai return acak (normal distribution)
      2. Dividen diterima dan di-reinvest (jika aktif)
      3. Tambahkan kontribusi DCA bulanan

    Returns dict berisi matrix simulasi dan percentile bands.
    """
    np.random.seed(seed)
    months = years * 12

    # Konversi parameter tahunan ke bulanan
    monthly_return = (1 + annual_return) ** (1 / 12) - 1
    monthly_vol = annual_volatility / np.sqrt(12)
    monthly_div = annual_div_yield / 12

    # Matrix simulasi: baris = simulasi, kolom = bulan
    portfolio = np.zeros((n_simulations, months + 1))
    portfolio[:, 0] = initial_value

    # Track modal yang diinvestasikan (deterministik)
    total_invested = np.zeros(months + 1)
    total_invested[0] = initial_value

    for m in range(1, months + 1):
        # Return acak bulan ini untuk semua simulasi
        r = np.random.normal(monthly_return, monthly_vol, n_simulations)

        # Pertumbuhan harga
        after_growth = portfolio[:, m - 1] * (1 + r)

        # Reinvest dividen
        if reinvest_div:
            after_growth = after_growth * (1 + monthly_div)

        # Tambah kontribusi DCA
        portfolio[:, m] = after_growth + monthly_dca

        # Total modal (deterministik)
        total_invested[m] = total_invested[m - 1] + monthly_dca

    # Label waktu (bulan ke bulan)
    today = date.today()
    time_labels = [today + relativedelta(months=m) for m in range(months + 1)]
    years_labels = [m / 12 for m in range(months + 1)]

    return {
        "simulations": portfolio,
        "total_invested": total_invested,
        "time_labels": time_labels,
        "years_labels": years_labels,
        "p10": np.percentile(portfolio, 10, axis=0),
        "p50": np.percentile(portfolio, 50, axis=0),
        "p90": np.percentile(portfolio, 90, axis=0),
    }


def calculate_blended_metrics(
    stock_metrics: dict,
    allocations: dict[str, float],
) -> dict:
    """
    Hitung metrik portfolio gabungan berdasarkan alokasi target.
    Volatilitas menggunakan weighted average (konservatif, tanpa korelasi).
    """
    blended_cagr = 0.0
    blended_vol = 0.0
    blended_div = 0.0

    for code, alloc in allocations.items():
        m = stock_metrics[code]
        blended_cagr += alloc * m["cagr"]
        blended_vol += alloc * m["volatility"]
        blended_div += alloc * m["div_yield"]

    return {
        "cagr": round(blended_cagr, 4),
        "volatility": round(blended_vol, 4),
        "div_yield": round(blended_div, 4),
    }


def project_dividend_income(portfolio_values: np.ndarray, div_yield: float) -> dict:
    """
    Hitung passive income dari dividen di tahun pensiun.
    """
    return {
        "annual_p10": int(np.percentile(portfolio_values, 10) * div_yield),
        "annual_p50": int(np.percentile(portfolio_values, 50) * div_yield),
        "annual_p90": int(np.percentile(portfolio_values, 90) * div_yield),
        "monthly_p10": int(np.percentile(portfolio_values, 10) * div_yield / 12),
        "monthly_p50": int(np.percentile(portfolio_values, 50) * div_yield / 12),
        "monthly_p90": int(np.percentile(portfolio_values, 90) * div_yield / 12),
    }


def apply_inflation(
    values: np.ndarray,
    years_axis: list[float],
    inflation_rate: float,
) -> np.ndarray:
    """
    Konversi nilai nominal ke nilai riil (inflation-adjusted).
    real_value[t] = nominal_value[t] / (1 + inflation)^t
    """
    deflators = np.array([(1 + inflation_rate) ** y for y in years_axis])
    return values / deflators


def calculate_required_dca(
    target_monthly_income: float,
    div_yield: float,
    annual_return: float,
    years: int,
    initial_value: float = 0,
) -> float:
    """
    Hitung DCA bulanan yang dibutuhkan untuk mencapai target passive income.

    Rumus FV anuitas:
      FV = PV*(1+r)^n + PMT*[(1+r)^n - 1] / r
    Solve for PMT:
      PMT = (FV - PV*(1+r)^n) * r / [(1+r)^n - 1]
    """
    target_portfolio = target_monthly_income * 12 / div_yield if div_yield > 0 else 0
    n = years * 12
    r = (1 + annual_return) ** (1 / 12) - 1

    growth_factor = (1 + r) ** n
    pv_grown = initial_value * growth_factor
    annuity_factor = (growth_factor - 1) / r if r > 0 else n

    required_dca = (target_portfolio - pv_grown) / annuity_factor
    return max(required_dca, 0)


def simulate_foreign_dca(
    initial_value_usd: float,
    monthly_dca_idr: float,
    years: int,
    annual_return: float,
    annual_volatility: float,
    annual_div_yield: float,
    usd_idr_rate: float,
    idr_depreciation: float = 0.035,
    reinvest_div: bool = True,
    n_simulations: int = 500,
    seed: int = 43,
) -> dict:
    """
    Simulasi DCA untuk portofolio ETF asing (GoTrade) dalam USD,
    lalu dikonversi ke IDR dengan mempertimbangkan depresiasi rupiah.

    - monthly_dca_idr: kontribusi bulanan dalam IDR, dikonversi ke USD tiap bulan
      menggunakan kurs proyeksi bulan tersebut
    - usd_idr_rate: kurs awal (Rp per 1 USD)
    - idr_depreciation: laju depresiasi IDR per tahun (default 3.5%)

    Hasilnya dikembalikan dalam IDR.
    """
    np.random.seed(seed)
    months = years * 12

    monthly_return = (1 + annual_return) ** (1 / 12) - 1
    monthly_vol = annual_volatility / np.sqrt(12)
    monthly_div = annual_div_yield / 12
    monthly_depreciation = (1 + idr_depreciation) ** (1 / 12) - 1

    # Simulasi dalam USD
    portfolio_usd = np.zeros((n_simulations, months + 1))
    portfolio_usd[:, 0] = initial_value_usd

    total_invested_idr = np.zeros(months + 1)
    total_invested_idr[0] = initial_value_usd * usd_idr_rate

    for m in range(1, months + 1):
        rate_at_month = usd_idr_rate * ((1 + monthly_depreciation) ** m)
        monthly_dca_usd = monthly_dca_idr / rate_at_month

        r = np.random.normal(monthly_return, monthly_vol, n_simulations)
        after_growth = portfolio_usd[:, m - 1] * (1 + r)
        if reinvest_div:
            after_growth = after_growth * (1 + monthly_div)
        portfolio_usd[:, m] = after_growth + monthly_dca_usd

        total_invested_idr[m] = total_invested_idr[m - 1] + monthly_dca_idr

    # Konversi portofolio USD ke IDR menggunakan kurs proyeksi tiap bulan
    portfolio_idr = np.zeros_like(portfolio_usd)
    for m in range(months + 1):
        rate_at_month = usd_idr_rate * ((1 + monthly_depreciation) ** m)
        portfolio_idr[:, m] = portfolio_usd[:, m] * rate_at_month

    today = date.today()
    time_labels = [today + relativedelta(months=m) for m in range(months + 1)]
    years_labels = [m / 12 for m in range(months + 1)]

    return {
        "simulations": portfolio_idr,
        "simulations_usd": portfolio_usd,
        "total_invested": total_invested_idr,
        "time_labels": time_labels,
        "years_labels": years_labels,
        "p10": np.percentile(portfolio_idr, 10, axis=0),
        "p50": np.percentile(portfolio_idr, 50, axis=0),
        "p90": np.percentile(portfolio_idr, 90, axis=0),
        "p10_usd": np.percentile(portfolio_usd, 10, axis=0),
        "p50_usd": np.percentile(portfolio_usd, 50, axis=0),
        "p90_usd": np.percentile(portfolio_usd, 90, axis=0),
    }


def simulate_combined_portfolio(
    idx_result: dict,
    foreign_result: dict,
) -> dict:
    """
    Gabungkan hasil simulasi IDX (IDR) dan Foreign/GoTrade (USD->IDR).
    Kedua result harus memiliki jumlah bulan yang sama.
    Returns dict dengan combined p10/p50/p90 dan total_invested.
    """
    combined_sims = idx_result["simulations"] + foreign_result["simulations"]
    combined_invested = idx_result["total_invested"] + foreign_result["total_invested"]

    return {
        "simulations": combined_sims,
        "total_invested": combined_invested,
        "time_labels": idx_result["time_labels"],
        "years_labels": idx_result["years_labels"],
        "p10": np.percentile(combined_sims, 10, axis=0),
        "p50": np.percentile(combined_sims, 50, axis=0),
        "p90": np.percentile(combined_sims, 90, axis=0),
    }


def project_future_usd_idr(
    base_rate: float,
    idr_depreciation: float,
    years: int,
) -> np.ndarray:
    """
    Proyeksi kurs USD/IDR ke depan.
    Mengembalikan array kurs untuk setiap tahun dari 0 sampai years.
    """
    return np.array([base_rate * ((1 + idr_depreciation) ** y) for y in range(years + 1)])
