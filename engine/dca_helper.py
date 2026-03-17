from config import LOT_SIZE


def get_dca_recommendation(
    current_prices: dict[str, float | None],
    current_lots: dict[str, int],
    target_alloc: dict[str, float],
    monthly_budget: float,
    accumulated_cash: float = 0.0,
) -> dict:
    """
    Tentukan saham mana yang harus dibeli bulan ini berdasarkan rebalancing.
    Logika: beli saham yang paling underfunded relatif terhadap target alokasi.

    Returns:
        recommendation: dict berisi saham yang direkomendasikan dan detail pembelian.
    """
    available_budget = monthly_budget + accumulated_cash

    # Hitung nilai portfolio saat ini per saham
    portfolio_values = {}
    for code, lots in current_lots.items():
        price = current_prices.get(code)
        if price:
            portfolio_values[code] = lots * LOT_SIZE * price
        else:
            portfolio_values[code] = 0.0

    total_portfolio = sum(portfolio_values.values())

    # Hitung alokasi aktual vs target
    actual_alloc = {}
    alloc_gap = {}
    for code in current_lots:
        if total_portfolio > 0:
            actual_alloc[code] = portfolio_values[code] / total_portfolio
        else:
            actual_alloc[code] = 0.0
        alloc_gap[code] = target_alloc[code] - actual_alloc[code]

    # Pilih saham paling underweight (gap terbesar)
    recommended = max(alloc_gap, key=alloc_gap.get)

    # Hitung berapa lot yang bisa dibeli
    price = current_prices.get(recommended)
    lots_can_buy = 0
    cost = 0
    remaining_cash = available_budget

    if price:
        lot_price = price * LOT_SIZE
        lots_can_buy = int(available_budget // lot_price)
        cost = lots_can_buy * lot_price
        remaining_cash = available_budget - cost

    return {
        "recommended_stock": recommended,
        "price": price,
        "lots_to_buy": lots_can_buy,
        "cost": cost,
        "remaining_cash": remaining_cash,
        "available_budget": available_budget,
        "portfolio_values": portfolio_values,
        "total_portfolio": total_portfolio,
        "actual_alloc": actual_alloc,
        "alloc_gap": alloc_gap,
    }


def format_rupiah(value: float) -> str:
    """Format angka ke format Rupiah Indonesia."""
    if value >= 1_000_000_000:
        return f"Rp {value / 1_000_000_000:.2f} M"
    elif value >= 1_000_000:
        return f"Rp {value / 1_000_000:.1f} jt"
    elif value >= 1_000:
        return f"Rp {value / 1_000:.0f} rb"
    else:
        return f"Rp {value:.0f}"
