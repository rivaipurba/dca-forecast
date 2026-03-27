import yfinance as yf
import numpy as np
import pandas as pd
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
        stock = yf.Ticker(ticker, session=_make_session())
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
            one_year_ago = dividends.index[-1] - pd.DateOffset(years=1)
            recent_divs = dividends[dividends.index >= one_year_ago]
            annual_div = recent_divs.sum() if not recent_divs.empty else dividends.sum()
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
            hist = yf.Ticker(ticker, session=_make_session()).history(period="2d")
            prices[ticker] = round(hist["Close"].iloc[-1], 0) if not hist.empty else None
        except Exception:
            prices[ticker] = None
    return prices


@st.cache_data(ttl=3600)
def get_foreign_stock_metrics(
    ticker: str,
    fallback_cagr: float,
    fallback_div_yield: float,
    fallback_volatility: float,
    override_cagr: float | None = None,
    override_div_yield: float | None = None,
) -> dict:
    """
    Ambil metrik untuk ETF asing (USD-denominated).
    CAGR di-cap 20% (lebih tinggi dari IDX karena Nasdaq bisa lebih tinggi).
    Harga dikembalikan dalam USD.
    """
    try:
        stock = yf.Ticker(ticker, session=_make_session())
        hist = stock.history(period="10y")

        if len(hist) < 252:
            raise ValueError("Data historis kurang dari 1 tahun")

        years_data = len(hist) / 252
        cagr = (hist["Close"].iloc[-1] / hist["Close"].iloc[0]) ** (1 / years_data) - 1
        cagr = min(cagr, 0.20)  # cap 20% untuk ETF asing

        daily_returns = hist["Close"].pct_change().dropna()
        volatility = daily_returns.std() * np.sqrt(252)

        dividends = stock.dividends
        current_price = hist["Close"].iloc[-1]
        if len(dividends) > 0:
            one_year_ago = dividends.index[-1] - pd.DateOffset(years=1)
            recent_divs = dividends[dividends.index >= one_year_ago]
            annual_div = recent_divs.sum() if not recent_divs.empty else dividends.sum()
            div_yield = annual_div / current_price
            div_yield = min(div_yield, 0.05)
        else:
            div_yield = fallback_div_yield

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
            "current_price_usd": round(float(current_price), 2),
            "source": source,
            "currency": "USD",
        }

    except Exception:
        cagr = override_cagr if override_cagr is not None else fallback_cagr
        div_yield = override_div_yield if override_div_yield is not None else fallback_div_yield
        return {
            "cagr": cagr,
            "volatility": fallback_volatility,
            "div_yield": div_yield,
            "current_price_usd": None,
            "source": "fallback" if override_cagr is None else "override",
            "currency": "USD",
        }


@st.cache_data(ttl=300)
def get_usd_idr_rate() -> float:
    """
    Ambil kurs USD/IDR terkini.
    Sumber 1: Yahoo Finance (USDIDR=X)
    Sumber 2: Frankfurter API (gratis, tanpa API key)
    Fallback: USD_IDR_BASE dari config
    """
    import urllib.request
    import json
    from config import USD_IDR_BASE

    # Sumber 1: Yahoo Finance
    try:
        ticker = yf.Ticker("USDIDR=X", session=_make_session())
        hist = ticker.history(period="2d")
        if not hist.empty:
            rate = hist["Close"].iloc[-1]
            if 10_000 <= rate <= 25_000:
                return round(float(rate), 0)
    except Exception:
        pass

    # Sumber 2: Frankfurter API (ECB rates)
    try:
        url = "https://api.frankfurter.app/latest?from=USD&to=IDR"
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
            rate = data["rates"]["IDR"]
            if 10_000 <= rate <= 25_000:
                return round(float(rate), 0)
    except Exception:
        pass

    return USD_IDR_BASE
