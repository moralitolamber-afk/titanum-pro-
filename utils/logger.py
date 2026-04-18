"""Logger de señales a SQLite y CSV para tracking de rendimiento."""
import csv
import os
import sqlite3
from datetime import datetime

import config

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'datos_trading.db')

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS signals (
            signal_id TEXT PRIMARY KEY,
            timestamp TEXT,
            direction TEXT,
            score INTEGER,
            entry REAL,
            stop_loss REAL,
            take_profit REAL,
            risk_reward REAL,
            status TEXT,
            breakdown TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS portfolio_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            daily_pnl_pct REAL,
            total_pnl_pct REAL,
            win_rate REAL,
            total_trades INTEGER,
            consecutive_losses INTEGER,
            kelly_pct REAL
        )
    ''')
    conn.commit()
    conn.close()

# Inicializar Base de Datos al cargar
init_db()

def log_portfolio_snapshot(risk_status_dict):
    """Guardar métricas globales del portafolio en la Base de Datos para el motor MCP"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO portfolio_snapshots 
            (timestamp, daily_pnl_pct, total_pnl_pct, win_rate, total_trades, consecutive_losses, kelly_pct)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            datetime.now().isoformat(),
            risk_status_dict.get('daily_pnl_pct', 0),
            risk_status_dict.get('total_pnl_pct', 0),
            risk_status_dict.get('win_rate', 0),
            risk_status_dict.get('total_trades', 0),
            risk_status_dict.get('consecutive_losses', 0),
            risk_status_dict.get('kelly_pct', 0)
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        pass


def log_signal(signal):
    """Guardar señal en Base de Datos SQLite (MCP) y CSV diario."""
    if hasattr(config, 'LOG_SIGNALS') and not config.LOG_SIGNALS:
        return

    bd_str = ' | '.join(f"{k}:{v[0]}/{v[1]}" for k, v in signal.breakdown.items())

    # --- GUARDAR EN MODO SQLITE (Para MCP) ---
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
        INSERT OR REPLACE INTO signals 
        (signal_id, timestamp, direction, score, entry, stop_loss, take_profit, risk_reward, status, breakdown)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            signal.signal_id,
            signal.timestamp.isoformat(),
            signal.direction,
            signal.score,
            signal.entry,
            signal.stop_loss,
            signal.take_profit,
            signal.risk_reward,
            signal.status,
            bd_str
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error guardando en BD: {e}")

    # --- GUARDAR EN CSV (Modo actual) ---
    os.makedirs(config.LOG_DIR, exist_ok=True)
    path = os.path.join(config.LOG_DIR, f"signals_{datetime.now().strftime('%Y%m%d')}.csv")
    exists = os.path.exists(path)

    with open(path, 'a', newline='') as f:
        w = csv.writer(f)
        if not exists:
            w.writerow([
                'timestamp', 'direction', 'score', 'entry',
                'sl', 'tp', 'rr', 'atr', 'status', 'breakdown'
            ])
        w.writerow([
            signal.timestamp.isoformat(), signal.direction, signal.score,
            signal.entry, signal.stop_loss, signal.take_profit,
            signal.risk_reward, signal.atr, signal.status, bd_str
        ])
