#!/usr/bin/env python3
"""
Envia relatórios do Crypto/Stock Signal Bot via Telegram.

Variáveis de ambiente necessárias:
  TELEGRAM_BOT_TOKEN
  TELEGRAM_CHAT_ID

Uso:
  python3 send_telegram_reports.py --mode both        # cripto + ações
  python3 send_telegram_reports.py --mode crypto      # só cripto
  python3 send_telegram_reports.py --mode stocks      # só ações
"""

import argparse
import io
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import List

import requests
import pandas as pd

from crypto_signal_bot import CryptoSignalBot
from stock_signal_bot import StockSignalBot


TELEGRAM_MAX = 4096  # limite de caracteres por mensagem


def chunk_text(text: str, max_len: int = TELEGRAM_MAX) -> List[str]:
    return [text[i : i + max_len] for i in range(0, len(text), max_len)]


def send_telegram_message(token: str, chat_id: str, text: str):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for part in chunk_text(text):
        resp = requests.post(url, json={"chat_id": chat_id, "text": part})
        resp.raise_for_status()


def run_and_capture(bot) -> str:
    buf = io.StringIO()
    with redirect_stdout(buf):
        bot.run()
    return buf.getvalue()


def run_summary_only(bot) -> str:
    buf = io.StringIO()
    # Executa apenas o scan e o resumo, sem imprimir sinais detalhados
    with redirect_stdout(buf):
        bot.last_run_at = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M:%S UTC")
        bot.scan_all_pairs(verbose=False)
        bot.print_analysis_summary()
    return buf.getvalue()


def format_signal_compact(a: dict, updated_at: str, timeframe_fallback: str) -> str:
    tf = a.get("timeframe", timeframe_fallback)
    conf = a.get("confidence", 0)
    strength = a.get("signal_strength", "")
    price = a.get("price", 0)
    rsi = a.get("rsi", 0)
    vol = a.get("volume_increase", 0)
    adx = a.get("adx", 0)
    macd = "MACD+" if a.get("macd_positive") else "MACD-"
    if a.get("macd_crossover"):
        macd += " x↑"
    ema200_dir = "↑" if a.get("in_uptrend") else "↓"
    ratio = a.get("ratio_tp1", 0)
    line1 = f"• {a.get('symbol')} [{tf}] — Conf {conf}/100 {strength} | {updated_at}"
    line2 = (
        f"  Preço {price:.2f} | EMA200 {ema200_dir} | RSI {rsi:.1f} | {macd} | "
        f"Vol {vol:+.0f}% | ADX {adx:.0f}"
    )
    line3 = (
        f"  Entrada {a.get('entry', 0):.2f} | Stop {a.get('stop_loss', 0):.2f} | "
        f"TP1 {a.get('tp1', 0):.2f} | TP2 {a.get('tp2', 0):.2f} | R/R {ratio:.2f}"
    )
    line4 = f"  Sup {a.get('support', 0):.2f} | Res {a.get('resistance', 0):.2f}"
    return "\n".join([line1, line2, line3, line4])


def run_signals_only(bot, tracker_path: Path):
    from trade_tracker import TradeTracker

    buf = io.StringIO()
    tracker = TradeTracker(tracker_path)
    bot.last_run_at = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M:%S UTC")

    with redirect_stdout(buf):
        signals = bot.scan_all_pairs(verbose=False)

        # Atualizar trades existentes com preço atual
        updates = tracker.update_with_analyses(bot.last_analyses, bot.last_run_at)
        # Adicionar novos trades para sinais
        new_signals = [a for a in bot.last_analyses if a.get("should_alert")]
        for sig in new_signals:
            tracker.add_trade(sig, bot.last_run_at)
        tracker.save()

        if updates:
            print("📈 Atualizações de trades:")
            for u in updates:
                print(u)
            print()

        if new_signals:
            print(f"Sinais encontrados: {len(new_signals)}")
            for sig in new_signals:
                print(format_signal_compact(sig, bot.last_run_at, bot.interval))
                print()
        elif not updates:
            print("Sem sinais hoje.")
    return buf.getvalue(), signals if "signals" in locals() else []


def main():
    parser = argparse.ArgumentParser(description="Enviar relatórios dos bots via Telegram")
    parser.add_argument(
        "--mode",
        choices=["crypto", "stocks", "both"],
        default="both",
        help="Qual relatório enviar",
    )
    parser.add_argument(
        "--stocks-region",
        choices=["all", "us", "eu"],
        default="all",
        help="Rodar ações por região para reduzir tempo (all/us/eu)",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Enviar apenas o resumo (sem sinais detalhados) para reduzir tamanho/tempo",
    )
    parser.add_argument(
        "--signals-only",
        action="store_true",
        help="Enviar apenas sinais (se existirem), sem logs nem resumo",
    )
    args = parser.parse_args()

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("❌ Defina TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID no ambiente.")
        sys.exit(1)

    messages = []
    if args.mode in ("crypto", "both"):
        crypto_bot = CryptoSignalBot()
        if args.signals_only:
            out, signals = run_signals_only(crypto_bot, Path("crypto_trades.json"))
            messages.append("📈 CRYPTO SIGNALS\n" + out)
        else:
            text = run_summary_only(crypto_bot) if args.summary_only else run_and_capture(crypto_bot)
            messages.append("📈 CRYPTO REPORT\n" + text)

    if args.mode in ("stocks", "both"):
        stock_bot = StockSignalBot(region=args.stocks_region)
        if args.signals_only:
            out, signals = run_signals_only(stock_bot, Path("stock_trades.json"))
            messages.append("📊 STOCK SIGNALS\n" + out)
        else:
            text = run_summary_only(stock_bot) if args.summary_only else run_and_capture(stock_bot)
            messages.append("📊 STOCKS REPORT\n" + text)

    full_message = "\n\n".join(messages)
    send_telegram_message(token, chat_id, full_message)
    print("✅ Relatórios enviados via Telegram.")


if __name__ == "__main__":
    main()
