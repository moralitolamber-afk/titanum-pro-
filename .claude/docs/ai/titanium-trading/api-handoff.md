# API Handoff: TITANIUM v8.0 PRO Trading Dashboard

## Business Context
TITANIUM es un bot de trading algorítmico que analiza BTC/USDT en tiempo real usando 8 factores de confluencia, inteligencia artificial para detección de cisnes negros, y gestión de riesgo institucional (Circuit Breaker, Kelly Criterion, Trailing Stop dinámico). El frontend necesita consumir estos datos para mostrar un dashboard interactivo de trader profesional. DEMO_MODE está habilitado por defecto (datos simulados).

## Endpoints

### GET /api/dashboard
- **Purpose**: Retorna TODOS los datos del dashboard en una sola llamada optimizada. Endpoint principal.
- **Auth**: Public (sin autenticación en v1)
- **Response** (success):
  ```json
  {
    "market": { "price": 84532.1, "obi": 0.152, "raw_obi": 0.18, "bid_vol": 175.2, "ask_vol": 124.8, "spread": 0.3, "bid_pct": 58.4 },
    "indicators": { "adx": 28.5, "rsi": 55.2, "atr": 320.5, "atr_pct": 0.38, "macd_hist": 12.3, "bb_pct": 0.62, "vol_ratio": 1.4, "trend_direction": "BULLISH", "trend_strength": 0.7, "rsi_divergence": "NONE", "market_structure": "BULLISH_STRUCT" },
    "confluence": { "long_score": 72, "short_score": 18, "dominant": "LONG", "breakdown": [{"factor": "OBI", "score": 12.0, "max_score": 15, "status": "pass"}] },
    "active_signal": { "signal_id": "a1b2c3d4", "direction": "LONG", "score": 72, "entry": 84500.0, "stop_loss": 83850.0, "take_profit": 85300.0, "sl_distance": 650.0, "tp_distance": 800.0, "risk_reward": 1.23, "atr": 320.5, "trailing_phase": "BREAKEVEN", "age_seconds": 45.2, "is_strong": false, "status": "ACTIVE", "timestamp": "2026-04-17T15:30:00-05:00" },
    "risk": { "can_trade": true, "daily_pnl_pct": -1.2, "total_pnl_pct": 3.5, "consecutive_losses": 1, "max_consecutive_losses": 5, "total_trades": 24, "win_rate": 58.3, "kelly_pct": 8.5, "pause_reason": null },
    "ai": { "panic_mode": false, "reason": "Mercado estable", "score": 65 },
    "session": { "active_sessions": ["🏰 LONDON", "🗽 NEW YORK"], "session_boost": 1.15, "timestamp": "2026-04-17T15:30:00-05:00", "timezone": "America/Bogota" },
    "history": []
  }
  ```
- **Response** (error): 500 si no hay datos de mercado disponibles
- **Notes**: Polling recomendado cada 3-4 segundos. `active_signal` es `null` cuando no hay señal activa.

### GET /api/market
- **Purpose**: Solo datos de mercado (precio, OBI, spread)
- **Auth**: Public
- **Response** (success):
  ```json
  { "price": 84532.1, "obi": 0.152, "raw_obi": 0.18, "bid_vol": 175.2, "ask_vol": 124.8, "spread": 0.3, "bid_pct": 58.4 }
  ```

### GET /api/indicators
- **Purpose**: Indicadores técnicos (ADX, RSI, ATR, MACD, BBands, tendencia, divergencias, estructura)
- **Auth**: Public
- **Response** (success):
  ```json
  { "adx": 28.5, "rsi": 55.2, "atr": 320.5, "atr_pct": 0.38, "macd_hist": 12.3, "bb_pct": 0.62, "vol_ratio": 1.4, "trend_direction": "BULLISH", "trend_strength": 0.7, "rsi_divergence": "NONE", "market_structure": "BULLISH_STRUCT" }
  ```

### GET /api/confluence
- **Purpose**: Scores de confluencia LONG/SHORT con desglose de 8 factores
- **Auth**: Public
- **Response** (success):
  ```json
  {
    "long_score": 72,
    "short_score": 18,
    "dominant": "LONG",
    "breakdown": [
      {"factor": "OBI", "score": 12.0, "max_score": 15, "status": "pass"},
      {"factor": "ADX", "score": 10.5, "max_score": 15, "status": "warn"},
      {"factor": "RSI", "score": 7.0, "max_score": 10, "status": "pass"},
      {"factor": "EMA", "score": 15.0, "max_score": 15, "status": "pass"},
      {"factor": "MTF", "score": 10.0, "max_score": 20, "status": "warn"},
      {"factor": "MACD", "score": 10.0, "max_score": 10, "status": "pass"},
      {"factor": "BB", "score": 6.0, "max_score": 10, "status": "pass"},
      {"factor": "VOL", "score": 3.3, "max_score": 5, "status": "pass"}
    ]
  }
  ```
- **Notes**: `dominant` es NEUTRAL cuando ningún score llega a 65. `status` es: pass (≥60% del max), warn (>0), fail (=0).

### GET /api/signal
- **Purpose**: Señal de trading activa con entry/SL/TP dinámicos
- **Auth**: Public
- **Response** (success): `SignalData` object o `null`
- **Notes**: SL se actualiza en cada tick por el trailing stop. `trailing_phase` puede ser INITIAL, BREAKEVEN, o TIGHT.

### GET /api/risk
- **Purpose**: Estado de gestión de riesgo
- **Auth**: Public
- **Response** (success):
  ```json
  { "can_trade": true, "daily_pnl_pct": -1.2, "total_pnl_pct": 3.5, "consecutive_losses": 1, "max_consecutive_losses": 5, "total_trades": 24, "win_rate": 58.3, "kelly_pct": 8.5, "pause_reason": null }
  ```
- **Notes**: `can_trade: false` cuando Circuit Breaker está activado. `pause_reason` describe por qué.

### GET /api/history
- **Purpose**: Últimas 20 señales con resultado
- **Auth**: Public

### GET /api/health
- **Purpose**: Health check del sistema
- **Auth**: Public
- **Response**: `{ "status": "ok", "demo_mode": true, "symbol": "BTC/USDT" }`

## Data Models / DTOs

```typescript
interface MarketData {
  price: number;
  obi: number;        // -1 to 1, positivo = más compradores
  raw_obi: number;    // Sin suavizar
  bid_vol: number;
  ask_vol: number;
  spread: number;
  bid_pct: number;    // 0-100, porcentaje de bids
}

interface SignalData {
  signal_id: string;
  direction: 'LONG' | 'SHORT';
  score: number;       // 0-100
  entry: number;
  stop_loss: number;   // Se mueve dinámicamente (trailing)
  take_profit: number;
  sl_distance: number;
  tp_distance: number;
  risk_reward: number;
  atr: number;
  trailing_phase: 'INITIAL' | 'BREAKEVEN' | 'TIGHT';
  age_seconds: number;
  is_strong: boolean;  // score >= 80
  status: 'ACTIVE' | 'HIT_TP' | 'HIT_SL' | 'EXPIRED' | 'BLOCKED_CB' | 'BLOCKED_AI';
  timestamp: string;   // ISO 8601 con timezone
}
```

## Enums & Constants

| Value | Meaning | Display |
|-------|---------|---------|
| `LONG` | Señal de compra | 🟢 LONG |
| `SHORT` | Señal de venta | 🔴 SHORT |
| `NEUTRAL` | Sin dirección clara | ⚪ NEUTRAL |
| `BULLISH` | Tendencia alcista | 📈 Alcista |
| `BEARISH` | Tendencia bajista | 📉 Bajista |
| `INITIAL` | Trailing SL en posición inicial | 🔵 Inicial |
| `BREAKEVEN` | SL movido a precio de entrada | 🟡 Breakeven |
| `TIGHT` | SL apretado protegiendo ganancias | 🟢 Apretado |
| `BULL_DIV` | RSI diverge al alza (señal oculta alcista) | ⚡ Div. Alcista |
| `BEAR_DIV` | RSI diverge a la baja (señal oculta bajista) | ⚡ Div. Bajista |
| `BULLISH_STRUCT` | Higher Highs + Higher Lows | 📈 Estructura Alcista |
| `BEARISH_STRUCT` | Lower Highs + Lower Lows | 📉 Estructura Bajista |
| `RANGING` | Sin estructura clara | ↔️ Rango |
| `HIT_TP` | Señal cerrada por Take Profit | ✅ TP |
| `HIT_SL` | Señal cerrada por Stop Loss | ❌ SL |
| `EXPIRED` | Señal expirada por tiempo | ⏰ Expirada |
| `BLOCKED_CB` | Señal bloqueada por Circuit Breaker | 🛡️ Bloqueada |
| `BLOCKED_AI` | Señal bloqueada por Black Swan AI | 🧠 Bloqueada |

## Validation Rules
- `score`: siempre 0-100, señal se emite solo si ≥ 65
- `risk_reward`: siempre ≥ 0, idealmente > 1.0
- `obi`: rango típico -0.6 a 0.6
- `rsi`: 0-100 (sobrecompra > 70, sobreventa < 30)
- `adx`: 0-100 (tendencia fuerte > 20, muy fuerte > 30)
- `bb_pct`: 0-1 (0 = banda inferior, 1 = banda superior)

## Business Logic & Edge Cases
- `active_signal` es `null` el 80% del tiempo. Solo aparece cuando confluencia ≥ 65.
- `stop_loss` cambia en cada respuesta — el trailing lo mueve automáticamente. Frontend NO debe cachear SL.
- Circuit Breaker pausa el trading sin destruir señales históricas.
- `BLOCKED_CB` y `BLOCKED_AI` son señales que se generaron pero no se activaron.
- En DEMO_MODE, los precios son simulados y oscilan alrededor de ~84,000.
- La IA solo chequea noticias cada 5 minutos (no cada tick).

## Integration Notes
- **Recommended polling**: `GET /api/dashboard` cada 3-4 segundos
- **Optimistic UI**: NO — los datos cambian con cada tick del mercado
- **Caching**: NO cachear. Datos son volátiles.
- **Real-time**: Polling. WebSocket pendiente para v2.
- **CORS**: Habilitado para todos los orígenes en dev.
- **OpenAPI docs**: Disponibles en `http://localhost:8000/docs`

## Test Scenarios
1. **Happy path**: Fetch `/api/dashboard` → renderizar precio, indicadores, scores
2. **Sin señal activa**: `active_signal` es `null` → mostrar "Esperando confluencia"
3. **Circuit Breaker activo**: `risk.can_trade` = false → mostrar warning visual
4. **Black Swan**: `ai.panic_mode` = true → mostrar alerta roja prominente
5. **Trailing SL movido**: `active_signal.trailing_phase` cambia de INITIAL a BREAKEVEN → actualizar badge

## Open Questions / TODOs
- WebSocket real-time para v2 (eliminar polling)
- Autenticación JWT para producción
- Endpoint POST para configurar parámetros en vivo
