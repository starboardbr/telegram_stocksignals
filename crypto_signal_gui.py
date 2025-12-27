#!/usr/bin/env python3
"""
Interface gráfica simples para rodar o CryptoSignalBot.
"""

import io
import json
import threading
from contextlib import redirect_stdout
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from crypto_signal_bot import CryptoSignalBot


class SignalGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Crypto Signal Bot")
        self.root.geometry("720x520")

        self.bot = CryptoSignalBot()

        self.status_var = tk.StringVar(value="Pronto para escanear.")

        top_frame = ttk.Frame(root, padding=10)
        top_frame.pack(fill="x")

        custom_frame = ttk.Frame(top_frame)
        custom_frame.pack(side="right")
        ttk.Label(custom_frame, text="Custom pares (ex: BTC, ETH): ").pack(side="left")
        self.custom_entry = ttk.Entry(custom_frame, width=30)
        self.custom_entry.pack(side="left")

        self.run_button = ttk.Button(top_frame, text="Rodar scanner", command=self.run_scan)
        self.run_button.pack(side="left")

        self.status_label = ttk.Label(top_frame, textvariable=self.status_var)
        self.status_label.pack(side="left", padx=10)

        text_frame = ttk.Frame(root, padding=(10, 0, 10, 10))
        text_frame.pack(fill="both", expand=True)

        self.output = tk.Text(text_frame, wrap="word")
        self.output.pack(fill="both", expand=True)

    def run_scan(self):
        if not self.run_button["state"] == "disabled":
            self.run_button.state(["disabled"])
        self.status_var.set("Escaneando pares...")
        self.output.delete("1.0", tk.END)

        custom_text = self.custom_entry.get().strip()
        if custom_text:
            extras = [p.strip() for p in custom_text.split(",") if p.strip()]
            self.bot.set_custom_pairs(extras)
        else:
            self.bot.set_custom_pairs([])

        thread = threading.Thread(target=self._run_in_background, daemon=True)
        thread.start()

    def _run_in_background(self):
        buffer = io.StringIO()
        signals = []
        with redirect_stdout(buffer):
            signals = self.bot.run()
        output_text = buffer.getvalue()
        self.root.after(0, self._on_finish, output_text, signals)

    def _on_finish(self, output_text: str, signals):
        self.output.insert("1.0", output_text)
        self.status_var.set("Concluído.")
        self.run_button.state(["!disabled"])

        if signals:
            self._save_signals(signals)
            self.output.insert(tk.END, "\n💾 Sinais salvos em signals.json\n")

    def _save_signals(self, signals):
        path = Path("signals.json")
        with path.open("w") as f:
            json.dump(signals, f, indent=2)


def main():
    root = tk.Tk()
    app = SignalGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
