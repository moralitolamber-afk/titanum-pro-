# ai/sentiment.py
import feedparser
import requests
from typing import List, Dict
from bs4 import BeautifulSoup

class NewsAggregator:
    """Agrega noticias de múltiples fuentes y extrae sentimiento básico."""

    SOURCES = [
        "https://cointelegraph.com/rss",
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "https://decrypt.co/feed"
    ]

    def fetch_headlines(self, limit: int = 10) -> List[Dict]:
        headlines = []
        for url in self.SOURCES:
            try:
                parsed = feedparser.parse(url)
                if not parsed.entries:
                    # Fallback for sites that might block standard feedparser
                    resp = requests.get(url, timeout=5, headers={'User-Agent': 'Mozilla/5.0'})
                    parsed = feedparser.parse(resp.content)
                
                for entry in parsed.entries[:limit]:
                    headlines.append({
                        "title": entry.title,
                        "link": entry.get('link', ''),
                        "published": entry.get('published', ''),
                        "source": url.split('/')[2]
                    })
            except Exception as e:
                print(f"Error fetching from {url}: {e}")
                continue
        return headlines[:limit]

    def get_market_context(self) -> Dict:
        """Obtiene contexto rápido para el advisor."""
        headlines = self.fetch_headlines(5)
        titles = [h['title'] for h in headlines]
        
        # Análisis de sentimiento simple basado en palabras clave
        bullish = ['rally', 'surge', 'bull', 'adoption', 'breakthrough', ' ATH', 'rise', 'long']
        bearish = ['crash', 'drop', 'bear', 'hack', 'sec', 'lawsuit', 'ban', 'fall', 'short']
        
        text = " ".join(titles).lower()
        b_score = sum(1 for w in bullish if w in text)
        be_score = sum(1 for w in bearish if w in text)
        
        total = b_score + be_score
        score = (b_score - be_score) / max(total, 1)
        
        return {
            "headlines": headlines,
            "sentiment_score": round(score, 2),
            "sentiment_label": "BULLISH" if score > 0.2 else "BEARISH" if score < -0.2 else "NEUTRAL",
            "raw_titles": titles
        }
