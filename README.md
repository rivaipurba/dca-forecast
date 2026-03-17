# 📈 DCA Forecast — Perjalanan Pensiun

Aplikasi personal untuk forecasting investasi DCA saham Indonesia dengan horizon pensiun jangka panjang.

Dibangun untuk investor buy-and-hold yang ingin **melihat hasil ketekunan DCA** secara visual agar tetap termotivasi.

---

## Fitur

| Tab | Fitur |
|-----|-------|
| 📊 Proyeksi Portfolio | Monte Carlo 500 skenario, grafik pertumbuhan 25 tahun (P10/P50/P90) |
| 💰 Dashboard Pensiun | Proyeksi passive income dividen bulanan saat pensiun |
| 📅 DCA Bulan Ini | Rekomendasi saham yang dibeli bulan ini (rebalancing-based) |
| 📒 Riwayat DCA | Catat transaksi, hitung cost basis (VWAP), unrealized P/L |
| 🔮 What-If | Bandingkan 3 skenario DCA + target calculator |
| 🔍 Fundamental | Snapshot PER, PBV, ROE + DCA Score per saham |

### Highlight
- **Monte Carlo simulation** — 500 skenario, proyeksi pesimis/median/optimis
- **Inflasi adjustment** — toggle nominal vs nilai riil (default 4.5%/tahun)
- **DCA Score** — sinyal Murah/Wajar/Mahal berbasis valuasi historis per saham
- **Target calculator** — hitung berapa DCA yang dibutuhkan untuk target passive income tertentu
- **Override asumsi** — koreksi CAGR & div yield per saham jika data live tidak representatif

---

## Saham yang Ditrack

| Kode | Nama | Target Alokasi |
|------|------|---------------|
| BBRI | Bank BRI | 50% |
| ADRO | Adaro Energy | 30% |
| TLKM | Telkom Indonesia | 20% |

---

## Instalasi

```bash
# Clone repo
git clone https://github.com/rivaipurba/dca-forecast.git
cd dca-forecast

# Install dependencies
pip install -r requirements.txt

# Jalankan aplikasi
streamlit run app.py
```

Buka browser di `http://localhost:8501`

---

## Stack

- **Python 3.14**
- **Streamlit** — UI dashboard
- **yfinance** — data harga & fundamental live dari Yahoo Finance
- **Plotly** — chart interaktif
- **pandas / numpy** — kalkulasi & simulasi
- **Monte Carlo** — proyeksi probabilistik

---

## Struktur Project

```
dca-forecast/
├── app.py                  # Streamlit dashboard utama
├── config.py               # Konfigurasi saham & konstanta
├── requirements.txt
└── engine/
    ├── data_fetcher.py     # Fetch live data dari Yahoo Finance
    ├── projection.py       # Monte Carlo DCA simulation
    ├── dca_helper.py       # Logika rekomendasi DCA bulanan
    ├── history_manager.py  # CRUD riwayat transaksi (CSV)
    └── fundamental.py      # Snapshot PER, PBV, ROE & DCA Score
```

> **Catatan:** Folder `data/` (berisi riwayat transaksi pribadi) di-exclude dari git via `.gitignore`.

---

## Cara Pakai

1. **Input riwayat transaksi** di Tab 📒 — lot dan harga beli yang sudah dilakukan
2. **Set override asumsi** di sidebar jika CAGR live tidak realistis (misal ADRO terdistorsi coal boom)
3. **Pantau Tab 🔍 Fundamental** setiap awal bulan untuk tahu saham mana yang paling menarik
4. **Eksekusi DCA** sesuai rekomendasi di Tab 📅
5. **Lihat Tab 🔮 What-If** jika ingin simulasi naik/turun DCA atau set target passive income

---

## Disclaimer

Aplikasi ini adalah **alat bantu personal**, bukan rekomendasi investasi. Seluruh proyeksi bersifat estimasi berdasarkan data historis dan asumsi yang dapat berubah. Lakukan riset mandiri sebelum mengambil keputusan investasi.
