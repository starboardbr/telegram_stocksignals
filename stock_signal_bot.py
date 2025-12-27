#!/usr/bin/env python3
"""
STOCK SIGNAL BOT - Identificador de oportunidades de compra em ações dos EUA.
Baseado no mesmo fluxo do bot de cripto: EMA/RSI/MACD + suporte/resistência.
"""

import json
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import yfinance as yf


@dataclass
class StockSignalBot:
    interval: str = "1d"
    last_run_at: str | None = None
    pairs: Dict[str, List[str]] = field(default_factory=dict)
    last_analyses: List[Dict] = field(default_factory=list)
    custom_tickers: List[str] = field(default_factory=list)
    region: str = "all"  # "all", "us", "eu"

    def __post_init__(self):
        if not self.pairs:
            # ~50 ações mais negociadas/mega caps nos EUA
            self.pairs = {
                "MEGA_CAP": ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "TSLA", "BRK-B", "V", "MA"],
                "FINANCE": ["JPM", "BAC", "WFC", "C", "GS", "MS", "USB", "PNC", "SCHW"],
                "ENERGY": ["XOM", "CVX", "COP", "SLB"],
                "HEALTHCARE": ["UNH", "JNJ", "ABBV", "PFE", "MRK", "LLY"],
                "CONSUMER": ["WMT", "COST", "PG", "KO", "PEP", "HD", "MCD", "NKE"],
                "INDUSTRIALS": ["CAT", "RTX", "LMT", "BA", "GE", "UNP"],
                "TECH_SEMI": ["ORCL", "IBM", "AMD"],
                "COMMS": ["NFLX", "DIS", "CMCSA", "T"],
                # Top Europa (tickers com sufixo de bolsa para yfinance)
                "EUROPE": [
                    "MC.PA",   # LVMH
                    "OR.PA",   # L'Oreal
                    "SAN.PA",  # Sanofi
                    "TTE.PA",  # TotalEnergies
                    "AIR.PA",  # Airbus
                    "ASML.AS", # ASML
                    "SHEL.L",  # Shell
                    "SAP.DE",  # SAP
                    "SIE.DE",  # Siemens
                    "DTE.DE",  # Deutsche Telekom
                    "NOVN.SW", # Novartis
                    "NESN.SW", # Nestle
                    "ROG.SW",  # Roche
                    "ZURN.SW", # Zurich Insurance
                    "HSBA.L",  # HSBC
                    "GSK.L",   # GSK
                    "ULVR.L",  # Unilever
                    "BP.L",    # BP
                    "RIO.L",   # Rio Tinto
                    "AZN.L",   # AstraZeneca
                ],
            }
        if self.region.lower() == "us":
            self.pairs = {k: v for k, v in self.pairs.items() if k != "EUROPE"}
        elif self.region.lower() == "eu":
            self.pairs = {k: v for k, v in self.pairs.items() if k == "EUROPE"}

        self.base_tickers = [t for ts in self.pairs.values() for t in ts]
        self.all_tickers = list(self.base_tickers)

    def get_klines(self, ticker: str, period_days: int = 400) -> pd.DataFrame:
        """Busca candles via yfinance."""
        try:
            df = yf.download(
                tickers=ticker,
                period=f"{period_days}d",
                interval=self.interval,
                progress=False,
            )
            if df.empty:
                return pd.DataFrame()
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [lvl[0] for lvl in df.columns]  # usa o nível Price
            # Garantir colunas no padrão
            expected_cols = ["Open", "High", "Low", "Close", "Volume"]
            df = df[expected_cols]
            df = df.reset_index().rename(
                columns={
                    "Date": "Open Time",
                    "Open": "Open",
                    "High": "High",
                    "Low": "Low",
                    "Close": "Close",
                    "Volume": "Volume",
                }
            )
            return df.sort_values("Open Time").reset_index(drop=True)
        except Exception as e:  # noqa: BLE001
            print(f"❌ Erro ao buscar {ticker}: {e}")
            return pd.DataFrame()

    def calculate_ema(self, df: pd.DataFrame, period: int, col: str = "Close") -> pd.Series:
        return df[col].ewm(span=period, adjust=False).mean()

    def calculate_macd(self, df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9):
        ema_fast = df["Close"].ewm(span=fast, adjust=False).mean()
        ema_slow = df["Close"].ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    def calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        high_low = df["High"] - df["Low"]
        high_close = (df["High"] - df["Close"].shift()).abs()
        low_close = (df["Low"] - df["Close"].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return tr.rolling(window=period).mean()

    def calculate_adx(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        high = df["High"]
        low = df["Low"]
        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm < 0] = 0
        tr = self.calculate_atr(df, period)
        plus_di = 100 * (plus_dm.ewm(alpha=1 / period).mean() / tr)
        minus_di = 100 * (minus_dm.ewm(alpha=1 / period).mean() / tr)
        dx = (abs(plus_di - minus_di) / (plus_di + minus_di)).abs() * 100
        return dx.ewm(alpha=1 / period).mean()

    def calculate_rsi(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        delta = df["Close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    def find_support_resistance(self, df: pd.DataFrame, window: int = 20) -> Tuple[float, float]:
        recent = df.tail(window)
        supports = []
        for i in range(1, len(recent) - 1):
            low = float(recent["Low"].iloc[i])
            prev_low = float(recent["Low"].iloc[i - 1])
            next_low = float(recent["Low"].iloc[i + 1])
            if low < prev_low and low < next_low:
                supports.append(low)
        resistances = []
        for i in range(1, len(recent) - 1):
            high = float(recent["High"].iloc[i])
            prev_high = float(recent["High"].iloc[i - 1])
            next_high = float(recent["High"].iloc[i + 1])
            if high > prev_high and high > next_high:
                resistances.append(high)
        nearest_support = max(supports) if supports else df["Low"].min()
        nearest_resistance = min(resistances) if resistances else df["High"].max()
        return nearest_support, nearest_resistance

    def set_custom_tickers(self, tickers: List[str]):
        cleaned = []
        for t in tickers:
            t = t.strip().upper()
            if t:
                cleaned.append(t)
        self.custom_tickers = list(dict.fromkeys(cleaned))

    def analyze_pair(self, ticker: str) -> Dict | None:
        df = self.get_klines(ticker)
        if df.empty or len(df) < 30:
            return None

        df["EMA20"] = self.calculate_ema(df, 20)
        df["EMA50"] = self.calculate_ema(df, 50)
        df["EMA200"] = self.calculate_ema(df, 200)
        macd, signal, histogram = self.calculate_macd(df)
        df["MACD"] = macd
        df["Signal"] = signal
        df["Histogram"] = histogram
        df["RSI"] = self.calculate_rsi(df, 14)
        df["ATR"] = self.calculate_atr(df, 14)
        df["ADX"] = self.calculate_adx(df, 14)

        current = df.iloc[-1]
        previous = df.iloc[-2]
        support, resistance = self.find_support_resistance(df, window=30)
        avg_volume_raw = df["Volume"].tail(20).mean()
        avg_volume = float(avg_volume_raw) if not pd.isna(avg_volume_raw) else 0.0
        current_volume = float(current["Volume"])
        volume_increase = ((current_volume / avg_volume) - 1) * 100 if avg_volume else 0

        in_uptrend = current["Close"] > current["EMA200"]
        ema_order = current["EMA20"] > current["EMA50"] > current["EMA200"]
        macd_positive = current["MACD"] > current["Signal"]
        macd_crossover = previous["MACD"] < previous["Signal"] and macd_positive
        rsi = current["RSI"]
        rsi_oversold = rsi < 30
        rsi_gaining = current["RSI"] > df["RSI"].iloc[-5]
        testing_support = (current["Low"] <= support * 1.005) and (current["Close"] > support)

        entry_price = current["Close"]
        atr = float(current.get("ATR", 0))
        stop_by_atr = entry_price - 1.5 * atr if atr > 0 else support * 0.99
        stop_loss = min(stop_by_atr, support * 0.99)
        if stop_loss <= 0 or stop_loss >= entry_price:
            stop_loss = entry_price * 0.98
        tp1 = entry_price + 2 * atr if atr > 0 else resistance * 0.98
        tp2 = entry_price + 3 * atr if atr > 0 else resistance
        risk = entry_price - stop_loss
        reward_tp1 = tp1 - entry_price
        reward_tp2 = tp2 - entry_price
        ratio_tp1 = reward_tp1 / risk if risk > 0 else 0
        ratio_tp2 = reward_tp2 / risk if risk > 0 else 0

        confidence_score = 0
        adx = current.get("ADX", 0)
        if in_uptrend:
            confidence_score += 20
        if ema_order:
            confidence_score += 15
        if macd_positive:
            confidence_score += 15
        if macd_crossover:
            confidence_score += 10
        if 30 < rsi < 80:
            confidence_score += 10
        if rsi_gaining:
            confidence_score += 10
        if testing_support:
            confidence_score += 10
        if volume_increase > 30:
            confidence_score += 5
        if volume_increase < -30:
            confidence_score -= 5
        if adx >= 25:
            confidence_score += 10
        elif adx < 15:
            confidence_score -= 5
        if ratio_tp1 >= 1.0:
            confidence_score += 5

        signal_strength = "FORTE" if confidence_score >= 75 else "MODERADO" if confidence_score >= 60 else "FRACO"

        return {
            "symbol": ticker,
            "timeframe": self.interval,
            "price": current["Close"],
            "ema200": current["EMA200"],
            "ema50": current["EMA50"],
            "ema20": current["EMA20"],
            "macd": current["MACD"],
            "signal_line": current["Signal"],
            "rsi": current["RSI"],
            "support": support,
            "resistance": resistance,
            "volume_increase": volume_increase,
            "atr": atr,
            "adx": adx,
            "in_uptrend": in_uptrend,
            "ema_order": ema_order,
            "macd_positive": macd_positive,
            "macd_crossover": macd_crossover,
            "rsi_oversold": rsi_oversold,
            "rsi_gaining": rsi_gaining,
            "testing_support": testing_support,
            "entry": entry_price,
            "stop_loss": stop_loss,
            "tp1": tp1,
            "tp2": tp2,
            "risk": risk,
            "reward_tp1": reward_tp1,
            "reward_tp2": reward_tp2,
            "ratio_tp1": ratio_tp1,
            "ratio_tp2": ratio_tp2,
            "confidence": confidence_score,
            "signal_strength": signal_strength,
            "should_alert": confidence_score >= 70 and ratio_tp1 >= 1.0 and in_uptrend,
        }

    def scan_all_pairs(self, verbose: bool = True) -> List[Dict]:
        signals: List[Dict] = []
        analyses: List[Dict] = []

        pairs_dict = dict(self.pairs)
        if self.custom_tickers:
            pairs_dict["CUSTOM"] = self.custom_tickers
        self.all_tickers = [t for ts in pairs_dict.values() for t in ts]

        if verbose:
            print("\n🔍 Escaneando ações dos EUA...")
            print("=" * 80)
            print(f"Total de tickers a analisar: {len(self.all_tickers)}")
            print("=" * 80 + "\n")

        for category, tickers in pairs_dict.items():
            if verbose:
                print(f"📂 {category} ({len(tickers)} tickers)")
                print("-" * 80)
            for ticker in tickers:
                analysis = self.analyze_pair(ticker)
                if analysis:
                    analyses.append(analysis)
                    if analysis["should_alert"]:
                        signals.append(analysis)
                        if verbose:
                            print(
                                f"  ✅ {ticker:8} → Sinal! Conf {analysis['confidence']}/100 | "
                                f"RSI {analysis['rsi']:.1f} | "
                                f"{'MACD+' if analysis['macd_positive'] else 'MACD-'}"
                                f"{' (x↑)' if analysis['macd_crossover'] else ''} | "
                                f"EMA {'20>50>200' if analysis['ema_order'] else 'mista'} | "
                                f"Vol {analysis['volume_increase']:+.0f}%"
                            )
                    else:
                        if verbose:
                            print(
                                f"  ⏳ {ticker:8} → Sem sinal (Conf {analysis['confidence']}/100) "
                                f"[RSI {analysis['rsi']:.1f} | "
                                f"{'MACD+' if analysis['macd_positive'] else 'MACD-'}"
                                f"{' (x↑)' if analysis['macd_crossover'] else ''} | "
                                f"EMA {'20>50>200' if analysis['ema_order'] else 'mista'} | "
                                f"Vol {analysis['volume_increase']:+.0f}%]"
                            )
                else:
                    if verbose:
                        print(f"  ❌ {ticker:8} → Erro ao buscar dados")
            if verbose:
                print()

        self.last_analyses = analyses
        return signals

    def print_analysis_summary(self):
        analyses = self.last_analyses
        if not analyses:
            print("\n⚠️  Sem dados suficientes para resumo.")
            return

        total = len(analyses)
        signals_count = sum(1 for a in analyses if a["should_alert"])
        avg_conf = sum(a["confidence"] for a in analyses) / total
        uptrend = sum(1 for a in analyses if a["in_uptrend"])
        oversold = sum(1 for a in analyses if a["rsi_oversold"])
        macd_pos = sum(1 for a in analyses if a["macd_positive"])

        print("\n" + "=" * 80)
        print("📊 RESUMO DO MERCADO DE AÇÕES")
        print("=" * 80)
        print(f"Atualizado em: {self.last_run_at} | Timeframe: {self.interval}")
        print(f"Total: {total} | Sinais fortes: {signals_count} | Confiança média: {avg_conf:.0f}/100")
        print(f"Alta (EMA200): {uptrend}/{total} | RSI<30: {oversold}/{total} | MACD+: {macd_pos}/{total}")

        watchlist = [a for a in analyses if 50 <= a["confidence"] < 75]
        watchlist.sort(key=lambda x: x["confidence"], reverse=True)
        if watchlist:
            print("\n👀 TICKERS PARA MONITORAR (score 50-74)")
            for a in watchlist[:8]:
                print(
                    f"- {a['symbol']}: Conf {a['confidence']}/100 | "
                    f"RSI {a['rsi']:.1f} | "
                    f"{'MACD+' if a['macd_positive'] else 'MACD-'}"
                    f"{' (x↑)' if a['macd_crossover'] else ''} | "
                    f"EMA {'20>50>200' if a['ema_order'] else 'mista'} | "
                    f"Vol {a['volume_increase']:+.0f}%"
                )
        print("=" * 80)

    def print_signal(self, analysis: Dict):
        print("\n" + "=" * 70)
        print(f"🚀 SINAL DE COMPRA - {analysis['symbol']}")
        print("=" * 70)
        print(f"  Timeframe: {analysis.get('timeframe', self.interval)} | Atualizado: {self.last_run_at}")
        print(f"  Preço: ${analysis['price']:.2f}")
        print(f"  EMA200: ${analysis['ema200']:.2f} {'✓' if analysis['in_uptrend'] else '✗'}")
        print(f"  EMA50: ${analysis['ema50']:.2f}")
        print(f"  EMA20: ${analysis['ema20']:.2f}")
        print(f"  RSI: {analysis['rsi']:.1f}")
        print(f"  MACD: {'POSITIVO ✓' if analysis['macd_positive'] else 'NEGATIVO'}")
        if analysis["macd_crossover"]:
            print("  └─ MACD CRUZANDO PARA CIMA ⚡")
        print(f"  Volume: {analysis['volume_increase']:+.1f}% vs média")
        print(f"\n🎯 ESTRUTURA DE PREÇO:")
        print(f"  Resistência: ${analysis['resistance']:.2f}")
        print(f"  Suporte Testado: ${analysis['support']:.2f} {'← SENDO TESTADO' if analysis['testing_support'] else ''}")
        print(f"\n💰 RECOMENDAÇÃO:")
        print(f"  Entrada: ${analysis['entry']:.2f}")
        print(f"  Stop Loss: ${analysis['stop_loss']:.2f}")
        print(f"  TP 1: ${analysis['tp1']:.2f} (R/R: 1:{analysis['ratio_tp1']:.2f})")
        print(f"  TP 2: ${analysis['tp2']:.2f} (R/R: 1:{analysis['ratio_tp2']:.2f})")
        print(f"\n⚡ CONFIANÇA: {analysis['confidence']}/100 - {analysis['signal_strength']}")
        print("=" * 70)

    def run(self) -> List[Dict]:
        self.last_run_at = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M:%S UTC")
        signals = self.scan_all_pairs()
        self.print_analysis_summary()

        if signals:
            print("\n" + "=" * 60)
            print(f"🎯 {len(signals)} SINAIS IDENTIFICADOS!\n")
            for sig in signals:
                self.print_signal(sig)
            print("=" * 60)
        else:
            print("\n" + "=" * 60)
            print("❌ Nenhum sinal identificado no momento")
            print("=" * 60)
        return signals


if __name__ == "__main__":
    bot = StockSignalBot()
    signals = bot.run()
    if signals:
        payload = []
        for s in signals:
            s_copy = s.copy()
            s_copy["generated_at"] = bot.last_run_at
            payload.append({k: v for k, v in s_copy.items() if not isinstance(v, (np.ndarray, pd.Series))})
        with open("stock_signals.json", "w") as f:
            json.dump(payload, f, indent=2)
        print("\n💾 Sinais de ações salvos em stock_signals.json")
