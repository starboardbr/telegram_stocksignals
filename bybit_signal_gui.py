#!/usr/bin/env python3
"""
Interface simples para colar um sinal de Telegram e simular a execução na Bybit (sem enviar ordens).

Use:
  python3 bybit_signal_gui.py

Cole o texto do sinal e clique em "Executar (simulação)".
"""

import os
import re
import tkinter as tk
from tkinter import ttk

try:
    from pybit.unified_trading import HTTP  # type: ignore
except Exception:  # noqa: BLE001
    HTTP = None


class SignalParser:
    sym_re = re.compile(r"#?([A-Z]{2,15})\s*/\s*USDT", re.IGNORECASE)
    entry_re = re.compile(r"Entrada:\s*([\d.]+)", re.IGNORECASE)
    targets_re = re.compile(r"Alvos:\s*([^\n]+)", re.IGNORECASE)
    stop_re = re.compile(r"Stop\s*Loss:\s*([^\n]+)", re.IGNORECASE)
    lev_re = re.compile(r"Alavancagem:\s*([^\n]+)", re.IGNORECASE)

    def parse(self, text: str):
        sym_m = self.sym_re.search(text)
        entry_m = self.entry_re.search(text)
        targets_m = self.targets_re.search(text)
        stop_m = self.stop_re.search(text)
        lev_m = self.lev_re.search(text)
        if not sym_m or not entry_m:
            return None, "Não encontrei símbolo ou entrada."

        symbol = sym_m.group(1).upper() + "USDT"
        entry = float(entry_m.group(1))

        leverage_txt = lev_m.group(1).strip() if lev_m else ""
        lev_num = re.search(r"(\d+)", leverage_txt)
        leverage = float(lev_num.group(1)) if lev_num else None

        targets = []
        if targets_m:
            parts = re.split(r"[,-]\s*", targets_m.group(1))
            for p in parts:
                p = p.strip().strip("%")
                if not p:
                    continue
                try:
                    pct = float(p)
                    targets.append(entry * (1 + pct / 100))
                except ValueError:
                    continue

        stop_val = None
        if stop_m:
            s = stop_m.group(1).strip()
            if s.lower() not in ("hold", "segurar"):
                try:
                    stop_val = float(s)
                except ValueError:
                    stop_val = None

        return {
            "symbol": symbol,
            "entry": entry,
            "targets": targets,
            "stop": stop_val,
            "leverage": leverage,
            "raw_leverage": leverage_txt,
        }, None


class BybitTrader:
    def __init__(self, api_key: str | None, api_secret: str | None, dry_run: bool = True):
        self.dry_run = dry_run or not (api_key and api_secret and HTTP)
        self.client = None
        if not self.dry_run and HTTP:
            self.client = HTTP(testnet=True, api_key=api_key, api_secret=api_secret)

    def ensure_symbol(self, symbol: str) -> bool:
        return symbol.endswith("USDT")

    def place(self, symbol: str, entry: float, targets: list[float], stop: float, size_usdt: float, leverage: float):
        if not self.ensure_symbol(symbol):
            return f"❌ Símbolo inválido: {symbol}"
        qty = size_usdt / entry / leverage
        msg = (
            f"▶️ {symbol} entry={entry:.4f} qty={qty:.4f} lev={leverage}x "
            f"stop={stop:.4f} targets={','.join([f'{t:.4f}' for t in targets])}"
        )
        if self.dry_run or not self.client:
            return msg + " (dry-run)"

        try:
            sym = symbol
            self.client.place_order(
                category="linear",
                symbol=sym,
                side="Buy",
                orderType="Market",
                qty=round(qty, 4),
                timeInForce="IOC",
                leverage=leverage,
            )
            part_qty = qty / max(len(targets), 1)
            for tgt in targets:
                self.client.place_order(
                    category="linear",
                    symbol=sym,
                    side="Sell",
                    orderType="Limit",
                    qty=round(part_qty, 4),
                    price=round(tgt, 4),
                    reduceOnly=True,
                )
            self.client.set_trading_stop(category="linear", symbol=sym, stopLoss=round(stop, 4))
            return msg + " (ordens enviadas para testnet)"
        except Exception as e:  # noqa: BLE001
            return f"{msg} | erro: {e}"


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Executor de Sinais (Simulação)")
        self.root.geometry("760x520")

        self.parser = SignalParser()

        top = ttk.Frame(root, padding=10)
        top.pack(fill="x")

        ttk.Label(top, text="Tamanho (USDT):").pack(side="left")
        self.size_var = tk.DoubleVar(value=50.0)
        ttk.Entry(top, textvariable=self.size_var, width=10).pack(side="left", padx=5)

        ttk.Label(top, text="Saldo (USDT):").pack(side="left", padx=(10, 0))
        self.balance_var = tk.DoubleVar(value=500.0)
        ttk.Entry(top, textvariable=self.balance_var, width=10).pack(side="left", padx=5)

        ttk.Label(top, text="Posições abertas:").pack(side="left", padx=(10, 0))
        self.open_pos_var = tk.IntVar(value=0)
        ttk.Entry(top, textvariable=self.open_pos_var, width=6).pack(side="left", padx=5)

        ttk.Label(top, text="Modo:").pack(side="left", padx=(10, 0))
        self.mode_var = tk.StringVar(value="safe")
        ttk.Combobox(top, textvariable=self.mode_var, values=["safe", "high_risk"], width=10, state="readonly").pack(side="left")

        ttk.Label(top, text="Alavancagem padrão:").pack(side="left")
        self.lev_var = tk.DoubleVar(value=10.0)
        ttk.Entry(top, textvariable=self.lev_var, width=6).pack(side="left", padx=5)

        ttk.Label(top, text="Stop de segurança (%) se Hold:").pack(side="left")
        self.stop_pct_var = tk.DoubleVar(value=8.0)
        ttk.Entry(top, textvariable=self.stop_pct_var, width=6).pack(side="left", padx=5)

        self.live_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="Enviar ordens (testnet)", variable=self.live_var).pack(side="right")

        ttk.Button(top, text="Executar", command=self.run_sim).pack(side="right", padx=6)

        body = ttk.Frame(root, padding=10)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="Cole o sinal aqui:").pack(anchor="w")
        self.input_txt = tk.Text(body, height=10)
        self.input_txt.pack(fill="x")

        ttk.Label(body, text="Resultado:").pack(anchor="w", pady=(10, 0))
        self.output = tk.Text(body, height=12)
        self.output.pack(fill="both", expand=True)

    def run_sim(self):
        text = self.input_txt.get("1.0", tk.END).strip()
        self.output.delete("1.0", tk.END)
        if not text:
            self.output.insert(tk.END, "Cole um sinal para simular.\n")
            return

        parsed, err = self.parser.parse(text)
        if err:
            self.output.insert(tk.END, f"Erro de parse: {err}\n")
            return

        # sizing baseado nas regras
        balance = self.balance_var.get()
        base_size = self.size_var.get()
        pct = 0.01 if balance < 1000 else 0.005
        size_rule = balance * pct
        size = min(base_size, size_rule)
        # limite de posições
        open_pos = self.open_pos_var.get()
        limit = 20
        if balance <= 100:
            limit = 5
        elif balance <= 200:
            limit = 8
        elif balance <= 300:
            limit = 13
        elif balance <= 400:
            limit = 18
        elif balance <= 500:
            limit = 30
        else:
            limit = 20
        if open_pos >= limit:
            self.output.insert(tk.END, f"Limite de posições atingido ({open_pos}/{limit}). Nenhuma ordem enviada.\n")
            return

        leverage = parsed["leverage"] or self.lev_var.get()
        entry = parsed["entry"]
        qty = size / entry / leverage

        stop = parsed["stop"]
        if stop is None:
            stop = entry * (1 - self.stop_pct_var.get() / 100)

        targets = parsed["targets"] or [entry * 1.02]
        mode = self.mode_var.get()
        # splits por modo
        if mode == "safe":
            weights = [0.50, 0.15, 0.10, 0.05, 0.05, 0.05, 0.05, 0.05]
        elif mode == "high_risk":
            weights = [0.50]  # TP5 50% e resto segurando; usamos primeiro alvo
        else:
            weights = [1.0]
        # normalizar pesos conforme quantidade de targets disponível
        if len(targets) < len(weights):
            weights = weights[: len(targets)]
        if len(weights) < len(targets):
            # se mais targets do que pesos, dividir restante igualmente
            rem = len(targets) - len(weights)
            weights += [ (1 - sum(weights)) / rem ] * rem
        # renormaliza para 1
        total_w = sum(weights)
        if total_w == 0:
            weights = [1 / len(targets)] * len(targets)
            total_w = 1
        weights = [w / total_w for w in weights]

        lines = [
            f"SINAL: {parsed['symbol']} | Entrada: {entry:.4f}",
            f"Alavancagem: {leverage}x | Tamanho: {size:.2f} USDT (regra {pct*100:.1f}% saldo={balance}) | Qty: {qty:.4f}",
            f"Stop: {stop:.4f}",
            "Alvos:",
        ]
        for i, (t, w) in enumerate(zip(targets, weights), 1):
            lines.append(f"  TP{i}: {t:.4f} (parcela {w*100:.1f}%)")

        send_orders = self.live_var.get()
        lines.append(f"\nEnvio de ordens: {'SIM (testnet)' if send_orders else 'NÃO, apenas simulação'}")

        if send_orders:
            api_key = os.getenv("BYBIT_API_KEY")
            api_secret = os.getenv("BYBIT_API_SECRET")
            trader = BybitTrader(api_key, api_secret, dry_run=False)
            result = trader.place(parsed["symbol"], entry, targets, stop, size_usdt=size, leverage=leverage)
            lines.append(result)
        else:
            lines.append("Dry-run: nenhuma ordem enviada.")

        self.output.insert(tk.END, "\n".join(lines) + "\n")


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
