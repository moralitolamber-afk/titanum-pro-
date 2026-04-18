# ai/advisor.py
import json
import os
from typing import Dict, List
import pandas as pd
from groq import Groq

class AIAdvisor:
    """Procesador de inteligencia para recomendaciones de inversión."""

    def __init__(self):
        self.api_key = os.getenv("GROQ_API_KEY")
        self.model = "llama-3.3-70b-versatile"

    def generate_portfolio_analysis(self, portfolio_df: pd.DataFrame, market_context: Dict, 
                                  news_summary: str, user_risk_profile: str = "moderate") -> Dict:
        if not self.api_key:
            return {"error": "API Key no configurada"}

        client = Groq(api_key=self.api_key)
        
        portfolio_json = portfolio_df.to_json(orient='records')
        
        prompt = f"""
        Actúa como un Portfolio Manager institucional senior de Criptoactivos.
        Analiza el portafolio del usuario y el contexto de mercado para generar recomendaciones tácticas.

        DIAGNÓSTICO TÉCNICO:
        - Portafolio: {portfolio_json}
        - Contexto Mercado: {json.dumps(market_context)}
        - Noticias Recientes: {news_summary}
        - Perfil de Riesgo: {user_risk_profile}

        """
        
        circuit_status = market_context.get('circuit_breaker', {})
        if not circuit_status.get('can_trade', True):
            prompt += "\nADVERTENCIA: El circuit breaker está ACTIVADO por pérdidas. La recomendación principal debe ser REDUCIR EXPOSICIÓN o mantener estable (USDT)."

        prompt += """
        RESPONDE ÚNICAMENTE CON UN JSON VÁLIDO CON ESTA ESTRUCTURA:
        {{
            "health_score": <int 0-100>,
            "risk_level": "low|medium|high",
            "summary": "<Resumen ejecutivo de 30 palabras>",
            "actions": [
                {{ "asset": "TICKER", "action": "buy|sell|hold|stake", "size": "10%", "rationale": "motivo" }}
            ],
            "opportunity": "<Oportunidad específica para las próximas 72h>",
            "warnings": ["lista de riesgos críticos detectados"]
        }}
        """
        
        try:
            resp = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            return json.loads(resp.choices[0].message.content)
        except Exception as e:
            return {"error": f"Fallo en IA: {str(e)}", "health_score": 0, "actions": []}

    def generate_market_brief(self, headlines: List[str], current_regime: str) -> str:
        if not self.api_key:
            return "Servicio de inteligencia no disponible."

        client = Groq(api_key=self.api_key)
        news_text = " | ".join(headlines)
        
        prompt = f"""
        Como analista macro de cripto, genera un briefing de mercado ultraconciso (50 palabras max).
        Contexto: {news_text}
        Régimen detectado: {current_regime}
        """
        
        try:
            resp = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}]
            )
            return resp.choices[0].message.content.strip()
        except Exception:
            return "No se pudo generar el briefing en este momento."
