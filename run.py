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
    print("[*] Verificando dependencias...")
    subprocess.run([python_exe, "-m", "pip", "install", "-r", requirements, "--quiet"])

    # 5. Lanzar Terminal Bloomberg
    print("[✓] Lanzando Terminal en http://localhost:8501")
    try:
        subprocess.run([streamlit_exe, "run", app_script])
    except KeyboardInterrupt:
        print("\n[!] Terminal detenida por el usuario.")

if __name__ == "__main__":
    main()
