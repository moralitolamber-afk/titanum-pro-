import os
import sys
import subprocess
import shutil

def main():
    # Detectar la ruta absoluta del script para evitar errores de directorio (CWD)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base_dir) # Cambiar al directorio del proyecto automáticamente
    
    print(f"🚀 TITANIUM PRO — Iniciando Motor Python en {base_dir}...")
    
    # 1. Rutas locales
    venv_path = os.path.join(base_dir, ".venv")
    requirements = os.path.join(base_dir, "requirements.txt")
    app_script = os.path.join(base_dir, "app.py")
    
    # 2. Crear VENV si no existe
    if not os.path.exists(venv_path):
        print("[!] Creando entorno virtual aislado...")
        subprocess.run([sys.executable, "-m", "venv", ".venv"])

    # 3. Determinar el ejecutable de Python y Streamlit en el VENV
    if os.name == 'nt': # Windows
        python_exe = os.path.join(venv_path, "Scripts", "python.exe")
        streamlit_exe = os.path.join(venv_path, "Scripts", "streamlit.exe")
    else: # Linux/Mac
        python_exe = os.path.join(venv_path, "bin", "python")
        streamlit_exe = os.path.join(venv_path, "bin", "streamlit")

    # 4. Instalar dependencias si es necesario
    print("[*] Sincronizando entorno profesional...")
    subprocess.run([python_exe, "-m", "pip", "install", "-r", requirements, "--quiet"])

    # 5. Checklist de Salud del Sistema
    print("\n" + "="*40)
    print(" 🛡️  AUDITORÍA DE SALUD TITANIUM PRO")
    print("-" * 40)
    print(f" 🧠 CEREBRO IA:   {'CONECTADO ✅' if os.getenv('GROQ_API_KEY') else 'SIN CLAVE ⚠️'}")
    print(f" 🔌 EXCHANGE:    {'LISTO ✅' if os.getenv('BINANCE_API_KEY') else 'DEMO MODE 💡'}")
    print(f" 📦 ENTORNO:     {'AISLADO (.venv) ✅'}")
    print(f" 📝 CONFIG:      {'.env ACTIVADO ✅' if os.path.exists('.env') else 'PENDIENTE ⚠️'}")
    print("="*40 + "\n")

    # 6. Lanzar Terminal Bloomberg
    print(f"[✓] Iniciando Streamlit desde: {app_script}")
    try:
        subprocess.run([streamlit_exe, "run", app_script, "--server.headless", "true"])
    except KeyboardInterrupt:
        print("\n[!] Motor detenido por el usuario.")

if __name__ == "__main__":
    main()
