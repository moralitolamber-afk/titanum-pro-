import os
import sys

# Añadir el path del proyecto
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.ai_brain import AIBrain
from rich.console import Console
from rich.panel import Panel

console = Console()

def test_ai():
    console.print("[bold cyan]*** Iniciando Escaneo Global de Noticias (Black Swan AI) ***[/bold cyan]")
    
    brain = AIBrain()
    
    # Pruebas de conexión
    if not brain.api_key:
        console.print("[bold red][ERROR] No se encontró la API KEY de Groq en el ambiente.[/bold red]")
        return

    # Forzar análisis
    brain.sentiment_state["last_check"] = 0 
    status = brain.analyze_sentiment()
    
    console.print("\n[bold green][OK] Análisis Completado con Exito[/bold green]")
    
    color = "red" if status["panic_mode"] else "green"
    icon = "!!!" if status["panic_mode"] else ">>>"
    
    panel_content = f"""
    [bold underline]Estado del Mercado:[/bold underline] {icon} {'PANICO DETECTADO' if status['panic_mode'] else 'MANTENER OPERACION'}
    
    [bold]Razon IA:[/bold] {status['reason']}
    [bold]Sentiment Score:[/bold] {status['score']}/100
    
    [dim]Analisis realizado mediante Groq Llama-3-8B optimizado para Titanium Pro.[/dim]
    """
    
    console.print(Panel(panel_content, title="TITANIUM AI BRAIN - RESULTADOS", border_style=color))

if __name__ == "__main__":
    test_ai()
