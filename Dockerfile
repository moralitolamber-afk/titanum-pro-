# Imagen base oficial de Python ligera
FROM python:3.12-slim

WORKDIR /app

# Dependencias mínimas del sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copiar e instalar dependencias primero (cache eficiente)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto del código
COPY . .

# Railway inyecta dinámicamente la variable PORT. 
# Usamos el formato Shell de CMD para que pueda leer las variables de entorno.
CMD streamlit run web_dashboard.py \
    --server.port=${PORT:-8501} \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --browser.gatherUsageStats=false
