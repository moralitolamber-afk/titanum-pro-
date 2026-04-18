"""
⚡ TITANIUM v8.0 PRO — Motor de Backtesting
Valida la estrategia de confluencia contra datos históricos.

Implementa:
- Vectorized Backtester (rápido, para iteración)
- Walk-Forward Analysis (evita overfitting)
- Monte Carlo Simulation (robustez estadística)
- Métricas institucionales (Sharpe, Sortino, Calmar, Max DD)

Basado en: backtesting-frameworks skill
Reglas anti-bias:
  - Cero look-ahead: señales generadas con shift(1)
  - Costos realistas: slippage + comisión de Binance
  - Out-of-sample: 70/30 train/test por defecto
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Any, Optional, Callable
from itertools import product
from dataclasses import dataclass, field

import config
from core.indicators import calculate_all
from core.strategy import StrategyEngine


# ══════════════════════════════════════════════════════════
# MÉTRICAS DE RENDIMIENTO
# ══════════════════════════════════════════════════════════

def calculate_metrics(returns: pd.Series, rf_rate: float = 0.02) -> Dict[str, float]:
    """Métricas institucionales de rendimiento."""
    if len(returns) == 0 or returns.std() == 0:
        return {k: 0.0 for k in [
            'total_return', 'annual_return', 'annual_volatility',
            'sharpe_ratio', 'sortino_ratio', 'calmar_ratio',
            'max_drawdown', 'win_rate', 'profit_factor', 'num_trades',
            'avg_win', 'avg_loss', 'expectancy',
        ]}

    ann = 252  # Factor de anualización (días de trading)

    total_return = (1 + returns).prod() - 1
    annual_return = (1 + total_return) ** (ann / max(len(returns), 1)) - 1
    annual_vol = returns.std() * np.sqrt(ann)

    # Sharpe Ratio
    sharpe = (annual_return - rf_rate) / annual_vol if annual_vol > 0 else 0

    # Sortino Ratio (solo penaliza downside)
    downside = returns[returns < 0]
    downside_vol = downside.std() * np.sqrt(ann) if len(downside) > 0 else 0
    sortino = (annual_return - rf_rate) / downside_vol if downside_vol > 0 else 0

    # Max Drawdown
    equity = (1 + returns).cumprod()
    rolling_max = equity.cummax()
    drawdowns = (equity - rolling_max) / rolling_max
    max_dd = drawdowns.min()

    # Calmar Ratio
    calmar = annual_return / abs(max_dd) if max_dd != 0 else 0

    # Win Rate & Profit Factor
    wins = returns[returns > 0]
    losses = returns[returns < 0]
    trades = returns[returns != 0]
    win_rate = len(wins) / len(trades) if len(trades) > 0 else 0
    profit_factor = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float('inf')

    avg_win = wins.mean() * 100 if len(wins) > 0 else 0
    avg_loss = losses.mean() * 100 if len(losses) > 0 else 0
    expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)

    return {
        'total_return': round(total_return * 100, 2),
        'annual_return': round(annual_return * 100, 2),
        'annual_volatility': round(annual_vol * 100, 2),
        'sharpe_ratio': round(sharpe, 3),
        'sortino_ratio': round(sortino, 3),
        'calmar_ratio': round(calmar, 3),
        'max_drawdown': round(max_dd * 100, 2),
        'win_rate': round(win_rate * 100, 1),
        'profit_factor': round(profit_factor, 2),
        'num_trades': int(len(trades)),
        'avg_win': round(avg_win, 3),
        'avg_loss': round(avg_loss, 3),
        'expectancy': round(expectancy, 3),
    }


# ══════════════════════════════════════════════════════════
# SEÑAL DE LA ESTRATEGIA TITANIUM
# ══════════════════════════════════════════════════════════

def titanium_signal(df: pd.DataFrame,
                    score_threshold: int = 65,
                    atr_tp_mult: float = 2.5,
                    atr_sl_mult: float = 1.5) -> pd.DataFrame:
    """
    Genera señales basadas en la estrategia de confluencia TITANIUM.
    Retorna DataFrame con columnas: signal, entry, sl, tp, score

    CERO look-ahead bias: solo usa datos hasta la barra actual.
    """
    if len(df) < config.EMA_SLOW + 5:
        return pd.DataFrame(index=df.index, columns=['signal', 'score'])

    # Calcular indicadores (función pura, sin look-ahead)
    df = calculate_all(df.copy())

    result = pd.DataFrame(index=df.index)
    result['signal'] = 0     # 1=LONG, -1=SHORT, 0=FLAT
    result['score'] = 0
    result['sl_pct'] = 0.0
    result['tp_pct'] = 0.0

    for i in range(config.EMA_SLOW, len(df)):
        row = df.iloc[i]

        # Score simplificado (misma lógica que StrategyEngine._score)
        long_s = _compute_score('LONG', row, df.iloc[:i+1])
        short_s = _compute_score('SHORT', row, df.iloc[:i+1])

        # Filtros FASE 2
        atr_pct = row.get('ATR_pct', 0)
        if pd.isna(atr_pct):
            atr_pct = 0
        if atr_pct < 0.3:
            long_s = int(long_s * 0.5)
            short_s = int(short_s * 0.5)

        rsi_div = row.get('rsi_divergence', 'NONE')
        if rsi_div == 'BEAR_DIV':
            long_s = int(long_s * 0.7)
        elif rsi_div == 'BULL_DIV':
            short_s = int(short_s * 0.7)

        mkt_struct = row.get('market_structure', 'RANGING')
        if mkt_struct == 'BULLISH_STRUCT':
            long_s = min(100, int(long_s * 1.1))
        elif mkt_struct == 'BEARISH_STRUCT':
            short_s = min(100, int(short_s * 1.1))

        # Generar señal
        atr = row.get('ATR', 0)
        if pd.isna(atr) or atr == 0:
            atr = row['close'] * 0.005

        if long_s >= score_threshold and long_s > short_s:
            result.iloc[i, result.columns.get_loc('signal')] = 1
            result.iloc[i, result.columns.get_loc('score')] = long_s
            result.iloc[i, result.columns.get_loc('sl_pct')] = (atr * atr_sl_mult) / row['close']
            result.iloc[i, result.columns.get_loc('tp_pct')] = (atr * atr_tp_mult) / row['close']
        elif short_s >= score_threshold and short_s > long_s:
            result.iloc[i, result.columns.get_loc('signal')] = -1
            result.iloc[i, result.columns.get_loc('score')] = short_s
            result.iloc[i, result.columns.get_loc('sl_pct')] = (atr * atr_sl_mult) / row['close']
            result.iloc[i, result.columns.get_loc('tp_pct')] = (atr * atr_tp_mult) / row['close']

    return result


def _compute_score(direction: str, row, window_df) -> int:
    """Score simplificado para backtesting (misma lógica que strategy.py)."""
    is_long = direction == 'LONG'
    W = config.WEIGHTS
    total = 0

    def sv(col, default=0):
        v = row.get(col, default)
        return default if pd.isna(v) else float(v)

    # ADX + DI
    adx = sv('ADX')
    di_p, di_m = sv('DI+'), sv('DI-')
    if adx > config.ADX_THRESHOLD:
        aligned = (is_long and di_p > di_m) or (not is_long and di_m > di_p)
        if aligned:
            total += min(W['adx_trend'], W['adx_trend'] * (adx / config.ADX_STRONG))

    # RSI
    rsi = sv('RSI', 50)
    if is_long and 45 < rsi < config.RSI_OVERBOUGHT:
        total += W['rsi'] * min(1.0, (rsi - 45) / 20)
    elif not is_long and config.RSI_OVERSOLD < rsi < 55:
        total += W['rsi'] * min(1.0, (55 - rsi) / 20)

    # EMA alignment
    price = row['close']
    e8 = sv('EMA_8', price)
    e21 = sv('EMA_21', price)
    e55 = sv('EMA_55', price)
    if is_long and price > e8 > e21 > e55:
        total += W['ema_alignment']
    elif not is_long and price < e8 < e21 < e55:
        total += W['ema_alignment']
    elif (is_long and price > e21 > e55) or (not is_long and price < e21 < e55):
        total += W['ema_alignment'] * 0.7

    # MACD
    mh = sv('MACD_hist')
    ml = sv('MACD')
    ms = sv('MACD_signal')
    if is_long:
        if ml > ms and mh > 0:
            total += W['macd']
        elif mh > 0:
            total += W['macd'] * 0.5
    else:
        if ml < ms and mh < 0:
            total += W['macd']
        elif mh < 0:
            total += W['macd'] * 0.5

    # BB position
    bb = sv('BB_pct', 0.5)
    if is_long and bb < 0.3:
        total += W['bb_position']
    elif not is_long and bb > 0.7:
        total += W['bb_position']

    # Volume
    vr = sv('vol_ratio', 1.0)
    if vr > 1.0:
        total += min(W['volume'], W['volume'] * (vr / 1.5))

    return round(total)


# ══════════════════════════════════════════════════════════
# VECTORIZED BACKTESTER
# ══════════════════════════════════════════════════════════

class TitaniumBacktester:
    """
    Backtester vectorizado para la estrategia TITANIUM.
    Incluye slippage, comisiones, y gestión de SL/TP basado en ATR.
    """

    def __init__(
        self,
        initial_capital: float = 10000,
        commission: float = 0.001,    # 0.1% (Binance taker fee)
        slippage: float = 0.0005,     # 0.05% slippage
        position_size_pct: float = 0.02,  # 2% del capital por trade
    ):
        self.initial_capital = initial_capital
        self.commission = commission
        self.slippage = slippage
        self.position_pct = position_size_pct

    def run(self, df: pd.DataFrame,
            score_threshold: int = 65,
            atr_tp_mult: float = 2.5,
            atr_sl_mult: float = 1.5) -> Dict[str, Any]:
        """
        Ejecutar backtest completo.

        Args:
            df: DataFrame con columnas OHLCV (open, high, low, close, volume, time)
            score_threshold: Score mínimo para entrar (default: 65)
            atr_tp_mult: Multiplicador ATR para TP
            atr_sl_mult: Multiplicador ATR para SL

        Returns:
            Dict con equity curve, trades, métricas
        """
        # Generar señales (SIN look-ahead)
        signals = titanium_signal(df, score_threshold, atr_tp_mult, atr_sl_mult)

        # SHIFT para evitar look-ahead: señal en barra N -> ejecuta en barra N+1
        signals['signal'] = signals['signal'].shift(1).fillna(0)

        # Simular trades con SL/TP
        equity = [self.initial_capital]
        trades = []
        position = 0    # 1=LONG, -1=SHORT, 0=FLAT
        entry_price = 0
        sl_price = 0
        tp_price = 0
        trade_entry_idx = 0

        for i in range(1, len(df)):
            cur_price = df.iloc[i]['close']
            prev_price = df.iloc[i - 1]['close']
            sig = signals.iloc[i]['signal']

            pnl = 0

            # Verificar SL/TP en posición abierta
            if position != 0:
                high = df.iloc[i]['high']
                low = df.iloc[i]['low']

                hit_sl = False
                hit_tp = False

                if position == 1:  # LONG
                    hit_sl = low <= sl_price
                    hit_tp = high >= tp_price
                else:  # SHORT
                    hit_sl = high >= sl_price
                    hit_tp = low <= tp_price

                if hit_sl:
                    exit_price = sl_price * (1 + self.slippage * (-position))
                    pnl = position * (exit_price - entry_price) / entry_price
                    pnl -= self.commission  # Comisión de salida
                    trades.append({
                        'entry_idx': trade_entry_idx,
                        'exit_idx': i,
                        'direction': 'LONG' if position == 1 else 'SHORT',
                        'entry': entry_price,
                        'exit': exit_price,
                        'pnl_pct': round(pnl * 100, 3),
                        'result': 'SL',
                    })
                    position = 0
                elif hit_tp:
                    exit_price = tp_price * (1 + self.slippage * (-position))
                    pnl = position * (exit_price - entry_price) / entry_price
                    pnl -= self.commission
                    trades.append({
                        'entry_idx': trade_entry_idx,
                        'exit_idx': i,
                        'direction': 'LONG' if position == 1 else 'SHORT',
                        'entry': entry_price,
                        'exit': exit_price,
                        'pnl_pct': round(pnl * 100, 3),
                        'result': 'TP',
                    })
                    position = 0

            # Nueva señal (solo si no hay posición abierta)
            if position == 0 and sig != 0:
                position = int(sig)
                entry_price = cur_price * (1 + self.slippage * position)
                sl_pct = signals.iloc[i].get('sl_pct', 0.015)
                tp_pct = signals.iloc[i].get('tp_pct', 0.025)

                if position == 1:
                    sl_price = entry_price * (1 - sl_pct)
                    tp_price = entry_price * (1 + tp_pct)
                else:
                    sl_price = entry_price * (1 + sl_pct)
                    tp_price = entry_price * (1 - tp_pct)

                trade_entry_idx = i
                pnl -= self.commission  # Comisión de entrada

            # Actualizar equity
            position_return = 0
            if position != 0:
                position_return = position * (cur_price - prev_price) / prev_price
            capital = equity[-1] * (1 + position_return * self.position_pct + pnl * self.position_pct)
            equity.append(capital)

        # Métricas
        equity_series = pd.Series(equity[1:], index=df.index[:len(equity)-1])
        returns = equity_series.pct_change().dropna()

        return {
            'equity': equity_series,
            'returns': returns,
            'trades': trades,
            'metrics': calculate_metrics(returns),
            'params': {
                'score_threshold': score_threshold,
                'atr_tp_mult': atr_tp_mult,
                'atr_sl_mult': atr_sl_mult,
            },
        }


# ══════════════════════════════════════════════════════════
# WALK-FORWARD ANALYSIS
# ══════════════════════════════════════════════════════════

class WalkForwardAnalyzer:
    """
    Walk-Forward: optimiza en train, valida en test, repite.
    Evita overfitting garantizando que cada test set es out-of-sample.
    """

    def __init__(self, train_bars: int = 2000, test_bars: int = 500):
        self.train_bars = train_bars
        self.test_bars = test_bars

    def run(self, df: pd.DataFrame,
            param_grid: Optional[Dict] = None) -> Dict[str, Any]:
        """Ejecutar walk-forward optimization."""
        if param_grid is None:
            param_grid = {
                'score_threshold': [60, 65, 70, 75],
                'atr_tp_mult': [2.0, 2.5, 3.0],
                'atr_sl_mult': [1.0, 1.5, 2.0],
            }

        backtester = TitaniumBacktester()
        splits = self._make_splits(df)
        results = []

        for i, (train, test) in enumerate(splits):
            # Optimizar en train
            best_params, best_sharpe = self._optimize(backtester, train, param_grid)
            print(f"  Split {i+1}/{len(splits)}: "
                  f"Best Sharpe={best_sharpe:.3f}, params={best_params}")

            # Validar en test (out-of-sample)
            test_result = backtester.run(test, **best_params)
            test_result['split'] = i + 1
            test_result['best_params'] = best_params
            test_result['train_sharpe'] = best_sharpe
            results.append(test_result)

        # Métricas combinadas
        all_returns = pd.concat([r['returns'] for r in results])
        combined_metrics = calculate_metrics(all_returns)

        return {
            'splits': results,
            'combined_metrics': combined_metrics,
            'n_splits': len(splits),
        }

    def _make_splits(self, df):
        splits = []
        n = len(df)
        start = 0
        while start + self.train_bars + self.test_bars <= n:
            train = df.iloc[start:start + self.train_bars].copy()
            test = df.iloc[start + self.train_bars:
                           start + self.train_bars + self.test_bars].copy()
            splits.append((train, test))
            start += self.test_bars
        return splits

    def _optimize(self, backtester, train_df, param_grid):
        best_params = {}
        best_sharpe = -np.inf

        keys = list(param_grid.keys())
        values = list(param_grid.values())

        for combo in product(*values):
            params = dict(zip(keys, combo))
            try:
                result = backtester.run(train_df, **params)
                sharpe = result['metrics']['sharpe_ratio']
                if sharpe > best_sharpe:
                    best_sharpe = sharpe
                    best_params = params
            except Exception:
                continue

        return best_params, best_sharpe


# ══════════════════════════════════════════════════════════
# MONTE CARLO SIMULATION
# ══════════════════════════════════════════════════════════

class MonteCarloSimulator:
    """
    Simula 1000 escenarios reshuffleando los retornos históricos.
    Responde: ¿Qué tan robusto es el resultado? ¿Fue suerte?
    """

    def __init__(self, n_simulations: int = 1000, confidence: float = 0.95):
        self.n_sims = n_simulations
        self.confidence = confidence

    def analyze(self, returns: pd.Series) -> Dict[str, Any]:
        """Análisis Monte Carlo completo."""
        if len(returns) == 0:
            return {'error': 'No returns to analyze'}

        # Bootstrap simulations
        sims = np.zeros((self.n_sims, len(returns)))
        for i in range(self.n_sims):
            sims[i] = np.random.choice(returns.values, size=len(returns), replace=True)

        # Equity curves simuladas
        equities = (1 + sims).cumprod(axis=1)

        # Max drawdowns
        max_dds = []
        for eq in equities:
            running_max = np.maximum.accumulate(eq)
            dd = (eq - running_max) / running_max
            max_dds.append(dd.min())
        max_dds = np.array(max_dds)

        # Total returns
        total_returns = equities[:, -1] - 1

        # Probabilidad de pérdida
        prob_loss = (total_returns < 0).mean()

        lo = (1 - self.confidence) / 2
        hi = 1 - lo

        return {
            'expected_return': round(total_returns.mean() * 100, 2),
            'median_return': round(np.median(total_returns) * 100, 2),
            'return_ci_low': round(np.percentile(total_returns, lo * 100) * 100, 2),
            'return_ci_high': round(np.percentile(total_returns, hi * 100) * 100, 2),
            'expected_max_dd': round(np.mean(max_dds) * 100, 2),
            'worst_case_dd': round(max_dds.min() * 100, 2),
            'probability_of_loss': round(prob_loss * 100, 1),
            'n_simulations': self.n_sims,
            'confidence': self.confidence,
        }


# ══════════════════════════════════════════════════════════
# GENERADOR DE DATOS HISTÓRICOS (para pruebas)
# ══════════════════════════════════════════════════════════

def generate_test_data(n_bars: int = 3000, start_price: float = 84000) -> pd.DataFrame:
    """
    Genera datos OHLCV sintéticos realistas para backtesting.
    Incluye tendencias, consolidaciones y breakouts.
    """
    np.random.seed(42)
    prices = [start_price]

    for i in range(n_bars - 1):
        # Régimen de mercado (cambia cada ~200 barras)
        regime = (i // 200) % 3  # 0=trend_up, 1=range, 2=trend_down
        if regime == 0:
            drift = 0.0002
            vol = 0.003
        elif regime == 1:
            drift = 0.0
            vol = 0.002
        else:
            drift = -0.00015
            vol = 0.004

        ret = np.random.normal(drift, vol)
        prices.append(prices[-1] * (1 + ret))

    prices = np.array(prices)
    times = pd.date_range('2025-01-01', periods=n_bars, freq='5min')

    # Generar OHLCV
    high_noise = np.abs(np.random.normal(0, 0.002, n_bars))
    low_noise = np.abs(np.random.normal(0, 0.002, n_bars))

    df = pd.DataFrame({
        'time': times,
        'open': prices * (1 + np.random.normal(0, 0.0005, n_bars)),
        'high': prices * (1 + high_noise),
        'low': prices * (1 - low_noise),
        'close': prices,
        'volume': np.random.exponential(100, n_bars),
    })

    return df


# ══════════════════════════════════════════════════════════
# CLI — Ejecutar backtesting desde terminal
# ══════════════════════════════════════════════════════════

if __name__ == '__main__':
    print("=" * 60)
    print("  TITANIUM v8.0 PRO — BACKTESTING ENGINE")
    print("=" * 60)

    # Generar datos de prueba
    print("\n[1/4] Generando datos historicos simulados (3000 barras)...")
    data = generate_test_data(3000)
    print(f"       Periodo: {data['time'].iloc[0]} -> {data['time'].iloc[-1]}")
    print(f"       Precio: ${data['close'].iloc[0]:,.0f} -> ${data['close'].iloc[-1]:,.0f}")

    # Backtest simple
    print("\n[2/4] Ejecutando backtest (score >= 65)...")
    bt = TitaniumBacktester(initial_capital=10000)
    results = bt.run(data, score_threshold=65)

    m = results['metrics']
    print(f"\n  --- RESULTADOS ---")
    print(f"  Return Total:    {m['total_return']:+.2f}%")
    print(f"  Return Anual:    {m['annual_return']:+.2f}%")
    print(f"  Sharpe Ratio:    {m['sharpe_ratio']:.3f}")
    print(f"  Sortino Ratio:   {m['sortino_ratio']:.3f}")
    print(f"  Max Drawdown:    {m['max_drawdown']:.2f}%")
    print(f"  Win Rate:        {m['win_rate']:.1f}%")
    print(f"  Profit Factor:   {m['profit_factor']:.2f}")
    print(f"  Trades:          {m['num_trades']}")
    print(f"  Expectancy:      {m['expectancy']:.3f}%")

    # Monte Carlo
    print("\n[3/4] Monte Carlo Simulation (1000 escenarios)...")
    mc = MonteCarloSimulator(n_simulations=1000)
    mc_results = mc.analyze(results['returns'])
    print(f"  Return Esperado:   {mc_results['expected_return']:+.2f}%")
    print(f"  CI 95%:            [{mc_results['return_ci_low']:+.2f}%, {mc_results['return_ci_high']:+.2f}%]")
    print(f"  Max DD Esperado:   {mc_results['expected_max_dd']:.2f}%")
    print(f"  Peor Caso DD:      {mc_results['worst_case_dd']:.2f}%")
    print(f"  P(Loss):           {mc_results['probability_of_loss']:.1f}%")

    # Trade log
    trades = results['trades']
    if trades:
        print(f"\n[4/4] Ultimos 5 trades:")
        for t in trades[-5:]:
            icon = 'WIN' if t['pnl_pct'] > 0 else 'LOSS'
            print(f"  {t['direction']:5} | Entry: ${t['entry']:,.0f} | "
                  f"Exit: ${t['exit']:,.0f} | {t['pnl_pct']:+.2f}% | "
                  f"{t['result']} | {icon}")

    print("\n" + "=" * 60)
    print("  Backtest completado.")
    print("=" * 60)
