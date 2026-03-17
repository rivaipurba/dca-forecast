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
