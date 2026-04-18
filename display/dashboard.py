"""
Dashboard profesional con Rich — Interfaz de trader.
Muestra mercado, indicadores, confluencia, señales activas, historial,
panel de riesgo (Circuit Breaker, Kelly, Trailing Stop) y estadísticas.
"""
import sys
from datetime import datetime
import pytz
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text
from rich import box

import config
from core.indicators import get_trend_direction


class Dashboard:
    def __init__(self, console):
        self.console = console
        self.tz = pytz.timezone(config.MY_TIMEZONE)

    def render(self, tf_data, ob_data, long_s, long_bd, short_s, short_bd,
               active_signal, history, ai_status, risk_status=None):
        """Generar layout completo del dashboard."""
        entry_df = tf_data.get(config.TF_ENTRY)
        last = entry_df.iloc[-1] if entry_df is not None and len(entry_df) > 0 else None

        layout = Layout()
        layout.split_column(
            Layout(self._header(ai_status), name="hdr", size=3),
            Layout(name="mid", size=11),
            Layout(name="bottom_mid", size=7),
            Layout(self._signal_panel(active_signal), name="sig", size=5),
            Layout(self._history_panel(history), name="hist", size=9),
        )
        layout["mid"].split_row(
            Layout(self._market_panel(last, ob_data), name="mkt"),
            Layout(self._indicators_panel(last, entry_df), name="ind"),
        )
        layout["bottom_mid"].split_row(
            Layout(self._scores_panel(long_s, long_bd, short_s, short_bd), name="scores"),
            Layout(self._risk_panel(risk_status), name="risk"),
        )
        return layout

    # ── PANELES ──────────────────────────────────────────

    def _header(self, ai_status):
        now = datetime.now(self.tz).strftime('%Y-%m-%d %H:%M:%S')
        session = self._session()

        # Estado IA
        if ai_status.get("panic_mode"):
            ai_text = Text(f" ⚠️ BLACK SWAN: {ai_status.get('reason')} ", style="bold white on red")
        else:
            score = ai_status.get('score', 50)
            sc = 'green' if score >= 50 else 'red'
            ai_text = Text(f" 🧠 IA: {ai_status.get('reason')} ({score}) ", style=f"bold {sc}")

        t = Text()
        t.append("  ⚡ TITANIUM v8.0 PRO ", style="bold white on blue")
        t.append(f"  {config.SYMBOL}  ", style="bold yellow")
        t.append(f"  {session}  ", style="bold white")
        t.append_text(ai_text)
        t.append(f"  📅 {now} COT", style="dim")
        return Panel(t, box=box.HEAVY, style="bright_blue")

    def _market_panel(self, last, ob):
        tbl = Table(show_header=False, box=None, padding=(0, 2))
        tbl.add_column("l", style="dim", width=14)
        tbl.add_column("v", width=20)

        if last is not None and ob:
            price = last['close']
            obi = ob['obi']
            oc = 'green' if obi > 0 else 'red'
            total_vol = ob['bid_vol'] + ob['ask_vol']
            bid_pct = ob['bid_vol'] / total_vol * 100 if total_vol > 0 else 50

            tbl.add_row("💰 Precio",   f"[bold yellow]{price:,.1f}[/]")
            tbl.add_row("📦 OBI",      f"[bold {oc}]{obi:+.3f}[/]")
            tbl.add_row("📊 Spread",   f"{ob['spread']:.2f}")
            tbl.add_row("🟢 Bids",     f"[green]{bid_pct:.0f}%[/]")
            tbl.add_row("🔴 Asks",     f"[red]{100-bid_pct:.0f}%[/]")
            tbl.add_row("📡 Raw OBI",  f"[{oc}]{ob['raw_obi']:+.3f}[/]")
        else:
            tbl.add_row("⏳", "Cargando...")

        return Panel(tbl, title="[bold]📈 MERCADO[/]", border_style="blue", box=box.ROUNDED)

    def _indicators_panel(self, last, entry_df):
        tbl = Table(show_header=False, box=None, padding=(0, 2))
        tbl.add_column("l", style="dim", width=14)
        tbl.add_column("v", width=20)

        if last is not None:
            adx = self._s(last, 'ADX')
            rsi = self._s(last, 'RSI', 50)
            atr = self._s(last, 'ATR')
            atr_pct = self._s(last, 'ATR_pct', 0)
            mh  = self._s(last, 'MACD_hist')
            bb  = self._s(last, 'BB_pct', 0.5)
            vr  = self._s(last, 'vol_ratio', 1.0)

            ac = 'green' if adx > config.ADX_THRESHOLD else 'red'
            rc = 'green' if 40 < rsi < 60 else ('yellow' if 30 < rsi < 70 else 'red')
            mc = 'green' if mh > 0 else 'red'

            tbl.add_row("📊 ADX",  f"[bold {ac}]{adx:.1f}[/]")
            tbl.add_row("📉 RSI",  f"[{rc}]{rsi:.1f}[/]")
            tbl.add_row("📐 ATR",  f"{atr:.1f} ({atr_pct:.2f}%)")
            tbl.add_row("〰️ MACD", f"[{mc}]{'▲' if mh > 0 else '▼'} {abs(mh):.1f}[/]")
            tbl.add_row("📏 BB%",  f"{bb:.2f}")
            tbl.add_row("📊 Vol",  f"{vr:.1f}x")

            if entry_df is not None:
                d, _ = get_trend_direction(entry_df)
                ec = {'BULLISH': 'green', 'BEARISH': 'red'}.get(d, 'yellow')
                tbl.add_row("📐 EMA",  f"[bold {ec}]{d}[/]")

                # FASE 2: Mostrar divergencias y estructura
                rsi_div = last.get('rsi_divergence', 'NONE')
                if rsi_div != 'NONE':
                    dc = 'green' if rsi_div == 'BULL_DIV' else 'red'
                    tbl.add_row("⚡ Div", f"[bold {dc}]{rsi_div}[/]")

                mkt_s = last.get('market_structure', 'RANGING')
                sc = {'BULLISH_STRUCT': 'green', 'BEARISH_STRUCT': 'red'}.get(mkt_s, 'dim')
                tbl.add_row("🏗️ Struct", f"[{sc}]{mkt_s}[/]")
        else:
            tbl.add_row("⏳", "Cargando...")

        return Panel(tbl, title="[bold]🧮 INDICADORES[/]", border_style="magenta", box=box.ROUNDED)

    def _scores_panel(self, long_s, long_bd, short_s, short_bd):
        tbl = Table(show_header=False, box=None, padding=(0, 1))
        tbl.add_column("d", width=12)
        tbl.add_column("bar", width=30)

        tbl.add_row("[green]🟢 LONG[/]",  self._bar(long_s))
        tbl.add_row("[red]🔴 SHORT[/]", self._bar(short_s))

        # Desglose del más fuerte
        bd = long_bd if long_s >= short_s else short_bd
        parts = []
        for k, (sc, mx) in (bd or {}).items():
            icon = '✅' if sc >= mx * 0.6 else ('⚠️' if sc > 0 else '❌')
            parts.append(f"{icon}{k}:{sc}/{mx}")

        content = Table.grid(padding=0)
        content.add_row(tbl)
        content.add_row(Text("  ".join(parts), style="dim"))

        return Panel(content, title="[bold]🎯 CONFLUENCIA[/]", border_style="yellow", box=box.ROUNDED)

    def _risk_panel(self, risk_status):
        """Panel de estado de riesgo — Circuit Breaker + Kelly + Trailing."""
        tbl = Table(show_header=False, box=None, padding=(0, 1))
        tbl.add_column("l", style="dim", width=16)
        tbl.add_column("v", width=18)

        if risk_status:
            cb = risk_status.get('breaker', {})
            ks = risk_status.get('sizer', {})

            # Circuit Breaker
            can_trade = cb.get('can_trade', True)
            ct_color = 'green' if can_trade else 'red'
            ct_text = '🟢 ACTIVO' if can_trade else '🔴 PAUSADO'
            tbl.add_row("🛡️ Breaker", f"[bold {ct_color}]{ct_text}[/]")

            daily = cb.get('daily_pnl_pct', 0)
            dc = 'green' if daily >= 0 else 'red'
            tbl.add_row("📅 P&L Diario", f"[{dc}]{daily:+.2f}%[/]")

            total = cb.get('total_pnl_pct', 0)
            tc = 'green' if total >= 0 else 'red'
            tbl.add_row("💰 P&L Total", f"[{tc}]{total:+.2f}%[/]")

            losses = cb.get('consecutive_losses', 0)
            lc = 'green' if losses < 3 else ('yellow' if losses < 5 else 'red')
            tbl.add_row("📉 Rachas", f"[{lc}]{losses}/{config.MAX_CONSECUTIVE_LOSSES}[/]")

            # Kelly
            kelly = ks.get('kelly_pct', config.MIN_POSITION_PCT * 100)
            tbl.add_row("📐 Kelly", f"{kelly:.1f}%")

            wr = ks.get('win_rate', 0)
            wc = 'green' if wr > 50 else ('yellow' if wr > 40 else 'red')
            trades = ks.get('total_trades', 0)
            tbl.add_row("🎯 WinRate", f"[{wc}]{wr:.0f}%[/] ({trades}t)")

            # Pause reason
            reason = cb.get('pause_reason')
            if reason:
                tbl.add_row("⚠️ Razón", f"[red]{reason[:20]}[/]")
        else:
            tbl.add_row("⏳", "Inicializando...")

        return Panel(tbl, title="[bold]🛡️ RIESGO[/]", border_style="cyan", box=box.ROUNDED)

    def _signal_panel(self, sig):
        if sig is None:
            return Panel(
                Text("  Esperando confluencia ≥ 65...", style="dim italic"),
                title="[bold]🎯 SEÑAL[/]", border_style="dim", box=box.ROUNDED
            )

        sc = 'green' if sig.direction == 'LONG' else 'red'
        strength = '🔥 FUERTE' if sig.is_strong else '⚡ MODERADA'
        age = int(sig.age_seconds)

        # Fase del trailing stop
        phase_icons = {
            'INITIAL': '🔵 INICIAL',
            'BREAKEVEN': '🟡 BREAKEVEN',
            'TIGHT': '🟢 APRETADO',
        }
        phase_text = phase_icons.get(getattr(sig, 'trailing_phase', 'INITIAL'), '🔵')

        t = Text()
        t.append(f"  {sig.emoji} {sig.direction} ", style=f"bold {sc}")
        t.append(f"| Score: {sig.score}/100 | {strength} ", style=f"{sc}")
        t.append(f"| ⏱️ {age}s\n", style="dim")
        t.append(f"  📍 Entry: {sig.entry:,.1f}  ", style="white")
        t.append(f"🛑 SL: {sig.stop_loss:,.1f} (-{sig.sl_distance:,.1f})  ", style="red")
        t.append(f"🎯 TP: {sig.take_profit:,.1f} (+{sig.tp_distance:,.1f})\n", style="green")
        t.append(f"  ⚖️ R:R = 1:{sig.risk_reward:.2f}  |  📐 ATR: {sig.atr:.1f}  |  🔄 {phase_text}", style="dim")

        return Panel(t, title=f"[bold]🎯 SEÑAL ACTIVA[/]", border_style=sc, box=box.ROUNDED)

    def _history_panel(self, history):
        tbl = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold dim",
                    padding=(0, 1))
        tbl.add_column("Hora", width=7)
        tbl.add_column("Dir", width=9)
        tbl.add_column("Score", width=6, justify="center")
        tbl.add_column("Entry", width=11, justify="right")
        tbl.add_column("SL", width=11, justify="right")
        tbl.add_column("TP", width=11, justify="right")
        tbl.add_column("R:R", width=7)
        tbl.add_column("Status", width=10)

        for sig in list(history)[-6:]:
            c = 'green' if sig.direction == 'LONG' else 'red'
            t = sig.timestamp.astimezone(self.tz).strftime('%H:%M')
            st_map = {
                'ACTIVE': 'cyan', 'HIT_TP': 'green', 'HIT_SL': 'red',
                'EXPIRED': 'dim', 'BLOCKED_CB': 'yellow', 'BLOCKED_AI': 'magenta'
            }
            st_c = st_map.get(sig.status, 'white')
            status_text = sig.status
            if sig.status == 'BLOCKED_CB':
                status_text = '🛡️ BLOCK'
            elif sig.status == 'BLOCKED_AI':
                status_text = '🧠 BLOCK'

            tbl.add_row(
                t, f"[{c}]{sig.emoji} {sig.direction}[/]",
                str(sig.score), f"{sig.entry:,.1f}",
                f"[red]{sig.stop_loss:,.1f}[/]", f"[green]{sig.take_profit:,.1f}[/]",
                f"1:{sig.risk_reward:.1f}", f"[{st_c}]{status_text}[/]",
            )

        if not history:
            return Panel(Text("  Sin señales aún", style="dim"), title="[bold]📋 HISTORIAL[/]",
                         border_style="dim", box=box.ROUNDED)
        return Panel(tbl, title="[bold]📋 HISTORIAL[/]", border_style="dim", box=box.ROUNDED)

    # ── UTILIDADES ────────────────────────────────────────

    def _bar(self, score, width=25):
        filled = int((score / 100) * width)
        bar = '█' * filled + '░' * (width - filled)
        c = 'green' if score >= 80 else ('yellow' if score >= 65 else 'white')
        return f"[{c}]{bar}[/] [{c}]{score}[/]/100"

    def _session(self):
        h = datetime.now(pytz.utc).hour
        active = [s for s in config.SESSIONS.values() if s['start'] <= h < s['end']]
        return ' + '.join(f"{s['emoji']} {s['name']}" for s in active) if active else '🌙 OFF-HOURS'

    @staticmethod
    def _s(row, col, default=0):
        import pandas as pd
        v = row.get(col, default)
        return default if pd.isna(v) else float(v)
