#!/usr/bin/env python3
"""
CRYPTO SIGNAL BOT - Identificador de Oportunidades de Compra
Autor: Thiago
Descrição: Bot que monitora múltiplos pares de crypto e identifica sinais
de compra em tendência de alta com suportes/resistências e risco/retorno.
"""

import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import requests


class CryptoSignalBot:
    def __init__(self):
        """Inicializa o bot com configurações padrão."""
        self.base_url = "https://api.binance.com/api/v3"
        self.session = requests.Session()
        self.last_analyses: List[Dict] = []
        self.interval = "1d"
        self.last_run_at = None
        self.custom_pairs: List[str] = []
        # PARES ORGANIZADOS POR CATEGORIA
        # Lista de 30 criptos priorizadas
        self.pairs = {
            "BLUE_CHIPS": ["BTC", "ETH", "BNB", "SOL", "AVAX", "ADA", "DOT"],
            "LAYER2": ["MATIC", "ARB", "OP"],
            "DEFI": ["LINK", "UNI", "AAVE", "MKR"],
            "INFRA": ["ATOM", "NEAR", "ALGO", "FIL", "ICP", "THETA"],
            "EXPANSAO": ["STX", "RNDR", "FET", "IMX", "GRT"],  # STX no lugar de KAS (não listado na Binance)
            "TRADING": ["LDO", "INJ", "TIA", "AR", "TON"],
        }
        # Flat list base (sem custom)
        self.base_pairs_flat = [pair for pairs in self.pairs.values() for pair in pairs]
        self.all_pairs = list(self.base_pairs_flat)
        self.usdt_suffix = "USDT"

    def get_klines(self, symbol: str, interval: str = "1d", limit: int = 200) -> pd.DataFrame:
        """
        Busca candles históricos da Binance.

        Args:
            symbol: Par (ex: 'BTCUSDT')
            interval: Timeframe ('1d', '4h', '1h')
            limit: Número de candles

        Returns:
            DataFrame com OHLCV data
        """
        endpoint = f"{self.base_url}/klines"
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        last_err = None
        for attempt in range(3):
            try:
                response = self.session.get(endpoint, params=params, timeout=10)
                response.raise_for_status()
                data = response.json()
                df = pd.DataFrame(
                    data,
                    columns=[
                        "Open Time",
                        "Open",
                        "High",
                        "Low",
                        "Close",
                        "Volume",
                        "Close Time",
                        "Quote Volume",
                        "Trades",
                        "Taker Buy Base",
                        "Taker Buy Quote",
                        "Ignore",
                    ],
                )
                df["Open"] = df["Open"].astype(float)
                df["High"] = df["High"].astype(float)
                df["Low"] = df["Low"].astype(float)
                df["Close"] = df["Close"].astype(float)
                df["Volume"] = df["Volume"].astype(float)
                df["Open Time"] = pd.to_datetime(df["Open Time"], unit="ms")
                return df.sort_values("Open Time").reset_index(drop=True)
            except requests.HTTPError as e:
                status = e.response.status_code if e.response else "http"
                last_err = f"HTTP {status}"
            except Exception as e:  # noqa: BLE001
                last_err = str(e)
            time.sleep(1 + attempt)
        print(f"❌ Erro ao buscar {symbol}: {last_err}")
        return pd.DataFrame()

    def calculate_ema(self, df: pd.DataFrame, period: int, col: str = "Close") -> pd.Series:
        """Calcula Média Móvel Exponencial."""
        return df[col].ewm(span=period, adjust=False).mean()

    def calculate_macd(self, df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9):
        """Calcula MACD e Signal Line."""
        ema_fast = df["Close"].ewm(span=fast, adjust=False).mean()
        ema_slow = df["Close"].ewm(span=slow, adjust=False).mean()

        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line

        return macd_line, signal_line, histogram

    def calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Average True Range."""
        high_low = df["High"] - df["Low"]
        high_close = (df["High"] - df["Close"].shift()).abs()
        low_close = (df["Low"] - df["Close"].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return tr.rolling(window=period).mean()

    def calculate_adx(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """ADX simples."""
        high = df["High"]
        low = df["Low"]
        close = df["Close"]
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
        """Calcula RSI (Relative Strength Index)."""
        delta = df["Close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def find_support_resistance(self, df: pd.DataFrame, window: int = 20) -> Tuple[float, float]:
        """
        Identifica suportes e resistências usando pontos de pivô.

        Returns:
            (suporte_próximo, resistência_próxima)
        """
        recent = df.tail(window)

        # Suportes (mínimos locais)
        supports = []
        for i in range(1, len(recent) - 1):
            if recent.iloc[i]["Low"] < recent.iloc[i - 1]["Low"] and recent.iloc[i]["Low"] < recent.iloc[i + 1]["Low"]:
                supports.append(recent.iloc[i]["Low"])

        # Resistências (máximos locais)
        resistances = []
        for i in range(1, len(recent) - 1):
            if recent.iloc[i]["High"] > recent.iloc[i - 1]["High"] and recent.iloc[i]["High"] > recent.iloc[i + 1]["High"]:
                resistances.append(recent.iloc[i]["High"])

        # Retorna mais próximos
        nearest_support = max(supports) if supports else df["Low"].min()
        nearest_resistance = min(resistances) if resistances else df["High"].max()

        return nearest_support, nearest_resistance

    def set_custom_pairs(self, pairs: List[str]):
        """Define pares customizados (lista de bases ex.: ['ABC', 'DEF'])."""
        cleaned = []
        for p in pairs:
            p = p.strip().upper()
            if p:
                cleaned.append(p)
        self.custom_pairs = list(dict.fromkeys(cleaned))  # remove duplicados preservando ordem

    def analyze_pair(self, symbol: str) -> Dict:
        """
        Análise completa de um par de crypto.

        Returns:
            Dict com análise completa
        """
        # Buscar dados 1d
        df_1d = self.get_klines(symbol, self.interval, 200)

        if df_1d.empty:
            return None

        # Calcular indicadores
        df_1d["EMA20"] = self.calculate_ema(df_1d, 20)
        df_1d["EMA50"] = self.calculate_ema(df_1d, 50)
        df_1d["EMA200"] = self.calculate_ema(df_1d, 200)

        macd, signal, histogram = self.calculate_macd(df_1d)
        df_1d["MACD"] = macd
        df_1d["Signal"] = signal
        df_1d["Histogram"] = histogram

        df_1d["ATR"] = self.calculate_atr(df_1d, 14)
        df_1d["ADX"] = self.calculate_adx(df_1d, 14)
        df_1d["RSI"] = self.calculate_rsi(df_1d, 14)

        # Dados atuais
        current = df_1d.iloc[-1]
        previous = df_1d.iloc[-2]

        # Suportes e resistências
        support, resistance = self.find_support_resistance(df_1d, window=30)

        # Calcular volume médio
        avg_volume = df_1d["Volume"].tail(20).mean()
        current_volume = current["Volume"]
        volume_increase = (current_volume / avg_volume - 1) * 100

        # Análise técnica
        in_uptrend = current["Close"] > current["EMA200"]
        ema_order = current["EMA20"] > current["EMA50"] > current["EMA200"]
        macd_positive = current["MACD"] > current["Signal"]
        macd_crossover = previous["MACD"] < previous["Signal"] and macd_positive
        rsi = current["RSI"]
        rsi_healthy = 30 < rsi < 80
        rsi_oversold = rsi < 30
        rsi_gaining = current["RSI"] > df_1d["RSI"].iloc[-5]

        # Teste de suporte
        testing_support = (current["Low"] <= support * 1.005) and (current["Close"] > support)

        # Cálculo de risco/retorno
        entry_price = current["Close"]
        atr = float(current.get("ATR", 0))
        # Stops/TPs baseados em ATR com piso no suporte
        stop_by_atr = entry_price - 1.5 * atr if atr > 0 else support * 0.99
        stop_loss = min(stop_by_atr, support * 0.99)
        if stop_loss <= 0 or stop_loss >= entry_price:
            stop_loss = entry_price * 0.98  # fallback
        tp1 = entry_price + 2 * atr if atr > 0 else resistance * 0.98
        tp2 = entry_price + 3 * atr if atr > 0 else resistance

        risk = entry_price - stop_loss
        reward_tp1 = tp1 - entry_price
        reward_tp2 = tp2 - entry_price

        ratio_tp1 = reward_tp1 / risk if risk > 0 else 0
        ratio_tp2 = reward_tp2 / risk if risk > 0 else 0

        # Score de confiança
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
        if rsi_healthy:
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

        # Determinar sinal
        signal_strength = "FORTE" if confidence_score >= 75 else "MODERADO" if confidence_score >= 60 else "FRACO"

        return {
            "symbol": symbol,
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
            # Condições
            "in_uptrend": in_uptrend,
            "ema_order": ema_order,
            "macd_positive": macd_positive,
            "macd_crossover": macd_crossover,
            "rsi_healthy": rsi_healthy,
            "rsi_oversold": rsi_oversold,
            "rsi_gaining": rsi_gaining,
            "testing_support": testing_support,
            # Risco/Retorno
            "entry": entry_price,
            "stop_loss": stop_loss,
            "tp1": tp1,
            "tp2": tp2,
            "risk": risk,
            "reward_tp1": reward_tp1,
            "reward_tp2": reward_tp2,
            "ratio_tp1": ratio_tp1,
            "ratio_tp2": ratio_tp2,
            # Score
            "confidence": confidence_score,
            "signal_strength": signal_strength,
            "should_alert": confidence_score >= 70 and ratio_tp1 >= 1.0 and in_uptrend,
        }

    def scan_all_pairs(self, verbose: bool = True) -> List[Dict]:
        """Escaneia todos os pares por categoria e retorna os com sinal."""
        signals = []
        analyses: List[Dict] = []

        # Mescla pares base com customizados, agrupando custom em categoria própria
        pairs_dict = dict(self.pairs)
        if self.custom_pairs:
            pairs_dict["CUSTOM"] = self.custom_pairs
        # Atualiza lista flat
        self.all_pairs = [p for plist in pairs_dict.values() for p in plist]

        if verbose:
            print("\n🔍 Escaneando pares de crypto...")
            print("=" * 80)
            print(f"Total de pares a analisar: {len(self.all_pairs)}")
            print("=" * 80 + "\n")

        for category, category_pairs in pairs_dict.items():
            if verbose:
                print(f"📂 {category.upper()} ({len(category_pairs)} pares)")
                print("-" * 80)

            for pair_base in category_pairs:
                symbol = f"{pair_base}{self.usdt_suffix}"
                analysis = self.analyze_pair(symbol)

                if analysis:
                    analyses.append(analysis)
                    if analysis["should_alert"]:
                        signals.append(analysis)
                        if verbose:
                            print(f"  ✅ {symbol:12} → Sinal identificado! (Confiança: {analysis['confidence']}/100)")
                            print(
                                f"     Indicadores: RSI {analysis['rsi']:.1f} | "
                                f"{'MACD+' if analysis['macd_positive'] else 'MACD-'}"
                                f"{' (crossover ↑)' if analysis['macd_crossover'] else ''} | "
                                f"EMA {'20>50>200' if analysis['ema_order'] else 'mista'} | "
                                f"Vol {analysis['volume_increase']:+.0f}% | "
                                f"Suporte {analysis['support']:.2f} / Resistência {analysis['resistance']:.2f}"
                            )
                    else:
                        if verbose:
                            print(
                                f"  ⏳ {symbol:12} → Sem sinal (Confiança: {analysis['confidence']}/100)  "
                                f"[RSI {analysis['rsi']:.1f} | "
                                f"{'MACD+' if analysis['macd_positive'] else 'MACD-'}"
                                f"{' (crossover ↑)' if analysis['macd_crossover'] else ''} | "
                                f"EMA {'20>50>200' if analysis['ema_order'] else 'mista'} | "
                                f"Vol {analysis['volume_increase']:+.0f}%]"
                            )
                else:
                    if verbose:
                        print(f"  ❌ {symbol:12} → Erro ao buscar dados")

            if verbose:
                print()

        self.last_analyses = analyses
        return signals

    def print_signal(self, analysis: Dict):
        """Imprime um sinal de forma legível."""
        print("\n" + "=" * 70)
        print(f"🚀 SINAL DE COMPRA - {analysis['symbol']}")
        print("=" * 70)

        print(f"\n📊 SITUAÇÃO ATUAL:")
        print(f"  Timeframe: {analysis.get('timeframe', self.interval)}")
        print(f"  Preço: ${analysis['price']:.2f}")
        print(f"  EMA200: ${analysis['ema200']:.2f} {'✓' if analysis['in_uptrend'] else '✗'}")
        print(f"  EMA50: ${analysis['ema50']:.2f}")
        print(f"  EMA20: ${analysis['ema20']:.2f}")
        print(f"  RSI: {analysis['rsi']:.1f}")
        print(f"  MACD: {'POSITIVO ✓' if analysis['macd_positive'] else 'NEGATIVO'}")
        if analysis["macd_crossover"]:
            print("  └─ MACD CRUZANDO PARA CIMA ⚡")
        print(f"  Volume: +{analysis['volume_increase']:.1f}%")

        print(f"\n🎯 ESTRUTURA DE PREÇO:")
        print(f"  Resistência: ${analysis['resistance']:.2f}")
        print(f"  Suporte Testado: ${analysis['support']:.2f} {'← SENDO TESTADO' if analysis['testing_support'] else ''}")

        print(f"\n💰 RECOMENDAÇÃO:")
        print(f"  Entrada: ${analysis['entry']:.2f}")
        print(f"  Stop Loss: ${analysis['stop_loss']:.2f}")
        print(f"  TP 1: ${analysis['tp1']:.2f} (Risco/Retorno: 1:{analysis['ratio_tp1']:.2f})")
        print(f"  TP 2: ${analysis['tp2']:.2f} (Risco/Retorno: 1:{analysis['ratio_tp2']:.2f})")

        print(f"\n⚡ CONFIANÇA: {analysis['confidence']}/100 - {analysis['signal_strength']}")
        print("=" * 70)

    def print_analysis_summary(self):
        """Resumo geral do mercado com métricas-chave."""
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
        print("📊 RESUMO DO MERCADO")
        print("=" * 80)
        print(
            f"Atualizado em: {self.last_run_at} | Timeframe: {self.interval}"
        )
        print(
            f"Total pares: {total} | Sinais fortes: {signals_count} | Confiança média: {avg_conf:.0f}/100"
        )
        print(
            f"Em tendência de alta: {uptrend}/{total} | "
            f"RSI<30: {oversold}/{total} | MACD+: {macd_pos}/{total}"
        )

        # Top para monitorar
        watchlist = [a for a in analyses if 50 <= a["confidence"] < 75]
        watchlist.sort(key=lambda x: x["confidence"], reverse=True)
        if watchlist:
            print("\n👀 PARES PARA MONITORAR (score 50-74)")
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

    def run(self, alert_only: bool = True):
        """
        Executa o scanner.

        Args:
            alert_only: Se True, mostra apenas sinais; se False, mostra todas análises
        """
        self.last_run_at = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M:%S UTC")
        signals = self.scan_all_pairs()

        # Resumo geral com indicadores agregados
        self.print_analysis_summary()

        print("\n" + "=" * 60)
        if signals:
            print(f"🎯 {len(signals)} SINAIS IDENTIFICADOS!\n")
            for signal in signals:
                self.print_signal(signal)
        else:
            print("❌ Nenhum sinal identificado no momento")
        print("=" * 60)

        return signals


if __name__ == "__main__":
    bot = CryptoSignalBot()
    signals = bot.run()

    # Salvar resultados em JSON dentro do workspace
    if signals:
        with open("signals.json", "w") as f:
            # Converter para JSON-serializable
            signals_json = []
            for s in signals:
                s_copy = s.copy()
                s_copy["timeframe"] = s_copy.get("timeframe", bot.interval)
                s_copy["generated_at"] = bot.last_run_at
                signals_json.append({k: v for k, v in s_copy.items() if not isinstance(v, (np.ndarray, pd.Series))})
            json.dump(signals_json, f, indent=2)
        print("\n💾 Sinais salvos em signals.json")
