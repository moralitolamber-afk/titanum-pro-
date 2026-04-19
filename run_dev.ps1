# 🚀 TITANIUM PRO — DEV RUNNER
# Este script levanta el entorno para pruebas locales profesionales

Write-Host "--- Levantando Ecosistema Titanium ---" -ForegroundColor Cyan

# 1. Verificar Entorno Virtual
if (-not (Test-Path ".venv")) {
    Write-Host "[!] Entorno virtual no encontrado. Creando..." -ForegroundColor Yellow
    python -m venv .venv
}

# 2. Activar e Instalar
Write-Host "[*] Sincronizando dependencias..." -ForegroundColor Gray
& .venv/Scripts/Activate.ps1
pip install -r requirements.txt --quiet

# 3. Verificar Archivo .env
if (-not (Test-Path ".env")) {
    Write-Host "[!] Archivo .env no encontrado. Usando .env.example como base..." -ForegroundColor Yellow
    Copy-Item .env.example .env
}

# 4. Iniciar Terminal Bloomberg (Streamlit)
Write-Host "[✓] Lanzando Terminal Bloomberg en Modo Desarrollo..." -ForegroundColor Green
streamlit run app.py --server.port 8501
