FROM python:3.10-slim

WORKDIR /app

# Instalar dependencias del sistema requeridas
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    software-properties-common \
    && rm -rf /var/lib/apt/lists/*

# Copiar configuración de dependencias
COPY requirements.txt .

# Instalar los paquetes Python (sin usar caché para que el contenedor quede ligero)
RUN pip3 install --no-cache-dir -r requirements.txt

# Copiar el ecosistema TITANIUM
COPY . .

# Exponer el puerto del Dashboard Streamlit
EXPOSE 8501

# Comando por defecto para correr el motor y la UI
ENTRYPOINT ["streamlit", "run", "web_dashboard.py", "--server.port=8501", "--server.address=0.0.0.0"]
