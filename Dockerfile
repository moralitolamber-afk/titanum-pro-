# Usar una imagen de Python ligera
FROM python:3.12-slim

# Evitar que Python genere archivos .pyc y forzar logs en tiempo real
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Configurar directorio de trabajo
WORKDIR /app

# Instalar dependencias del sistema necesarias para TA-Lib o compilaciones
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    software-properties-common \
    && rm -rf /var/lib/apt/lists/*

# Copiar requerimientos e instalar (Caché optimizado)
COPY requirements.txt .

# Instalación de dependencias (Incluyendo las visuales para el Dashboard)
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir streamlit plotly streamlit-autorefresh

# Copiar el resto del proyecto
COPY . .

# Railway usa la variable de entorno $PORT. Configuramos Streamlit para usarla.
EXPOSE 8501

# Comando para arrancar el Dashboard en el puerto dinámico de Railway
CMD ["sh", "-c", "streamlit run web_dashboard.py --server.port ${PORT:-8501} --server.address 0.0.0.0"]
