import yfinance as yf
import numpy as np
import streamlit as st


@st.cache_data(ttl=3600)  # cache 1 jam, hindari hit API terus menerus
def get_stock_metrics(
    ticker: str,
    fallback_cagr: float,
    fallback_div_yield: float,
    fallback_volatility: float,
    override_cagr: float | None = None,
    override_div_yield: float | None = None,
) -> dict:
    """
    Ambil data historis dari yfinance dan hitung metrik utama.
    Fallback ke nilai default jika API gagal.
    """
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="10y")  # 10 tahun untuk kurangi bias event jangka pendek

        if len(hist) < 252:
            raise ValueError("Data historis kurang dari 1 tahun")

        # CAGR dari harga close — cap 15% agar tidak bias dari event exceptional (coal boom, dll)
        years = len(hist) / 252
        cagr = (hist["Close"].iloc[-1] / hist["Close"].iloc[0]) ** (1 / years) - 1
        cagr = min(cagr, 0.15)  # cap 15%/tahun untuk proyeksi jangka panjang

        # Volatilitas historis (annualized)
        daily_returns = hist["Close"].pct_change().dropna()
        volatility = daily_returns.std() * np.sqrt(252)

        # Dividend yield (dari 1 tahun terakhir)
        dividends = stock.dividends
        current_price = hist["Close"].iloc[-1]
        if len(dividends) > 0:
            annual_div = dividends.iloc[-4:].sum() if len(dividends) >= 4 else dividends.sum()
            div_yield = annual_div / current_price
            # Batasi yield yang tidak realistis (misal ADRO saat coal boom)
            div_yield = min(div_yield, 0.08)  # cap 8% untuk proyeksi jangka panjang
        else:
            div_yield = fallback_div_yield

        # Terapkan override dari user jika ada
        source = "live"
        if override_cagr is not None:
            cagr = override_cagr
            source = "live+override"
        if override_div_yield is not None:
            div_yield = override_div_yield
            source = "live+override"

        return {
            "cagr": round(cagr, 4),
            "volatility": round(volatility, 4),
            "div_yield": round(div_yield, 4),
            "current_price": round(current_price, 0),
            "source": source,
        }

    except Exception:
        cagr = override_cagr if override_cagr is not None else fallback_cagr
        div_yield = override_div_yield if override_div_yield is not None else fallback_div_yield
        return {
            "cagr": cagr,
            "volatility": fallback_volatility,
            "div_yield": div_yield,
            "current_price": None,
            "source": "fallback" if override_cagr is None else "override",
        }


@st.cache_data(ttl=300)  # cache 5 menit untuk harga live
def get_current_prices(tickers: list[str]) -> dict[str, float | None]:
    """Ambil harga terkini untuk list ticker."""
    prices = {}
    for ticker in tickers:
        try:
            hist = yf.Ticker(ticker).history(period="2d")
            prices[ticker] = round(hist["Close"].iloc[-1], 0) if not hist.empty else None
        except Exception:
            prices[ticker] = None
    return prices
