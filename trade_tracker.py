"""
Trade tracker simples para persistir sinais e marcar TP/STOP em execuções futuras.
"""

import json
from pathlib import Path
from typing import Dict, List


class TradeTracker:
    def __init__(self, path: Path):
        self.path = path
        self.trades: List[Dict] = []
        self.load()

    def load(self):
        if self.path.exists():
            try:
                self.trades = json.loads(self.path.read_text())
            except Exception:
                self.trades = []

    def save(self):
        self.path.write_text(json.dumps(self.trades, indent=2))

    def _find_trade(self, symbol: str, timeframe: str):
        for t in self.trades:
            if t.get("symbol") == symbol and t.get("timeframe") == timeframe and t.get("status") in ("open", "tp1"):
                return t
        return None

    def add_trade(self, analysis: Dict, created_at: str):
        if self._find_trade(analysis["symbol"], analysis.get("timeframe", "")):
            return
        self.trades.append(
            {
                "symbol": analysis["symbol"],
                "timeframe": analysis.get("timeframe", ""),
                "entry": analysis["entry"],
                "stop_loss": analysis["stop_loss"],
                "tp1": analysis["tp1"],
                "tp2": analysis["tp2"],
                "status": "open",
                "created_at": created_at,
                "last_update": created_at,
                "last_price": analysis["price"],
                "pnl_pct": 0.0,
            }
        )

    def update_with_analyses(self, analyses: List[Dict], ts: str) -> List[str]:
        updates = []
        for a in analyses:
            trade = self._find_trade(a["symbol"], a.get("timeframe", ""))
            if not trade:
                continue
            price = a["price"]
            status = trade["status"]
            trade["last_price"] = price
            trade["pnl_pct"] = (price / trade["entry"] - 1) * 100
            if status in ("tp2", "stopped"):
                continue
            new_status = status
            msg = None
            if price <= trade["stop_loss"]:
                new_status = "stopped"
                pnl = (trade["stop_loss"] / trade["entry"] - 1) * 100
                msg = f"⛔ STOP {trade['symbol']}: saída {trade['stop_loss']:.2f} ({pnl:+.2f}%)"
            elif price >= trade["tp2"]:
                new_status = "tp2"
                pnl = (trade["tp2"] / trade["entry"] - 1) * 100
                msg = f"🎯 TP2 {trade['symbol']}: {trade['tp2']:.2f} ({pnl:+.2f}%)"
            elif price >= trade["tp1"] and status == "open":
                new_status = "tp1"
                pnl = (trade["tp1"] / trade["entry"] - 1) * 100
                msg = f"✅ TP1 {trade['symbol']}: {trade['tp1']:.2f} ({pnl:+.2f}%)"

            if new_status != status:
                trade["status"] = new_status
                trade["last_update"] = ts
                if msg:
                    updates.append(msg)
        return updates
