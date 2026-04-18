"""
⚡ TITANIUM v8.0 — Smart Trading Scanner
Motor de confluencia multi-timeframe para BTC/USDT.
Analiza 8 factores, puntúa 0-100 y genera señales con SL/TP dinámicos.
Incluye: Circuit Breaker, Kelly Position Sizer, ATR Trailing Stop.
"""
import asyncio
import sys
import os

# Fix encoding en Windows para emojis
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rich.console import Console
from rich.live import Live

import config
from core.exchange import ExchangeManager
from core.indicators import calculate_all
from core.strategy import StrategyEngine
from core.ai_brain import AIBrain
from risk.circuit_breaker import CircuitBreaker
from risk.position_sizer import KellyPositionSizer
from display.dashboard import Dashboard
from utils.logger import log_signal


async def main():
    console = Console()
    console.clear()

    exchange  = ExchangeManager()
    strategy  = StrategyEngine()
    ai_brain  = AIBrain()
    breaker   = CircuitBreaker()
    sizer     = KellyPositionSizer()
    dashboard = Dashboard(console)
    active_signal = None
    ai_status = ai_brain.sentiment_state

    console.print("[bold cyan]⚡ Iniciando TITANIUM v8.0 PRO...[/]")

    try:
        await exchange.connect()
        console.print("[green]✅ Conectado a Binance[/]")
        console.print("[green]🛡️  Circuit Breaker: ACTIVO[/]")
        console.print("[green]📐 Kelly Sizer: ACTIVO[/]")
        console.print("[green]🔄 Trailing Stop: ACTIVO[/]")

        # Fetch inicial
        tf_data = await exchange.fetch_all_timeframes()
        ob_data = await exchange.fetch_obi()

        for tf in tf_data:
            tf_data[tf] = calculate_all(tf_data[tf])

        long_s, long_bd, short_s, short_bd, _ = strategy.analyze(tf_data, ob_data)

        risk_status = {
            'breaker': breaker.get_status(),
            'sizer': sizer.get_status(),
        }

        initial = dashboard.render(
            tf_data, ob_data, long_s, long_bd, short_s, short_bd,
            active_signal, strategy.signal_history, ai_status, risk_status
        )

        with Live(initial, console=console, refresh_per_second=1, screen=True) as live:
            while True:
                try:
                    # ── Fetch ──
                    ob_data = await exchange.fetch_obi()
                    tf_data = await exchange.fetch_all_timeframes()

                    # ── Indicadores ──
                    for tf in tf_data:
                        tf_data[tf] = calculate_all(tf_data[tf])

                    # ── Inteligencia Artificial ──
                    asyncio.create_task(ai_brain.analyze_sentiment())
                    ai_status = ai_brain.sentiment_state

                    # ── Análisis de confluencia ──
                    long_s, long_bd, short_s, short_bd, new_sig = strategy.analyze(
                        tf_data, ob_data
                    )

                    # ── Nueva señal: verificar Circuit Breaker + IA ──
                    if new_sig:
                        can_trade = breaker.can_trade()
                        is_panic = ai_status.get("panic_mode", False)

                        if can_trade and not is_panic:
                            active_signal = new_sig
                            log_signal(new_sig)
                        else:
                            # Señal bloqueada, registrar razón
                            new_sig.status = 'BLOCKED'
                            if not can_trade:
                                new_sig.status = f'BLOCKED_CB'
                            elif is_panic:
                                new_sig.status = f'BLOCKED_AI'
                            strategy.signal_history.append(new_sig)

                    # ── Verificar señal activa (Trailing SL/TP/expiración) ──
                    if active_signal:
                        entry_df = tf_data.get(config.TF_ENTRY)
                        if entry_df is not None and len(entry_df) > 0:
                            price = entry_df.iloc[-1]['close']
                            closed = strategy.check_signal_status(active_signal, price)
                            if closed:
                                # Calcular PnL
                                pnl = closed.calculate_pnl(price)

                                # Registrar en Circuit Breaker y Kelly Sizer
                                breaker.record_trade(pnl)
                                sizer.add_trade(pnl)

                                log_signal(closed)
                                active_signal = None

                    # ── Actualizar risk status ──
                    risk_status = {
                        'breaker': breaker.get_status(),
                        'sizer': sizer.get_status(),
                    }

                    # ── Render dashboard ──
                    layout = dashboard.render(
                        tf_data, ob_data, long_s, long_bd, short_s, short_bd,
                        active_signal, strategy.signal_history, ai_status,
                        risk_status
                    )
                    live.update(layout)

                except Exception:
                    pass  # No crashear por errores transitorios

                await asyncio.sleep(config.UPDATE_INTERVAL)

    except KeyboardInterrupt:
        console.print("\n[yellow]🛑 TITANIUM detenido.[/]")
    finally:
        await exchange.close()
        console.print("[dim]Conexión cerrada. Hasta pronto. 🚀[/]")


if __name__ == '__main__':
    asyncio.run(main())
