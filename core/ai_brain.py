"""
Cerebro de IA - Detector de Cisnes Negros (Black Swans)
Usa Groq API (modelos ultra rápidos) para analizar titulares RSS
y detectar pánico en el mercado en tiempo real.
"""
import os
import json
import time
import asyncio
import feedparser
from groq import Groq

# Configuración RSS
RSS_FEEDS = [
    "https://cointelegraph.com/rss",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
]

class AIBrain:
    def __init__(self):
        self.api_key = os.getenv("GROQ_API_KEY")
        self.client = Groq(api_key=self.api_key) if self.api_key else None
        
        self.sentiment_state = {
            "panic_mode": False,
            "reason": "OK. Analizando mercado...",
            "score": 50,  # 0 = Pánico máximo, 100 = Euforia máxima
            "last_check": 0
        }
        
    def analyze_sentiment(self):
        """Descarga noticias en segundo plano y las envía a Groq."""
        if not self.client:
            self.sentiment_state["reason"] = "Inactivo. Falta GROQ_API_KEY en .env"
            return self.sentiment_state
            
        now = time.time()
        # Limitar llamadas a Groq: chequear cada 5 minutos
        if (now - self.sentiment_state["last_check"]) < 300:
            return self.sentiment_state

        print("🧠 [AI BRAIN] Descargando últimas noticias mundiales...")
        
        # 1. Obtener titulares
        headlines = []
        for feed_url in RSS_FEEDS:
            try:
                # Se podría hacer async con aiohttp, pero feedparser.parse es bloqueante.
                # Para simplificar y ya que corre espaciado, corremos al loop de asyncio si es necesario, 
                # o lo dejamos simple.
                feed = feedparser.parse(feed_url)
                for entry in feed.entries[:5]: # últimos 5 de cada feed
                    headlines.append(f"- {entry.title}")
            except Exception as e:
                pass
                
        if not headlines:
            self.sentiment_state["last_check"] = now
            return self.sentiment_state
            
        news_text = "\\n".join(headlines)

        # 2. Consultar a Groq
        prompt = f"""
Eres el 'Black Swan Detector' de TITANIUM, un bot de trading algorítmico.
Tu tarea es leer los siguientes titulares recientes del mercado financiero/cripto y determinar SI HAY PÁNICO (CISNE NEGRO).
Si hay guerras, hacks masivos de exchanges TOP, caídas bruscas, arrestos de CEOs importantes, la Reserva Federal subiendo tasas de emergencia, etc -> pánico.

Titulares recientes:
{news_text}

Responde ÚNICAMENTE con un JSON válido usando esta estructura estructural (sin markdown tags):
{{
    "panic_mode": true/false, // true SOLO si es una catástrofe que requiera apagar el bot
    "reason": "Resumen conciso en español (máx 10 palabras)",
    "score": 0 a 100 // 0 = Caos total, 50 = Normal, 100 = Bull market total
}}
"""
        try:
            # Usar llama3-8b-8192 o llama3-70b-8192 por su velocidad brutal
            completion = self.client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "You are a helpful JSON-only output assistant."},
                    {"role": "user", "content": prompt}
                ],
                model="llama3-8b-8192",
                temperature=0.0,
                max_tokens=200,
            )
            
            response_text = completion.choices[0].message.content.strip()
            # Limpiar posible markdown en la respuesta de groq
            if response_text.startswith("```json"):
                response_text = response_text[7:-3]
            elif response_text.startswith("```"):
                response_text = response_text[3:-3]
                
            data = json.loads(response_text)
            
            self.sentiment_state["panic_mode"] = bool(data.get("panic_mode", False))
            self.sentiment_state["reason"]     = str(data.get("reason", "Unknown"))
            self.sentiment_state["score"]      = int(data.get("score", 50))
            self.sentiment_state["last_check"] = now
            
        except Exception as e:
            self.sentiment_state["reason"] = f"Error IA: {str(e)[:30]}"
            
        return self.sentiment_state

