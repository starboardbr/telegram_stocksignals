#!/usr/bin/env python3
"""
Bot para ler sinais do canal do Telegram e (opcionalmente) enviar ordens na Bybit.
Fluxo:
 1) Usa Telethon para ler mensagens recentes do canal.
 2) Faz parse de sinais no formato:
    #STORJ / USDT CONFIGURAÇÃO DE COMPRA (ARRISCADO)
    Entrada: 0.1465
    Alavancagem: Máx. 10x-20x
    Alvos: 3% - 20% - 40% ...
    Stop Loss: Hold
 3) Gera planos de trade e (se configurado) envia ordens de mercado + TPs na Bybit.
Por padrão está em dry-run (não envia ordens). Configure as variáveis de ambiente para operar:
  TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION (nome do arquivo da sessão)
  TELEGRAM_CHANNEL (username ou link, ex.: https://t.me/+u8_FXC7Wdg04ZDIx)
  BYBIT_API_KEY, BYBIT_API_SECRET (opcional; se ausentes, dry-run)
  DEFAULT_LEVERAGE (ex.: 10), POSITION_SIZE_USDT (ex.: 50)
"""

import asyncio
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from telethon import TelegramClient
from telethon.tl.types import PeerChannel

try:
    from pybit.unified_trading import HTTP  # type: ignore
except Exception:
    HTTP = None  # pybit opcional; se ausente, roda dry-run


SIGNALS_FILE = Path("bybit_signals.json")


@dataclass
class Signal:
    symbol: str
    entry: float
    targets: List[float]
    stop: Optional[float]  # None para Hold
    leverage: Optional[float]
    raw_leverage: str
    text: str
    timestamp: str


class TelegramSignalListener:
    def __init__(self, api_id: int, api_hash: str, session_name: str, channel: str):
        self.client = TelegramClient(session_name, api_id, api_hash)
        self.channel = channel

    async def fetch_messages(self, limit: int = 20) -> List[str]:
        await self.client.start()
        entity = self.channel
        if self.channel.startswith("http"):
            entity = await self.client.get_entity(self.channel)
        msgs = await self.client.get_messages(entity, limit=limit)
        return [m.message for m in msgs if m.message]


class SignalParser:
    sym_re = re.compile(r"#?([A-Z]{2,15})\s*/\s*USDT", re.IGNORECASE)
    entry_re = re.compile(r"Entrada:\s*([\d.]+)", re.IGNORECASE)
    leverage_re = re.compile(r"Alavancagem:\s*([^\n]+)", re.IGNORECASE)
    targets_re = re.compile(r"Alvos:\s*([^\n]+)", re.IGNORECASE)
    stop_re = re.compile(r"Stop\s*Loss:\s*([^\n]+)", re.IGNORECASE)

    @staticmethod
    def parse_targets(text: str, entry: float) -> List[float]:
        # Converte lista de percentuais em preços (assume % acima da entrada)
        parts = re.split(r"[,-]\s*", text)
        targets = []
        for p in parts:
            p = p.strip().strip("%")
            if not p:
                continue
            try:
                pct = float(p)
                targets.append(entry * (1 + pct / 100))
            except ValueError:
                continue
        return targets

    def parse(self, text: str) -> Optional[Signal]:
        sym_m = self.sym_re.search(text)
        entry_m = self.entry_re.search(text)
        targets_m = self.targets_re.search(text)
        stop_m = self.stop_re.search(text)
        lev_m = self.leverage_re.search(text)
        if not sym_m or not entry_m:
            return None
        symbol = sym_m.group(1).upper() + "USDT"
        entry = float(entry_m.group(1))
        leverage_txt = lev_m.group(1).strip() if lev_m else ""
        # Escolhe um valor seguro se vier faixa
        leverage_val = None
        lev_num = re.search(r"(\d+)", leverage_txt)
        if lev_num:
            leverage_val = float(lev_num.group(1))
        targets = self.parse_targets(targets_m.group(1), entry) if targets_m else []
        stop_val = None
        if stop_m:
            s = stop_m.group(1).strip()
            if s.lower() not in ("hold", "segurar"):
                try:
                    stop_val = float(s)
                except ValueError:
                    stop_val = None
        return Signal(
            symbol=symbol,
            entry=entry,
            targets=targets,
            stop=stop_val,
            leverage=leverage_val,
            raw_leverage=leverage_txt,
            text=text,
            timestamp=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        )


class SignalStore:
    def __init__(self, path: Path):
        self.path = path
        self.data = self._load()

    def _load(self):
        if self.path.exists():
            try:
                return json.loads(self.path.read_text())
            except Exception:
                return {}
        return {}

    def save(self):
        self.path.write_text(json.dumps(self.data, indent=2))

    def is_new(self, signal: Signal) -> bool:
        key = f"{signal.symbol}-{signal.entry}"
        return key not in self.data

    def add(self, signal: Signal):
        key = f"{signal.symbol}-{signal.entry}"
        self.data[key] = signal.__dict__
        self.save()


class BybitTrader:
    def __init__(self, api_key: Optional[str], api_secret: Optional[str], dry_run: bool = True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.dry_run = dry_run or not (api_key and api_secret and HTTP)
        self.client = None
        if not self.dry_run and HTTP:
            self.client = HTTP(
                testnet=False,
                api_key=api_key,
                api_secret=api_secret,
            )

    def ensure_symbol(self, symbol: str) -> bool:
        # Para simplicidade, assume que symbol já é válido; poderia consultar exchange info.
        return symbol.endswith("USDT")

    def place_trade(self, sig: Signal, size_usdt: float, leverage: float):
        if not self.ensure_symbol(sig.symbol):
            print(f"❌ Símbolo inválido: {sig.symbol}")
            return
        qty = size_usdt / sig.entry / leverage
        print(f"▶️ Abrindo {sig.symbol} @ {sig.entry:.4f}, qty {qty:.4f}, lev {leverage}x, stop={sig.stop}, targets={sig.targets}")
        if self.dry_run:
            print("Dry-run: nenhuma ordem enviada.")
            return
        try:
            # Ordem de mercado de entrada
            self.client.place_order(
                category="linear",
                symbol=sig.symbol,
                side="Buy",
                orderType="Market",
                qty=round(qty, 4),
                timeInForce="IOC",
                leverage=leverage,
            )
            # TPs parciais
            for tgt in sig.targets:
                self.client.place_order(
                    category="linear",
                    symbol=sig.symbol,
                    side="Sell",
                    orderType="Limit",
                    qty=round(qty / max(len(sig.targets), 1), 4),
                    price=round(tgt, 4),
                    reduceOnly=True,
                )
            if sig.stop:
                self.client.set_trading_stop(
                    category="linear",
                    symbol=sig.symbol,
                    stopLoss=round(sig.stop, 4),
                )
        except Exception as e:  # noqa: BLE001
            print(f"❌ Erro ao enviar ordens: {e}")


async def main():
    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    session_name = os.getenv("TELEGRAM_SESSION", "tg_session")
    channel = os.getenv("TELEGRAM_CHANNEL")
    if not api_id or not api_hash or not channel:
        print("❌ Defina TELEGRAM_API_ID, TELEGRAM_API_HASH e TELEGRAM_CHANNEL.")
        return

    listener = TelegramSignalListener(int(api_id), api_hash, session_name, channel)
    parser = SignalParser()
    store = SignalStore(SIGNALS_FILE)

    messages = await listener.fetch_messages(limit=30)
    print(f"ℹ️ Mensagens lidas: {len(messages)}")

    new_signals = []
    for msg in messages:
        sig = parser.parse(msg)
        if sig and store.is_new(sig):
            store.add(sig)
            new_signals.append(sig)

    if not new_signals:
        print("Sem novos sinais.")
        return

    trader = BybitTrader(
        api_key=os.getenv("BYBIT_API_KEY"),
        api_secret=os.getenv("BYBIT_API_SECRET"),
        dry_run=os.getenv("BYBIT_DRY_RUN", "true").lower() != "false",
    )
    size_usdt = float(os.getenv("POSITION_SIZE_USDT", "50"))
    default_lev = float(os.getenv("DEFAULT_LEVERAGE", "10"))

    for sig in new_signals:
        lev = sig.leverage or default_lev
        trader.place_trade(sig, size_usdt=size_usdt, leverage=lev)


if __name__ == "__main__":
    asyncio.run(main())
