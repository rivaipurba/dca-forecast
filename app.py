import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np
from datetime import date

from config import STOCKS, DCA_MONTHLY, INVESTMENT_YEARS, LOT_SIZE, N_SIMULATIONS, HISTORY_FILE
from engine.data_fetcher import get_stock_metrics, get_current_prices
from engine.projection import (
    simulate_dca, calculate_blended_metrics, project_dividend_income,
    apply_inflation, calculate_required_dca,
)
from engine.dca_helper import get_dca_recommendation, format_rupiah
from engine.fundamental import fetch_fundamentals, VALUATION_RANGES, SIGNAL_EMOJI, format_market_cap
from engine.history_manager import (
    load_history, save_transaction, save_history,
    compute_holdings, compute_cost_basis,
    compute_unrealized_pl, compute_portfolio_trajectory,
)

# ─── Page Config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="DCA Forecast — Perjalanan Pensiun",
    page_icon="📈",
    layout="wide",
)

st.markdown("""
<style>
    .metric-card {
        background: #1e1e2e;
        border-radius: 12px;
        padding: 20px;
        border-left: 4px solid;
        margin-bottom: 8px;
    }
    .retirement-banner {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border-radius: 16px;
        padding: 30px;
        border: 1px solid #0f3460;
        text-align: center;
        margin: 20px 0;
    }
    .stMetric label { font-size: 0.85rem !important; }
</style>
""", unsafe_allow_html=True)

# ─── Load History (sebelum sidebar, untuk derive lots) ───────────────────────
history = load_history(HISTORY_FILE)
history_lots = compute_holdings(history)

# ─── Sidebar — Konfigurasi ────────────────────────────────────────────────────
with st.sidebar:
    st.title("⚙️ Konfigurasi")
    st.divider()

    # ── Holding Saat Ini ───────────────────────────────────────────────────
    st.subheader("💼 Holding Saat Ini")
    current_lots = {}
    if history_lots:
        st.info("Lot dihitung dari Riwayat DCA", icon="📒")
        for code, cfg in STOCKS.items():
            lots = history_lots.get(code, 0)
            st.metric(f"{code}", f"{lots} lot", label_visibility="visible")
            current_lots[code] = lots
    else:
        st.caption("Belum ada riwayat — input manual")
        for code, cfg in STOCKS.items():
            current_lots[code] = st.number_input(
                f"{code} ({cfg['name']}) — lot",
                min_value=0,
                value=cfg["initial_lots"],
                step=1,
                key=f"lots_{code}",
            )

    st.divider()

    # ── Parameter DCA ──────────────────────────────────────────────────────
    st.subheader("💰 Parameter DCA")
    monthly_dca = st.number_input(
        "DCA per bulan (Rp)",
        min_value=100_000,
        max_value=10_000_000,
        value=DCA_MONTHLY,
        step=100_000,
        format="%d",
    )
    accumulated_cash = st.number_input(
        "Kas terakumulasi (Rp)",
        min_value=0,
        value=0,
        step=50_000,
        format="%d",
        help="Sisa uang dari bulan sebelumnya yang belum dibelikan saham",
    )
    years = st.slider("Horizon investasi (tahun)", 5, 35, INVESTMENT_YEARS)
    reinvest_div = st.toggle("Reinvest dividen", value=True)

    st.divider()

    # ── Target Alokasi ─────────────────────────────────────────────────────
    st.subheader("🎯 Target Alokasi")
    alloc_bbri = st.slider("BBRI %", 0, 100, 50)
    alloc_adro = st.slider("ADRO %", 0, 100 - alloc_bbri, 30)
    alloc_tlkm = 100 - alloc_bbri - alloc_adro
    st.caption(f"TLKM otomatis: {alloc_tlkm}%")

    target_alloc = {
        "BBRI": alloc_bbri / 100,
        "ADRO": alloc_adro / 100,
        "TLKM": alloc_tlkm / 100,
    }

    st.divider()

    # ── Override Asumsi Return ─────────────────────────────────────────────
    with st.expander("🔧 Override Asumsi Return"):
        st.caption(
            "Data live Yahoo Finance mungkin tidak akurat untuk proyeksi "
            "jangka panjang. Override di sini jika perlu."
        )
        overrides = {}
        for code, cfg in STOCKS.items():
            st.markdown(f"**{code}**")
            col_a, col_b = st.columns(2)
            use_cagr = col_a.toggle(f"CAGR", key=f"use_cagr_{code}", value=False)
            use_div = col_b.toggle(f"Div Yield", key=f"use_div_{code}", value=False)
            cagr_val = None
            div_val = None
            if use_cagr:
                cagr_val = st.slider(
                    f"CAGR {code} (%/tahun)", 0.0, 25.0,
                    value=float(cfg["default_cagr"] * 100),
                    step=0.5, key=f"cagr_{code}",
                ) / 100
            if use_div:
                div_val = st.slider(
                    f"Div Yield {code} (%/tahun)", 0.0, 15.0,
                    value=float(cfg["default_div_yield"] * 100),
                    step=0.5, key=f"div_{code}",
                ) / 100
            overrides[code] = {"cagr": cagr_val, "div_yield": div_val}

    st.divider()

    # ── Inflasi ────────────────────────────────────────────────────────────
    st.subheader("📉 Asumsi Inflasi")
    inflation_rate = st.slider(
        "Inflasi tahunan (%)", 0.0, 10.0, 4.5, step=0.5,
        help="Indonesia historis ~4-5%/tahun. Dipakai untuk menghitung nilai riil.",
    ) / 100
    show_real = st.toggle("Tampilkan nilai riil (after inflation)", value=False)

    st.divider()
    st.caption("Data live dari Yahoo Finance. Cache 1 jam.")

# ─── Load Data ────────────────────────────────────────────────────────────────
with st.spinner("Mengambil data saham dari Yahoo Finance..."):
    stock_metrics = {}
    for code, cfg in STOCKS.items():
        ov = overrides.get(code, {})
        stock_metrics[code] = get_stock_metrics(
            cfg["ticker"],
            cfg["default_cagr"],
            cfg["default_div_yield"],
            cfg["default_volatility"],
            override_cagr=ov.get("cagr"),
            override_div_yield=ov.get("div_yield"),
        )

    tickers = [cfg["ticker"] for cfg in STOCKS.values()]
    ticker_to_code = {cfg["ticker"]: code for code, cfg in STOCKS.items()}
    live_prices_raw = get_current_prices(tickers)
    live_prices = {ticker_to_code[t]: p for t, p in live_prices_raw.items()}

# Blended portfolio metrics berdasarkan target alokasi
blended = calculate_blended_metrics(stock_metrics, target_alloc)

# Hitung nilai portfolio awal dari holding saat ini
initial_portfolio_value = 0
for code, lots in current_lots.items():
    price = live_prices.get(code) or (lots * 4000)  # fallback estimasi
    initial_portfolio_value += lots * LOT_SIZE * price

# Jalankan simulasi Monte Carlo
result = simulate_dca(
    initial_value=initial_portfolio_value,
    monthly_dca=monthly_dca,
    years=years,
    annual_return=blended["cagr"],
    annual_volatility=blended["volatility"],
    annual_div_yield=blended["div_yield"],
    reinvest_div=reinvest_div,
    n_simulations=N_SIMULATIONS,
)

# Proyeksi dividen di tahun pensiun (nilai akhir simulasi)
final_values = result["simulations"][:, -1]
div_income = project_dividend_income(final_values, blended["div_yield"])

# DCA recommendation bulan ini
dca_rec = get_dca_recommendation(
    current_prices=live_prices,
    current_lots=current_lots,
    target_alloc=target_alloc,
    monthly_budget=monthly_dca,
    accumulated_cash=accumulated_cash,
)

# ─── Header ──────────────────────────────────────────────────────────────────
st.title("📈 DCA Forecast — Perjalanan Pensiun")
retirement_year = date.today().year + years
st.caption(f"Simulasi DCA {format_rupiah(monthly_dca)}/bulan selama {years} tahun — Target pensiun: **{retirement_year}**")

# ─── Tab Layout ──────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📊 Proyeksi Portfolio",
    "💰 Dashboard Pensiun",
    "📅 DCA Bulan Ini",
    "📒 Riwayat DCA",
    "🔮 What-If",
    "🔍 Fundamental",
])

# ════════════════════════════════════════════════════════════════════════════
# TAB 1: PROYEKSI PORTFOLIO
# ════════════════════════════════════════════════════════════════════════════
with tab1:
    total_invested = result["total_invested"][-1]
    proj_base = result["p50"][-1]
    proj_best = result["p90"][-1]
    multiplier = proj_base / total_invested if total_invested > 0 else 0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric(
        "Total Modal Diinvestasikan",
        format_rupiah(total_invested),
        help=f"Rp {monthly_dca:,.0f} × {years * 12} bulan + modal awal",
    )
    col2.metric(
        "Proyeksi Nilai (Median)",
        format_rupiah(proj_base),
        f"+{((proj_base / total_invested) - 1) * 100:.0f}% dari modal",
    )
    col3.metric(
        "Proyeksi Nilai (Optimis)",
        format_rupiah(proj_best),
        f"+{((proj_best / total_invested) - 1) * 100:.0f}% dari modal",
    )
    col4.metric(
        "Faktor Pengganda (Median)",
        f"{multiplier:.1f}x",
        help="Proyeksi dibagi total modal yang diinvestasikan",
    )

    st.divider()

    # ── Monte Carlo Chart ─────────────────────────────────────────────────
    years_axis = result["years_labels"]
    invested_line = result["total_invested"]

    fig = go.Figure()

    # Area optimis-pesimis
    fig.add_trace(go.Scatter(
        x=years_axis, y=result["p90"],
        fill=None, mode="lines",
        line=dict(color="rgba(99,202,109,0.3)", width=0),
        showlegend=False, name="Optimis (P90)",
    ))
    fig.add_trace(go.Scatter(
        x=years_axis, y=result["p10"],
        fill="tonexty", mode="lines",
        fillcolor="rgba(99,202,109,0.12)",
        line=dict(color="rgba(99,202,109,0.3)", width=0),
        name="Rentang P10–P90",
    ))

    # Garis P50 (median)
    fig.add_trace(go.Scatter(
        x=years_axis, y=result["p50"],
        mode="lines", name="Proyeksi Median (P50)",
        line=dict(color="#63ca6d", width=2.5),
    ))

    # Garis P90
    fig.add_trace(go.Scatter(
        x=years_axis, y=result["p90"],
        mode="lines", name="Skenario Optimis (P90)",
        line=dict(color="#63ca6d", width=1.5, dash="dot"),
    ))

    # Garis P10
    fig.add_trace(go.Scatter(
        x=years_axis, y=result["p10"],
        mode="lines", name="Skenario Pesimis (P10)",
        line=dict(color="#e07b54", width=1.5, dash="dot"),
    ))

    # Garis modal yang diinvestasikan
    fig.add_trace(go.Scatter(
        x=years_axis, y=invested_line,
        mode="lines", name="Total Modal Diinvestasikan",
        line=dict(color="#a0a0b0", width=1.5, dash="dash"),
    ))

    real_note = ""
    if show_real:
        real_note = f" — Nilai Riil (inflasi {inflation_rate*100:.1f}%/tahun)"
        p50_plot  = apply_inflation(result["p50"],  years_axis, inflation_rate)
        p10_plot  = apply_inflation(result["p10"],  years_axis, inflation_rate)
        p90_plot  = apply_inflation(result["p90"],  years_axis, inflation_rate)
        # Update traces yang sudah ada
        fig.data[0].y = p90_plot
        fig.data[1].y = p10_plot
        fig.data[2].y = p50_plot
        fig.data[3].y = p90_plot
        fig.data[4].y = p10_plot

    fig.update_layout(
        title=f"Proyeksi Pertumbuhan Portfolio (Monte Carlo){real_note}",
        xaxis_title="Tahun ke-",
        yaxis_title="Nilai Portfolio (Rp)",
        yaxis_tickformat=",",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=420,
        template="plotly_dark",
    )

    # Custom y-axis labels (dalam juta/miliar)
    fig.update_yaxes(tickprefix="Rp ", tickformat=".2s")
    st.plotly_chart(fig, use_container_width=True)

    # ── Asumsi Return Per Saham ───────────────────────────────────────────
    st.subheader("📋 Asumsi Return Per Saham")
    rows = []
    for code, cfg in STOCKS.items():
        m = stock_metrics[code]
        rows.append({
            "Saham": f"{code} — {cfg['name']}",
            "Harga Live": f"Rp {live_prices.get(code):,.0f}" if live_prices.get(code) else "N/A",
            "CAGR Historis": f"{m['cagr'] * 100:.1f}%",
            "Div Yield": f"{m['div_yield'] * 100:.1f}%",
            "Volatilitas": f"{m['volatility'] * 100:.1f}%",
            "Total Return Est.": f"{(m['cagr'] + m['div_yield']) * 100:.1f}%",
            "Sumber Data": "Live ✅" if m["source"] == "live" else "Default ⚠️",
            "Target Alokasi": f"{target_alloc[code] * 100:.0f}%",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.caption(
        f"Blended portfolio: CAGR **{blended['cagr']*100:.1f}%** | "
        f"Div Yield **{blended['div_yield']*100:.1f}%** | "
        f"Volatilitas **{blended['volatility']*100:.1f}%** | "
        f"Total Return Est. **{(blended['cagr'] + blended['div_yield'])*100:.1f}%**"
    )

# ════════════════════════════════════════════════════════════════════════════
# TAB 2: DASHBOARD PENSIUN
# ════════════════════════════════════════════════════════════════════════════
with tab2:
    st.subheader(f"🎯 Proyeksi di Tahun Pensiun ({retirement_year})")

    # Hitung nilai riil jika toggle aktif
    inflation_factor = (1 + inflation_rate) ** years
    def to_real(v): return v / inflation_factor

    label_nominal = "nominal"
    label_riil    = f"≈ {format_rupiah(to_real(div_income['monthly_p50']))} nilai uang hari ini" if show_real else ""

    # Banner utama
    st.markdown(f"""
    <div class="retirement-banner">
        <h2 style="color:#63ca6d; margin:0">💰 Passive Income dari Dividen</h2>
        <p style="color:#a0a0b0; margin:8px 0 4px">Estimasi pendapatan pasif bulanan saat pensiun — nilai {label_nominal}</p>
        {'<p style="color:#f0a500; font-size:0.85rem; margin:0 0 16px">⚠️ Inflasi ' + f"{inflation_rate*100:.1f}%" + '/tahun → daya beli riil lebih rendah (lihat baris kedua)</p>' if show_real else '<p style="margin:0 0 16px"></p>'}
        <div style="display:flex; justify-content:center; gap:60px;">
            <div>
                <div style="color:#e07b54; font-size:0.85rem">Skenario Pesimis</div>
                <div style="color:#e07b54; font-size:2rem; font-weight:bold">{format_rupiah(div_income['monthly_p10'])}</div>
                {'<div style="color:#e07b54; font-size:0.8rem; opacity:0.7">≈ ' + format_rupiah(to_real(div_income['monthly_p10'])) + ' hari ini</div>' if show_real else ''}
            </div>
            <div>
                <div style="color:#63ca6d; font-size:0.85rem; font-weight:bold">Skenario Median</div>
                <div style="color:#63ca6d; font-size:2.8rem; font-weight:bold">{format_rupiah(div_income['monthly_p50'])}</div>
                {'<div style="color:#63ca6d; font-size:0.85rem; opacity:0.8">≈ ' + format_rupiah(to_real(div_income['monthly_p50'])) + ' hari ini</div>' if show_real else ''}
            </div>
            <div>
                <div style="color:#4fc3f7; font-size:0.85rem">Skenario Optimis</div>
                <div style="color:#4fc3f7; font-size:2rem; font-weight:bold">{format_rupiah(div_income['monthly_p90'])}</div>
                {'<div style="color:#4fc3f7; font-size:0.8rem; opacity:0.7">≈ ' + format_rupiah(to_real(div_income['monthly_p90'])) + ' hari ini</div>' if show_real else ''}
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # KPI nilai portfolio di tahun pensiun
    col1, col2, col3 = st.columns(3)
    col1.metric("Nilai Portfolio (Pesimis)", format_rupiah(np.percentile(final_values, 10)))
    col2.metric("Nilai Portfolio (Median)", format_rupiah(np.percentile(final_values, 50)))
    col3.metric("Nilai Portfolio (Optimis)", format_rupiah(np.percentile(final_values, 90)))

    st.divider()

    # ── Grafik Dividen Bulanan Sepanjang Waktu ─────────────────────────────
    riil_label = f" (Nilai Riil, inflasi {inflation_rate*100:.1f}%/tahun)" if show_real else " (Nilai Nominal)"
    st.subheader(f"📈 Proyeksi Dividen Bulanan Sepanjang Perjalanan{riil_label}")

    monthly_div_p50 = result["p50"] * blended["div_yield"] / 12
    monthly_div_p10 = result["p10"] * blended["div_yield"] / 12
    monthly_div_p90 = result["p90"] * blended["div_yield"] / 12
    if show_real:
        monthly_div_p50 = apply_inflation(monthly_div_p50, years_axis, inflation_rate)
        monthly_div_p10 = apply_inflation(monthly_div_p10, years_axis, inflation_rate)
        monthly_div_p90 = apply_inflation(monthly_div_p90, years_axis, inflation_rate)

    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(
        x=years_axis, y=monthly_div_p90,
        fill=None, mode="lines",
        line=dict(color="rgba(79,195,247,0.3)", width=0), showlegend=False,
    ))
    fig2.add_trace(go.Scatter(
        x=years_axis, y=monthly_div_p10,
        fill="tonexty", mode="lines",
        fillcolor="rgba(79,195,247,0.10)",
        line=dict(color="rgba(79,195,247,0.3)", width=0),
        name="Rentang P10–P90",
    ))
    fig2.add_trace(go.Scatter(
        x=years_axis, y=monthly_div_p50,
        mode="lines", name="Dividen Bulanan (Median)",
        line=dict(color="#4fc3f7", width=2.5),
    ))
    fig2.add_hrect(
        y0=3_000_000, y1=5_000_000,
        fillcolor="rgba(99,202,109,0.08)",
        annotation_text="Zona UMR Jakarta (~Rp 3–5 jt/bulan)",
        annotation_position="top right",
        line_width=0,
    )
    fig2.update_layout(
        xaxis_title="Tahun ke-",
        yaxis_title="Dividen Bulanan (Rp)",
        yaxis_tickprefix="Rp ",
        yaxis_tickformat=".2s",
        hovermode="x unified",
        height=380,
        template="plotly_dark",
    )
    st.plotly_chart(fig2, use_container_width=True)

    # ── Milestone Tracker ──────────────────────────────────────────────────
    st.subheader("🏁 Estimasi Milestone Portfolio")
    milestones = [100_000_000, 250_000_000, 500_000_000, 1_000_000_000]
    milestone_labels = ["Rp 100 jt", "Rp 250 jt", "Rp 500 jt", "Rp 1 Miliar"]

    cols = st.columns(len(milestones))
    p50_series = result["p50"]
    for i, (target_val, label) in enumerate(zip(milestones, milestone_labels)):
        months_reach = np.argmax(p50_series >= target_val)
        if months_reach == 0 and p50_series[0] < target_val:
            cols[i].metric(label, "Belum tercapai", "dalam 25 tahun")
        else:
            yr = months_reach / 12
            cols[i].metric(label, f"Tahun ke-{yr:.1f}", f"± {date.today().year + int(yr)}")


# ════════════════════════════════════════════════════════════════════════════
# TAB 3: DCA BULAN INI
# ════════════════════════════════════════════════════════════════════════════
with tab3:
    today_str = date.today().strftime("%B %Y")
    st.subheader(f"📅 Rekomendasi DCA — {today_str}")

    rec = dca_rec
    recommended = rec["recommended_stock"]
    rec_cfg = STOCKS[recommended]

    # Banner rekomendasi
    if rec["lots_to_buy"] > 0:
        st.success(
            f"**Beli {recommended} — {rec_cfg['name']}**  \n"
            f"Jumlah: **{rec['lots_to_buy']} lot** ({rec['lots_to_buy'] * LOT_SIZE:,} lembar)  \n"
            f"Harga: Rp {rec['price']:,.0f}/lembar  \n"
            f"Biaya: **{format_rupiah(rec['cost'])}**  \n"
            f"Sisa kas bulan ini: {format_rupiah(rec['remaining_cash'])}"
        )
    else:
        price = rec.get("price")
        if price:
            lot_price = price * LOT_SIZE
            st.warning(
                f"Budget Rp {monthly_dca:,.0f} belum cukup untuk 1 lot {recommended} "
                f"(harga 1 lot ≈ {format_rupiah(lot_price)}).  \n"
                f"Akumulasikan sisa kas ke bulan depan."
            )
        else:
            st.warning("Harga live tidak tersedia. Cek koneksi internet.")

    st.divider()

    # ── Alokasi Aktual vs Target ───────────────────────────────────────────
    st.subheader("📊 Alokasi Portfolio — Aktual vs Target")

    col_chart, col_table = st.columns([1.2, 1])

    with col_chart:
        alloc_df = pd.DataFrame({
            "Saham": list(rec["actual_alloc"].keys()),
            "Aktual (%)": [v * 100 for v in rec["actual_alloc"].values()],
            "Target (%)": [target_alloc[k] * 100 for k in rec["actual_alloc"]],
        })

        fig3 = go.Figure()
        fig3.add_trace(go.Bar(
            name="Aktual",
            x=alloc_df["Saham"],
            y=alloc_df["Aktual (%)"],
            marker_color=[STOCKS[c]["color"] for c in alloc_df["Saham"]],
            opacity=0.85,
        ))
        fig3.add_trace(go.Bar(
            name="Target",
            x=alloc_df["Saham"],
            y=alloc_df["Target (%)"],
            marker_color="rgba(255,255,255,0.2)",
            marker_line=dict(color="white", width=1.5),
        ))
        fig3.update_layout(
            barmode="overlay",
            yaxis_title="Alokasi (%)",
            yaxis_range=[0, 100],
            height=300,
            template="plotly_dark",
            legend=dict(orientation="h", y=1.1),
        )
        st.plotly_chart(fig3, use_container_width=True)

    with col_table:
        st.markdown("**Detail Holding Saat Ini**")
        rows = []
        for code in STOCKS:
            price = live_prices.get(code)
            lots = current_lots[code]
            value = rec["portfolio_values"].get(code, 0)
            gap = rec["alloc_gap"].get(code, 0)
            rows.append({
                "Saham": code,
                "Lot": lots,
                "Harga": f"Rp {price:,.0f}" if price else "N/A",
                "Nilai": format_rupiah(value),
                "Aktual": f"{rec['actual_alloc'].get(code, 0)*100:.1f}%",
                "Target": f"{target_alloc[code]*100:.0f}%",
                "Gap": f"{'▲' if gap > 0 else '▼'} {abs(gap)*100:.1f}%",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.caption(
        f"Total nilai portfolio saat ini: **{format_rupiah(rec['total_portfolio'])}** | "
        f"Budget tersedia: **{format_rupiah(rec['available_budget'])}**"
    )

# ════════════════════════════════════════════════════════════════════════════
# TAB 4: RIWAYAT DCA
# ════════════════════════════════════════════════════════════════════════════
with tab4:
    st.subheader("📒 Riwayat Transaksi DCA")

    # ── Form Input Transaksi Baru ──────────────────────────────────────────
    with st.form("add_transaction", clear_on_submit=True):
        st.markdown("**➕ Catat Transaksi DCA**")
        col_a, col_b, col_c = st.columns(3)
        tx_date  = col_a.date_input("Tanggal", value=date.today())
        tx_stock = col_b.selectbox("Saham", list(STOCKS.keys()))
        tx_lots  = col_c.number_input("Jumlah Lot", min_value=1, value=1, step=1)
        col_d, col_e = st.columns([1, 2])
        tx_price = col_d.number_input("Harga per lembar (Rp)", min_value=1, value=4000, step=10)
        tx_notes = col_e.text_input("Catatan (opsional)", placeholder="misal: DCA Maret 2026")
        submitted = st.form_submit_button("💾 Simpan Transaksi", use_container_width=True)

        if submitted:
            save_transaction(HISTORY_FILE, tx_date, tx_stock, tx_lots, tx_price, tx_notes)
            total = tx_lots * LOT_SIZE * tx_price
            st.success(
                f"Tersimpan: {tx_stock} {tx_lots} lot @ Rp {tx_price:,} "
                f"= **{format_rupiah(total)}**"
            )
            st.rerun()

    st.divider()

    if history.empty:
        st.info(
            "Belum ada transaksi tercatat. Mulai catat DCA pertamamu di atas!",
            icon="👆",
        )
    else:
        # ── Cost Basis & Unrealized P/L ────────────────────────────────────
        st.subheader("💼 Ringkasan Holding & Unrealized P/L")
        cost_basis = compute_cost_basis(history)
        unrealized = compute_unrealized_pl(cost_basis, live_prices)

        pl_rows = []
        for code in STOCKS:
            if code not in cost_basis:
                continue
            basis = cost_basis[code]
            pl = unrealized.get(code, {})
            unreal_rp = pl.get("unrealized_rp")
            unreal_pct = pl.get("unrealized_pct")
            market_val = pl.get("market_value")
            pl_rows.append({
                "Saham": code,
                "Lot": basis["lots"],
                "Avg Beli (Rp/lembar)": int(basis["avg_price"]),
                "Harga Live": int(live_prices[code]) if live_prices.get(code) else None,
                "Total Modal": int(basis["total_cost"]),
                "Nilai Pasar": int(market_val) if market_val else None,
                "Unrealized P/L (Rp)": int(unreal_rp) if unreal_rp is not None else None,
                "Unrealized P/L (%)": unreal_pct,
            })

        pl_df = pd.DataFrame(pl_rows)
        st.dataframe(
            pl_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Total Modal": st.column_config.NumberColumn(format="Rp %d"),
                "Nilai Pasar": st.column_config.NumberColumn(format="Rp %d"),
                "Avg Beli (Rp/lembar)": st.column_config.NumberColumn(format="Rp %d"),
                "Harga Live": st.column_config.NumberColumn(format="Rp %d"),
                "Unrealized P/L (Rp)": st.column_config.NumberColumn(format="Rp %d"),
                "Unrealized P/L (%)": st.column_config.NumberColumn(format="%.2f%%"),
            },
        )

        # Total summary
        total_modal_all = sum(b["total_cost"] for b in cost_basis.values())
        total_pasar_all = sum(
            v["market_value"] for v in unrealized.values()
            if v.get("market_value") is not None
        )
        total_pl = total_pasar_all - total_modal_all
        total_pl_pct = (total_pl / total_modal_all * 100) if total_modal_all > 0 else 0
        pl_sign = "+" if total_pl >= 0 else ""

        col1, col2, col3 = st.columns(3)
        col1.metric("Total Modal Aktual", format_rupiah(total_modal_all))
        col2.metric("Total Nilai Pasar", format_rupiah(total_pasar_all))
        col3.metric(
            "Total Unrealized P/L",
            f"{pl_sign}{format_rupiah(total_pl)}",
            f"{pl_sign}{total_pl_pct:.1f}%",
        )

        st.divider()

        # ── Chart Trajectory Aktual vs Proyeksi ───────────────────────────
        st.subheader("📈 Perjalanan Aktual vs Proyeksi")
        trajectory = compute_portfolio_trajectory(history, live_prices)

        if not trajectory.empty:
            fig4 = go.Figure()

            # Proyeksi P50 (sebagai referensi)
            time_labels_dt = [t for t in result["time_labels"]]
            fig4.add_trace(go.Scatter(
                x=time_labels_dt, y=result["p50"],
                mode="lines", name="Proyeksi Median (P50)",
                line=dict(color="#4fc3f7", width=1.5, dash="dot"),
                opacity=0.7,
            ))

            # Modal aktual yang diinvestasikan
            fig4.add_trace(go.Scatter(
                x=trajectory["date"], y=trajectory["total_invested"],
                mode="lines", name="Modal Diinvestasikan",
                line=dict(color="#a0a0b0", width=1.5, dash="dash"),
            ))

            # Nilai pasar aktual (estimasi)
            fig4.add_trace(go.Scatter(
                x=trajectory["date"], y=trajectory["estimated_market_value"],
                mode="lines+markers", name="Nilai Pasar Aktual",
                line=dict(color="#63ca6d", width=2.5),
                marker=dict(size=6),
            ))

            fig4.update_layout(
                xaxis_title="Tanggal",
                yaxis_title="Nilai (Rp)",
                yaxis_tickprefix="Rp ",
                yaxis_tickformat=".2s",
                hovermode="x unified",
                height=350,
                template="plotly_dark",
                legend=dict(orientation="h", y=1.1),
            )
            st.plotly_chart(fig4, use_container_width=True)
            st.caption(
                "Nilai pasar historis menggunakan harga beli sebagai estimasi. "
                "Bulan terakhir menggunakan harga live."
            )

        st.divider()

        # ── Tabel Riwayat + Delete ─────────────────────────────────────────
        st.subheader("📋 Detail Transaksi")
        display_df = history.copy()
        display_df["date"] = display_df["date"].dt.strftime("%Y-%m-%d")
        display_df["Hapus"] = False
        display_df = display_df.rename(columns={
            "date": "Tanggal", "ticker": "Saham",
            "lots": "Lot", "price_per_share": "Harga/Lembar",
            "total_cost": "Total Biaya", "notes": "Catatan",
        })

        edited = st.data_editor(
            display_df[["Tanggal", "Saham", "Lot", "Harga/Lembar", "Total Biaya", "Catatan", "Hapus"]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "Harga/Lembar": st.column_config.NumberColumn(format="Rp %d"),
                "Total Biaya": st.column_config.NumberColumn(format="Rp %d"),
                "Hapus": st.column_config.CheckboxColumn("Hapus?"),
            },
            disabled=["Tanggal", "Saham", "Lot", "Harga/Lembar", "Total Biaya", "Catatan"],
        )

        rows_to_delete = edited[edited["Hapus"]].index.tolist()
        if rows_to_delete:
            if st.button(
                f"🗑️ Hapus {len(rows_to_delete)} transaksi terpilih",
                type="primary",
            ):
                updated_history = history.drop(index=rows_to_delete).reset_index(drop=True)
                save_history(HISTORY_FILE, updated_history)
                st.success("Transaksi dihapus.")
                st.rerun()

# ════════════════════════════════════════════════════════════════════════════
# TAB 5: WHAT-IF SIMULATOR
# ════════════════════════════════════════════════════════════════════════════
with tab5:
    st.subheader("🔮 What-If Simulator")
    st.caption("Bandingkan skenario berbeda — ubah DCA, skip bulan, atau set target pensiun.")

    # ── Section 1: Perbandingan Skenario DCA ──────────────────────────────
    st.markdown("### 📊 Bandingkan 3 Skenario DCA")
    st.caption("Berapa beda hasilnya kalau DCA dinaikkan atau diturunkan?")

    col_s1, col_s2, col_s3 = st.columns(3)
    with col_s1:
        st.markdown("**Skenario 1** — Rencana Saat Ini")
        sc1_dca  = st.number_input("DCA/bulan (Rp)", value=int(monthly_dca),   step=50_000, key="sc1_dca", format="%d")
        sc1_skip = st.number_input("Skip per tahun (bulan)", value=0, min_value=0, max_value=11, key="sc1_skip")
    with col_s2:
        st.markdown("**Skenario 2** — Lebih Agresif")
        sc2_dca  = st.number_input("DCA/bulan (Rp)", value=int(monthly_dca * 1.5), step=50_000, key="sc2_dca", format="%d")
        sc2_skip = st.number_input("Skip per tahun (bulan)", value=0, min_value=0, max_value=11, key="sc2_skip")
    with col_s3:
        st.markdown("**Skenario 3** — Lebih Konservatif")
        sc3_dca  = st.number_input("DCA/bulan (Rp)", value=int(monthly_dca * 0.5), step=50_000, key="sc3_dca", format="%d")
        sc3_skip = st.number_input("Skip per tahun (bulan)", value=2, min_value=0, max_value=11, key="sc3_skip")

    # Effective monthly DCA setelah skip
    def effective_dca(dca, skip_per_year):
        active_months = 12 - skip_per_year
        return dca * active_months / 12

    eff1 = effective_dca(sc1_dca, sc1_skip)
    eff2 = effective_dca(sc2_dca, sc2_skip)
    eff3 = effective_dca(sc3_dca, sc3_skip)

    # Jalankan simulasi untuk ketiga skenario
    common_args = dict(
        initial_value=initial_portfolio_value,
        years=years,
        annual_return=blended["cagr"],
        annual_volatility=blended["volatility"],
        annual_div_yield=blended["div_yield"],
        reinvest_div=reinvest_div,
        n_simulations=N_SIMULATIONS,
    )
    with st.spinner("Menjalankan 3 simulasi..."):
        r1 = simulate_dca(monthly_dca=eff1, seed=42, **common_args)
        r2 = simulate_dca(monthly_dca=eff2, seed=42, **common_args)
        r3 = simulate_dca(monthly_dca=eff3, seed=42, **common_args)

    # ── Chart Perbandingan ────────────────────────────────────────────────
    fig5 = go.Figure()

    scenarios = [
        (r1, f"Skenario 1 — {format_rupiah(sc1_dca)}/bln", "#63ca6d"),
        (r2, f"Skenario 2 — {format_rupiah(sc2_dca)}/bln", "#4fc3f7"),
        (r3, f"Skenario 3 — {format_rupiah(sc3_dca)}/bln", "#f0a500"),
    ]

    for res, label, color in scenarios:
        p50 = apply_inflation(res["p50"], years_axis, inflation_rate) if show_real else res["p50"]
        p10 = apply_inflation(res["p10"], years_axis, inflation_rate) if show_real else res["p10"]
        p90 = apply_inflation(res["p90"], years_axis, inflation_rate) if show_real else res["p90"]
        # Area P10-P90
        fig5.add_trace(go.Scatter(
            x=years_axis, y=p90, mode="lines",
            line=dict(color=color, width=0), showlegend=False,
        ))
        fig5.add_trace(go.Scatter(
            x=years_axis, y=p10, mode="lines",
            fill="tonexty", fillcolor=f"rgba({int(color[1:3],16)},{int(color[3:5],16)},{int(color[5:7],16)},0.08)",
            line=dict(color=color, width=0), showlegend=False,
        ))
        # Garis P50
        fig5.add_trace(go.Scatter(
            x=years_axis, y=p50, mode="lines", name=label,
            line=dict(color=color, width=2.5),
        ))

    # Garis modal Skenario 1 sebagai referensi
    fig5.add_trace(go.Scatter(
        x=years_axis, y=r1["total_invested"],
        mode="lines", name="Modal Sc.1",
        line=dict(color="#666", width=1, dash="dash"),
    ))

    fig5.update_layout(
        xaxis_title="Tahun ke-",
        yaxis_title="Nilai Portfolio" + (" Riil" if show_real else " Nominal") + " (Rp)",
        yaxis_tickprefix="Rp ", yaxis_tickformat=".2s",
        hovermode="x unified",
        height=400,
        template="plotly_dark",
        legend=dict(orientation="h", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig5, use_container_width=True)

    # ── Tabel Perbandingan di Tahun Pensiun ───────────────────────────────
    st.markdown("#### Perbandingan di Tahun Pensiun")

    def retirement_summary(res, label, dca_monthly, skip_per_year, effective):
        final = res["simulations"][:, -1]
        total_inv = res["total_invested"][-1]
        p50_val = float(np.percentile(final, 50))
        div_monthly = p50_val * blended["div_yield"] / 12
        real_div = div_monthly / inflation_factor if show_real else div_monthly
        breakeven_month = next(
            (i for i, v in enumerate(res["p50"]) if v >= res["total_invested"][i] and i > 0),
            None,
        )
        be_label = f"Tahun ke-{breakeven_month/12:.1f}" if breakeven_month else "Belum tercapai"
        return {
            "Skenario": label,
            "DCA/Bulan": format_rupiah(dca_monthly),
            "Skip/Tahun": f"{skip_per_year} bln",
            "Eff. DCA": format_rupiah(effective),
            "Total Modal": format_rupiah(total_inv),
            "Proyeksi P50": format_rupiah(float(np.percentile(final, 50))),
            "Proyeksi P10": format_rupiah(float(np.percentile(final, 10))),
            "Div/Bulan P50": format_rupiah(real_div) + (" riil" if show_real else ""),
            "Balik Modal": be_label,
        }

    summary_rows = [
        retirement_summary(r1, "Skenario 1", sc1_dca, sc1_skip, eff1),
        retirement_summary(r2, "Skenario 2", sc2_dca, sc2_skip, eff2),
        retirement_summary(r3, "Skenario 3", sc3_dca, sc3_skip, eff3),
    ]
    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

    st.divider()

    # ── Section 2: Target Calculator ─────────────────────────────────────
    st.markdown("### 🎯 Target Calculator")
    st.caption("Saya ingin pensiun dengan passive income sekian — berapa DCA yang dibutuhkan?")

    col_t1, col_t2 = st.columns([1, 1])
    with col_t1:
        target_income = st.number_input(
            "Target passive income/bulan (Rp)",
            min_value=500_000,
            value=5_000_000,
            step=500_000,
            format="%d",
            help="Dalam nilai nominal saat pensiun. Jika aktifkan inflasi, ini adalah target nilai hari ini.",
        )
        if show_real:
            target_income_nominal = target_income * inflation_factor
            st.caption(f"= {format_rupiah(target_income_nominal)} nominal di tahun {retirement_year}")
        else:
            target_income_nominal = target_income

    with col_t2:
        target_years = st.slider("Dalam berapa tahun?", 5, 35, years, key="target_years")

    total_return = blended["cagr"] + blended["div_yield"]
    required_dca = calculate_required_dca(
        target_monthly_income=target_income_nominal,
        div_yield=blended["div_yield"],
        annual_return=total_return,
        years=target_years,
        initial_value=initial_portfolio_value,
    )

    target_portfolio = target_income_nominal * 12 / blended["div_yield"] if blended["div_yield"] > 0 else 0

    col_r1, col_r2, col_r3 = st.columns(3)
    col_r1.metric(
        "Target Portfolio di Pensiun",
        format_rupiah(target_portfolio),
        help="Nilai portfolio yang dibutuhkan untuk menghasilkan target passive income",
    )
    col_r2.metric(
        "DCA Bulanan yang Dibutuhkan",
        format_rupiah(required_dca),
        f"{'↓' if required_dca < monthly_dca else '↑'} {format_rupiah(abs(required_dca - monthly_dca))} vs rencana",
        delta_color="inverse" if required_dca > monthly_dca else "normal",
    )
    col_r3.metric(
        "DCA Kamu Sekarang",
        format_rupiah(monthly_dca),
        "rencana saat ini",
    )

    if required_dca <= monthly_dca:
        surplus = monthly_dca - required_dca
        st.success(
            f"DCA Rp {monthly_dca:,.0f}/bulan sudah cukup untuk target "
            f"{format_rupiah(target_income)}/bulan saat pensiun. "
            f"Kamu bahkan punya surplus {format_rupiah(surplus)}/bulan yang bisa diinvestasikan lebih!"
        )
    else:
        gap = required_dca - monthly_dca
        st.warning(
            f"Untuk mencapai target {format_rupiah(target_income)}/bulan, "
            f"kamu perlu menambah DCA sebesar **{format_rupiah(gap)}/bulan** "
            f"(total {format_rupiah(required_dca)}/bulan)."
        )

# ════════════════════════════════════════════════════════════════════════════
# TAB 6: FUNDAMENTAL
# ════════════════════════════════════════════════════════════════════════════
with tab6:
    st.subheader("🔍 Snapshot Fundamental")
    st.caption(
        "Data valuasi live dari Yahoo Finance. "
        "Sinyal Murah/Wajar/Mahal berdasarkan rentang historis masing-masing saham."
    )

    with st.spinner("Mengambil data fundamental..."):
        fundamentals = {}
        for code, cfg in STOCKS.items():
            fundamentals[code] = fetch_fundamentals(cfg["ticker"], code)

    # ── DCA Score Cards ────────────────────────────────────────────────────
    st.markdown("### 🏆 Skor Ketertarikan DCA Bulan Ini")
    st.caption("Semakin tinggi skor → semakin menarik untuk di-DCA sekarang (PER 40% + PBV 40% + ROE 20%)")

    cols = st.columns(3)
    sorted_stocks = sorted(STOCKS.keys(), key=lambda c: fundamentals[c]["dca_score"], reverse=True)

    for i, code in enumerate(sorted_stocks):
        f = fundamentals[code]
        score = f["dca_score"]
        name = STOCKS[code]["name"]
        rank = ["🥇", "🥈", "🥉"][i]
        bar = "█" * (score // 10) + "░" * (10 - score // 10)
        color = "#63ca6d" if score >= 70 else "#f0a500" if score >= 40 else "#e07b54"
        cols[i].markdown(f"""
<div style="background:#1e1e2e; border-radius:12px; padding:16px; border-left:4px solid {color}">
    <div style="font-size:1.5rem">{rank} {code}</div>
    <div style="color:#aaa; font-size:0.8rem">{name}</div>
    <div style="color:{color}; font-size:2rem; font-weight:bold; margin:8px 0">{score}</div>
    <div style="color:{color}; font-family:monospace; font-size:0.85rem">{bar}</div>
    <div style="color:#888; font-size:0.75rem; margin-top:4px">DCA Score / 100</div>
</div>
        """, unsafe_allow_html=True)

    best = sorted_stocks[0]
    best_score = fundamentals[best]["dca_score"]
    if best_score >= 60:
        st.success(f"Berdasarkan valuasi fundamental, **{best}** adalah kandidat DCA terkuat bulan ini.")
    elif best_score >= 40:
        st.info(f"Semua saham berada di zona wajar. **{best}** sedikit lebih menarik secara valuasi.")
    else:
        st.warning("Semua saham terlihat mahal secara valuasi. Pertimbangkan tetap DCA rutin — timing market sulit.")

    st.divider()

    # ── Tabel Detail Fundamental ───────────────────────────────────────────
    st.markdown("### 📋 Detail Metrik Fundamental")

    for code, cfg in STOCKS.items():
        f = fundamentals[code]
        ranges = VALUATION_RANGES.get(code, {})

        with st.expander(f"**{code} — {cfg['name']}**  |  Skor: {f['dca_score']}/100", expanded=True):
            col_a, col_b, col_c, col_d = st.columns(4)

            # PER
            per_emoji, per_label = SIGNAL_EMOJI.get(f["per_signal"], ("⚪", "N/A"))
            per_range = ranges.get("PER", {})
            col_a.metric(
                f"PER  {per_emoji} {per_label}",
                f"{f['PER']:.1f}x" if f["PER"] else "N/A",
                help=f"Murah <{per_range.get('murah', ('?','?'))[1]}x | Wajar {per_range.get('wajar', ('?','?'))[0]}–{per_range.get('wajar', ('?','?'))[1]}x | Mahal >{per_range.get('mahal', ('?','?'))[0]}x",
            )

            # PBV
            pbv_emoji, pbv_label = SIGNAL_EMOJI.get(f["pbv_signal"], ("⚪", "N/A"))
            pbv_range = ranges.get("PBV", {})
            col_b.metric(
                f"PBV  {pbv_emoji} {pbv_label}",
                f"{f['PBV']:.2f}x" if f["PBV"] else "N/A",
                help=f"Murah <{pbv_range.get('murah', ('?','?'))[1]}x | Wajar {pbv_range.get('wajar', ('?','?'))[0]}–{pbv_range.get('wajar', ('?','?'))[1]}x",
            )

            # ROE
            roe_emoji, roe_label = SIGNAL_EMOJI.get(f["roe_signal"], ("⚪", "N/A"))
            col_c.metric(
                f"ROE  {roe_emoji} {roe_label}",
                f"{f['ROE']:.1f}%" if f["ROE"] else "N/A",
                help="Return on Equity — seberapa efisien perusahaan menghasilkan profit dari modal sendiri",
            )

            # Forward PER
            col_d.metric(
                "Forward PER",
                f"{f['Forward PER']:.1f}x" if f["Forward PER"] else "N/A",
                help="PER berdasarkan estimasi laba ke depan (lebih forward-looking)",
            )

            col_e, col_f = st.columns(2)
            col_e.metric("EPS (Trailing)", f"Rp {f['EPS']:,.0f}" if f["EPS"] else "N/A")
            col_f.metric("Market Cap", format_market_cap(f["Market Cap"]))

            # Rentang referensi
            st.caption(
                f"Rentang historis **{code}**: "
                f"PER murah <{per_range.get('murah', (0,0))[1]}x, wajar {per_range.get('wajar', (0,0))[0]}–{per_range.get('wajar', (0,0))[1]}x | "
                f"PBV murah <{pbv_range.get('murah', (0,0))[1]}x, wajar {pbv_range.get('wajar', (0,0))[0]}–{pbv_range.get('wajar', (0,0))[1]}x"
            )

    st.divider()

    # ── Chart Radar: Perbandingan Visual ──────────────────────────────────
    st.markdown("### 🕸️ Perbandingan Visual DCA Score")

    categories = ["DCA Score", "PER Score", "PBV Score", "ROE Score"]

    def metric_score(signal, metric_type):
        if metric_type in ("PER", "PBV"):
            return {"murah": 100, "wajar": 50, "mahal": 10, "n/a": 25}.get(signal, 25)
        else:  # ROE
            return {"tinggi": 100, "normal": 60, "rendah": 20, "n/a": 25}.get(signal, 25)

    fig6 = go.Figure()
    for code, cfg in STOCKS.items():
        f = fundamentals[code]
        values = [
            f["dca_score"],
            metric_score(f["per_signal"], "PER"),
            metric_score(f["pbv_signal"], "PBV"),
            metric_score(f["roe_signal"], "ROE"),
        ]
        values_closed = values + [values[0]]
        cats_closed = categories + [categories[0]]
        fig6.add_trace(go.Scatterpolar(
            r=values_closed,
            theta=cats_closed,
            fill="toself",
            name=f"{code}",
            line=dict(color=cfg["color"]),
            fillcolor=cfg["color"],
            opacity=0.3,
        ))

    fig6.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
        showlegend=True,
        template="plotly_dark",
        height=380,
    )
    st.plotly_chart(fig6, use_container_width=True)
    st.caption(
        "⚠️ Sinyal fundamental hanya alat bantu — bukan rekomendasi beli/jual. "
        "Tetap lakukan riset mandiri sebelum berinvestasi."
    )
