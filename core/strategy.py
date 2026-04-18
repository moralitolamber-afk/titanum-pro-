"""
⚡ Motor de Confluencia — El cerebro de TITANIUM.
Evalúa 8 factores y genera un score 0-100 para LONG y SHORT.
Solo emite señal cuando la confluencia supera el umbral.
Incluye Trailing Stop Dinámico basado en ATR.
"""
import time
import uuid
from datetime import datetime, timezone
from collections import deque

import config
from models.signal import Signal
from core.indicators import get_trend_direction
from risk.trailing_stop import TrailingStop, TrailingStopConfig


class StrategyEngine:
    def __init__(self):
        self.last_signal_time = 0
        self.signal_history = deque(maxlen=50)
        self.trailing_stop = TrailingStop(TrailingStopConfig(
            atr_multiplier=config.TRAILING_ATR_MULT,
            tighten_after_rr=config.TRAILING_TIGHTEN_RR,
            tighten_multiplier=config.TRAILING_TIGHTEN_MULT,
            breakeven_at_rr=config.TRAILING_BREAKEVEN_RR,
        ))

    # ── API PÚBLICA ───────────────────────────────────────

    def analyze(self, tf_data, ob_data):
        """Análisis principal. Retorna (long_s, long_bd, short_s, short_bd, signal|None)."""
        entry_df   = tf_data.get(config.TF_ENTRY)
        confirm_df = tf_data.get(config.TF_CONFIRM)
        trend_df   = tf_data.get(config.TF_TREND)

        if entry_df is None or len(entry_df) < config.EMA_SLOW:
            return 0, {}, 0, {}, None

        last = entry_df.iloc[-1]
        obi  = ob_data['obi']

        long_s,  long_bd  = self._score('LONG',  last, entry_df, confirm_df, trend_df, obi)
        short_s, short_bd = self._score('SHORT', last, entry_df, confirm_df, trend_df, obi)

        # ── FASE 2: Filtro de volatilidad (ATR% demasiado bajo = mercado muerto) ──
        atr_pct = self._safe(last, 'ATR_pct', 0)
        if atr_pct < 0.3:  # Volatilidad extremadamente baja
            long_s = int(long_s * 0.5)
            short_s = int(short_s * 0.5)

        # ── FASE 2: Penalizar si hay divergencia RSI contra la dirección ──
        rsi_div = last.get('rsi_divergence', 'NONE')
        if rsi_div == 'BEAR_DIV':
            long_s = int(long_s * 0.7)   # Penalizar longs
        elif rsi_div == 'BULL_DIV':
            short_s = int(short_s * 0.7)  # Penalizar shorts

        # ── FASE 2: Bonificar si estructura de mercado confirma ──
        mkt_struct = last.get('market_structure', 'RANGING')
        if mkt_struct == 'BULLISH_STRUCT':
            long_s = min(100, int(long_s * 1.1))
        elif mkt_struct == 'BEARISH_STRUCT':
            short_s = min(100, int(short_s * 1.1))

        # ── FASE 2: Boost por sesión de trading activa ──
        session_boost = self._session_boost()
        long_s = min(100, int(long_s * session_boost))
        short_s = min(100, int(short_s * session_boost))

        # Generar señal solo si pasa cooldown
        new_signal = None
        cooldown_ok = (time.time() - self.last_signal_time) >= config.SIGNAL_COOLDOWN_SEC

        if cooldown_ok:
            if long_s >= config.SCORE_MIN_ENTRY and long_s > short_s:
                new_signal = self._build_signal('LONG', long_s, long_bd, last)
            elif short_s >= config.SCORE_MIN_ENTRY and short_s > long_s:
                new_signal = self._build_signal('SHORT', short_s, short_bd, last)

            if new_signal:
                self.last_signal_time = time.time()
                self.signal_history.append(new_signal)

        return long_s, long_bd, short_s, short_bd, new_signal

    def check_signal_status(self, signal, current_price):
        """Verificar señal activa con Trailing Stop Dinámico."""
        if signal is None:
            return None

        # Actualizar trailing stop dinámicamente
        ts_result = self.trailing_stop.update(signal.signal_id, current_price)

        if ts_result.get('hit'):
            signal.status = 'HIT_SL'
            signal.stop_loss = ts_result['sl']  # Actualizar SL final
            signal.trailing_phase = ts_result['phase']
            self.trailing_stop.remove(signal.signal_id)
            return signal

        # Actualizar SL visible en el dashboard
        if ts_result.get('sl'):
            signal.stop_loss = ts_result['sl']
            signal.trailing_phase = ts_result.get('phase', 'INITIAL')

        # Verificar Take Profit
        if signal.direction == 'LONG' and current_price >= signal.take_profit:
            signal.status = 'HIT_TP'
            self.trailing_stop.remove(signal.signal_id)
            return signal
        elif signal.direction == 'SHORT' and current_price <= signal.take_profit:
            signal.status = 'HIT_TP'
            self.trailing_stop.remove(signal.signal_id)
            return signal

        # Verificar expiración
        if signal.age_seconds > config.SIGNAL_EXPIRY_SEC:
            signal.status = 'EXPIRED'
            self.trailing_stop.remove(signal.signal_id)
            return signal

        return None  # Sigue activa

    # ── SCORING PRIVADO ───────────────────────────────────

    def _score(self, direction, last, entry_df, confirm_df, trend_df, obi):
        is_long = direction == 'LONG'
        W = config.WEIGHTS
        bd = {}

        # 1. OBI
        s = 0
        if is_long and obi > config.OBI_THRESHOLD:
            s = min(W['obi'], W['obi'] * (obi / 0.5))
        elif not is_long and obi < -config.OBI_THRESHOLD:
            s = min(W['obi'], W['obi'] * (abs(obi) / 0.5))
        bd['OBI'] = (round(s, 1), W['obi'])

        # 2. ADX + DI
        adx = self._safe(last, 'ADX')
        di_p = self._safe(last, 'DI+')
        di_m = self._safe(last, 'DI-')
        s = 0
        if adx > config.ADX_THRESHOLD:
            aligned = (is_long and di_p > di_m) or (not is_long and di_m > di_p)
            if aligned:
                s = min(W['adx_trend'], W['adx_trend'] * (adx / config.ADX_STRONG))
        bd['ADX'] = (round(s, 1), W['adx_trend'])

        # 3. RSI
        rsi = self._safe(last, 'RSI', 50)
        s = 0
        if is_long and 45 < rsi < config.RSI_OVERBOUGHT:
            s = W['rsi'] * min(1.0, (rsi - 45) / 20)
        elif not is_long and config.RSI_OVERSOLD < rsi < 55:
            s = W['rsi'] * min(1.0, (55 - rsi) / 20)
        bd['RSI'] = (round(s, 1), W['rsi'])

        # 4. EMA Ribbon
        ema_dir, ema_str = get_trend_direction(entry_df)
        s = 0
        if (is_long and ema_dir == 'BULLISH') or (not is_long and ema_dir == 'BEARISH'):
            s = W['ema_alignment'] * ema_str
        bd['EMA'] = (round(s, 1), W['ema_alignment'])

        # 5. Multi-Timeframe
        agreements = 0
        for tf_df in [confirm_df, trend_df]:
            if tf_df is not None and len(tf_df) >= config.EMA_SLOW:
                d, _ = get_trend_direction(tf_df)
                if (is_long and d == 'BULLISH') or (not is_long and d == 'BEARISH'):
                    agreements += 1
        bd['MTF'] = (round(W['mtf_trend'] * agreements / 2, 1), W['mtf_trend'])

        # 6. MACD
        mh = self._safe(last, 'MACD_hist')
        ml = self._safe(last, 'MACD')
        ms = self._safe(last, 'MACD_signal')
        s = 0
        if is_long:
            if ml > ms and mh > 0: s = W['macd']
            elif mh > 0: s = W['macd'] * 0.5
        else:
            if ml < ms and mh < 0: s = W['macd']
            elif mh < 0: s = W['macd'] * 0.5
        bd['MACD'] = (round(s, 1), W['macd'])

        # 7. Bollinger Band position
        bb = self._safe(last, 'BB_pct', 0.5)
        s = 0
        if is_long:
            if bb < 0.3:   s = W['bb_position']
            elif bb < 0.6: s = W['bb_position'] * 0.6
        else:
            if bb > 0.7:   s = W['bb_position']
            elif bb > 0.4: s = W['bb_position'] * 0.6
        bd['BB'] = (round(s, 1), W['bb_position'])

        # 8. Volumen
        vr = self._safe(last, 'vol_ratio', 1.0)
        s = min(W['volume'], W['volume'] * (vr / 1.5)) if vr > 1.0 else 0
        bd['VOL'] = (round(s, 1), W['volume'])

        total = round(sum(v[0] for v in bd.values()))
        return total, bd

    def _build_signal(self, direction, score, breakdown, last):
        price = last['close']
        atr = self._safe(last, 'ATR') or price * 0.005
        signal_id = str(uuid.uuid4())[:8]

        # SL inicial viene del trailing stop
        sl = self.trailing_stop.initialize(signal_id, direction, price, atr)

        if direction == 'LONG':
            tp = price + atr * config.ATR_TP_MULTIPLIER
        else:
            tp = price - atr * config.ATR_TP_MULTIPLIER

        sl_dist = abs(price - sl)
        rr = abs(price - tp) / sl_dist if sl_dist > 0 else 0

        return Signal(
            signal_id=signal_id,
            direction=direction, score=score,
            timestamp=datetime.now(timezone.utc),
            price=price, entry=price,
            stop_loss=round(sl, 1), take_profit=round(tp, 1),
            atr=round(atr, 1), risk_reward=round(rr, 2),
            breakdown=breakdown,
        )

    @staticmethod
    def _safe(row, col, default=0):
        import pandas as pd
        v = row.get(col, default)
        return default if pd.isna(v) else float(v)

    @staticmethod
    def _session_boost():
        """Boost de score según la sesión activa (London+NY = mayor volumen)."""
        from datetime import datetime, timezone
        h = datetime.now(timezone.utc).hour
        # London + NY overlap (13-16 UTC) = mejor momento
        if 13 <= h < 16:
            return 1.15  # +15% boost
        # London (7-16) o NY (13-22)
        if 7 <= h < 22:
            return 1.05  # +5% boost
        # Asia o fuera de horas
        return 0.95  # -5% penalización
