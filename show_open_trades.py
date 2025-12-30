#!/usr/bin/env python3
"""
Mostra trades abertos ou parcial (tp1) no stock_trades.json.
"""

import json
from pathlib import Path


def main():
    path = Path("stock_trades.json")
    if not path.exists():
        print("Nenhum arquivo stock_trades.json encontrado.")
        return

    data = json.loads(path.read_text())
    # data pode ser dict (keyed) ou list; normaliza para list
    if isinstance(data, dict):
        trades = list(data.values())
    elif isinstance(data, list):
        trades = data
    else:
        print("Formato inesperado em stock_trades.json")
        return

    open_trades = [t for t in trades if t.get("status") in ("open", "tp1")]

    if not open_trades:
        print("Nenhum trade aberto ou em tp1.")
        return

    print(f"Trades abertos: {len(open_trades)}\n")
    for t in open_trades:
        pnl = t.get("pnl_pct", 0)
        last_price = t.get("last_price", 0)
        print(f"{t['symbol']} | status={t['status']} | entry={t['entry']:.4f} | "
              f"price={last_price:.4f} | pnl={pnl:+.2f}% | "
              f"stop={t['stop_loss']:.4f} | tp1={t['tp1']:.4f} | tp2={t['tp2']:.4f} | "
              f"last_update={t.get('last_update','')}")


if __name__ == "__main__":
    main()
