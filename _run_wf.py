"""Run Walk-Forward Analysis."""
from backtest import WalkForwardAnalyzer, MonteCarloSimulator, generate_test_data

print("=" * 60)
print("  TITANIUM — WALK-FORWARD ANALYSIS")
print("=" * 60)

data = generate_test_data(5000)
print(f"\nDatos: {len(data)} barras")

wf = WalkForwardAnalyzer(train_bars=1500, test_bars=500)
results = wf.run(data)

cm = results['combined_metrics']
print("\n  RESULTADOS COMBINADOS (Out-of-Sample):")
print(f"  Return Total:   {cm['total_return']:+.2f}%")
print(f"  Sharpe Ratio:   {cm['sharpe_ratio']:.3f}")
print(f"  Sortino Ratio:  {cm['sortino_ratio']:.3f}")
print(f"  Max Drawdown:   {cm['max_drawdown']:.2f}%")
print(f"  Win Rate:       {cm['win_rate']:.1f}%")
print(f"  Profit Factor:  {cm['profit_factor']:.2f}")
print(f"  Trades:         {cm['num_trades']}")
print(f"  Splits:         {results['n_splits']}")
print("=" * 60)
