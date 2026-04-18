@echo off
color 0A
title TITANIUM v8.0 PRO - CONTROL CENTER

echo ==================================================================
echo         ___ ______ ___    __  ______________  __ __
echo        /   /_  __/  / |  / / /_  __/  _/ __ \/ // /
echo       / /_  / /    /  | / /   / /  / // / / / // /
echo      / __/ / /    / / |/ /   / / _/ // /_/ /_  _/
echo     /_/   /_/    /_/|___/   /_/ /___/\____/ /_/
echo.
echo     TITANIUM v8.0 PRO - INSTITUTIONAL TRADING SYSTEM
echo ==================================================================
echo.

echo [1/3] Preparando base de datos SQLite (MCP Engine)...
:: Esto asegura que los archivos necesarios existen
if not exist "datos_trading.db" (
    echo [*] Inicializando Base de Datos nueva...
)

echo.
echo [2/3] Levantando Backend (API REST + Motor de trading)...
:: Levantamos uvicorn en una ventana de comandos nueva y en segundo plano
start "Titanium API (Motor)" cmd /k "chcp 65001 >nul && uvicorn api_server:app --host 0.0.0.0 --port 8000"

echo      [*] Esperando 6 segundos a que el motor arranque y sincronice...
timeout /t 6 /nobreak >nul

echo.
echo [3/3] Levantando Web Dashboard Institucional...
:: Lanzamos el panel usando streamlit
start "Titanium PRO Dashboard" cmd /c "chcp 65001 >nul && streamlit run web_dashboard.py --server.port 8501"

echo.
echo ==================================================================
echo                       ESTADO DEL SISTEMA
echo ==================================================================
echo  [OK] El ecosistema de TITANIUM esta ONLINE.
echo.
echo  - Panel de Control : http://localhost:8501
echo  - Swagger API Docs : http://localhost:8000/docs
echo  - Base de datos MCP: datos_trading.db (Lista para Claude/Cursor)
echo.
echo IMPORTANTE: No cierres esta ventana. 
echo Si quieres apagar por completo el bot y la interfaz...
echo.
pause
echo Apagando todo el ecosistema...
taskkill /F /FI "WINDOWTITLE eq Titanium API (Motor)*" /T >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq Titanium PRO Dashboard*" /T >nul 2>&1
taskkill /FI "WINDOWTITLE eq streamlit*" /F /T >nul 2>&1
echo TITANIUM se ha cerrado de forma segura.
exit
