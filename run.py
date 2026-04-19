import os
import sys
import subprocess
import shutil

def main():
    print("🚀 TITANIUM PRO — Iniciando Motor Python...")
    
    # 1. Rutas
    venv_path = os.path.join(os.getcwd(), ".venv")
    requirements = "requirements.txt"
    
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
        subprocess.run([streamlit_exe, "run", "app.py"])
    except KeyboardInterrupt:
        print("\n[!] Terminal detenida por el usuario.")

if __name__ == "__main__":
    main()
