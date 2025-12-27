#!/usr/bin/env python3
"""
Interface gráfica simples para rodar o StockSignalBot.
"""

import io
import json
import threading
import tkinter as tk
from contextlib import redirect_stdout
from pathlib import Path
from tkinter import ttk

import numpy as np
import pandas as pd

from stock_signal_bot import StockSignalBot


class StockSignalGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Stock Signal Bot")
        self.root.geometry("760x560")

        self.bot = StockSignalBot()
        self.status_var = tk.StringVar(value="Pronto para escanear ações.")

        top = ttk.Frame(root, padding=10)
        top.pack(fill="x")

        custom = ttk.Frame(top)
        custom.pack(side="right")
        ttk.Label(custom, text="Custom tickers (ex: BRK.B, KO): ").pack(side="left")
        self.custom_entry = ttk.Entry(custom, width=30)
        self.custom_entry.pack(side="left")

        self.run_button = ttk.Button(top, text="Rodar scanner de ações", command=self.run_scan)
        self.run_button.pack(side="left")

        self.status_label = ttk.Label(top, textvariable=self.status_var)
        self.status_label.pack(side="left", padx=10)

        text_frame = ttk.Frame(root, padding=(10, 0, 10, 10))
        text_frame.pack(fill="both", expand=True)

        self.output = tk.Text(text_frame, wrap="word")
        self.output.pack(fill="both", expand=True)

    def run_scan(self):
        self.run_button.state(["disabled"])
        self.status_var.set("Escaneando...")
        self.output.delete("1.0", tk.END)
        custom_text = self.custom_entry.get().strip()
        if custom_text:
            extras = [t.strip() for t in custom_text.split(",") if t.strip()]
            self.bot.set_custom_tickers(extras)
        else:
            self.bot.set_custom_tickers([])
        threading.Thread(target=self._run_bg, daemon=True).start()

    def _run_bg(self):
        buf = io.StringIO()
        signals = []
        with redirect_stdout(buf):
            signals = self.bot.run()
        self.root.after(0, self._on_finish, buf.getvalue(), signals)

    def _on_finish(self, text: str, signals):
        self.output.insert("1.0", text)
        self.status_var.set("Concluído.")
        self.run_button.state(["!disabled"])
        if signals:
            self._save(signals)
            self.output.insert(tk.END, "\n💾 Sinais salvos em stock_signals.json\n")

    def _save(self, signals):
        payload = []
        for s in signals:
            s_copy = s.copy()
            s_copy["generated_at"] = self.bot.last_run_at
            payload.append({k: v for k, v in s_copy.items() if not isinstance(v, (pd.Series, np.ndarray))})
        Path("stock_signals.json").write_text(json.dumps(payload, indent=2))


def main():
    root = tk.Tk()
    app = StockSignalGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
