# ui/pages/portfolio.py
import streamlit as st
import pandas as pd
from datetime import datetime
from core.secure_vault import SecureVault
from portfolio.analyzer import PortfolioAnalyzer
from ai.advisor import AIAdvisor
from ai.sentiment import NewsAggregator

def card(label: str, value: str, sub: str = "", badge: str = ""):
    """Helper para crear tarjetas con estética Quantum Noir."""
    b_class = f"badge-{badge}" if badge else ""
    st.markdown(f"""
    <div class="titanium-card">
        <div class="metric-label">{label}</div>
        <div class="metric-value">{value}</div>
        <div class="metric-sub">{sub}</div>
        {f'<div class="badge {b_class}">{badge}</div>' if badge else ''}
    </div>
    """, unsafe_allow_html=True)

def page_portfolio():
    st.markdown('<div class="titanium-header" style="font-size: 32px; letter-spacing: -1px;">💼 Portafolio & IA Advisor</div>', True)
    
    # Estado de conexión
    username = st.session_state.get('username', '')
    try:
        vault = SecureVault()
    except:
        vault = None
        
    demo_mode = st.session_state.get('demo_mode', True)
    
    if demo_mode:
        st.info("🔒 Modo DEMO: Mostrando datos simulados. Configura tus API keys en Ajustes para análisis real.")
        # Datos mock
        portfolio = pd.DataFrame([
            {"asset": "BTC", "balance": 0.15, "price_usdt": 65000, "usd_value": 9750, "pct_of_portfolio": 65.0},
            {"asset": "ETH", "balance": 1.2, "price_usdt": 3500, "usd_value": 4200, "pct_of_portfolio": 28.0},
            {"asset": "SOL", "balance": 10, "price_usdt": 150, "usd_value": 1500, "pct_of_portfolio": 10.0},
        ])
        metrics = {
            "total_usd": 15450, "num_assets": 3, "concentration_pct": 65,
            "diversification_score": 35, "largest_position": "BTC", "needs_rebalance": True
        }
    else:
        if not vault:
            st.error("Error: Vault no inicializado.")
            return
        try:
            api_key, api_secret = vault.retrieve(username)
            if not api_key:
                st.warning("No se encontraron API Keys. Cambia a modo DEMO o configura las llaves.")
                return
            analyzer = PortfolioAnalyzer(api_key, api_secret, sandbox=False)
            portfolio = analyzer.get_balances(min_usd=5.0)
            metrics = analyzer.get_portfolio_metrics(portfolio)
        except Exception as e:
            st.error(f"Error conectando al exchange: {e}")
            return

    # ── Métricas Superiores ──
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        card("Valor Total", f"${metrics['total_usd']:,.2f}", badge="blue")
    with c2:
        color = "green" if metrics['diversification_score'] > 70 else "yellow" if metrics['diversification_score'] > 40 else "red"
        card("Diversificación", f"{metrics['diversification_score']}/100", badge=color)
    with c3:
        color = "red" if metrics['needs_rebalance'] else "green"
        card("Concentración", f"{metrics['concentration_pct']}% en {metrics['largest_position']}", badge=color)
    with c4:
        card("Activos", str(metrics['num_assets']), sub="Posiciones activas", badge="blue")

    # ── Tabla de Posiciones ──
    st.markdown("### 💼 Tus Posiciones")
    if not portfolio.empty:
        # Añadir cambios 24h mock o reales
        if demo_mode:
            portfolio['change_24h'] = ["+2.4%", "-1.2%", "+5.6%"]
        else:
            portfolio['change_24h'] = ["—"] * len(portfolio)
            
        st.dataframe(
            portfolio[['asset', 'balance', 'price_usdt', 'usd_value', 'pct_of_portfolio', 'change_24h']],
            column_config={
                "asset": "Activo",
                "balance": st.column_config.NumberColumn("Balance", format="%.4f"),
                "price_usdt": st.column_config.NumberColumn("Precio USDT", format="$%.2f"),
                "usd_value": st.column_config.NumberColumn("Valor USD", format="$%.2f"),
                "pct_of_portfolio": st.column_config.NumberColumn("% Portafolio", format="%.1f%%"),
                "change_24h": "24h %"
            },
            hide_index=True,
            use_container_width=True
        )
    else:
        st.warning("No se encontraron posiciones con valor significativo.")

    # ── AI Advisor Section ──
    st.markdown("---")
    st.markdown("### 🤖 AI Investment Advisor")
    
    if st.button("🚀 Generar Análisis Completo", use_container_width=True, type="primary"):
        with st.spinner("Analizando portafolio + mercado + noticias..."):
            news = NewsAggregator()
            context = news.get_market_context()
            
            market_ctx = {
                "regime": st.session_state.get('regime_data', {}).get('regime', 'TREND'),
                "sentiment_label": context['sentiment_label'],
                "sentiment_score": context['sentiment_score'],
                "circuit_breaker": st.session_state.get('circuit_breaker', {}).get_status() if 'circuit_breaker' in st.session_state else {"can_trade": True}
            }
            
            advisor = AIAdvisor()
            analysis = advisor.generate_portfolio_analysis(
                portfolio_df=portfolio,
                market_context=market_ctx,
                news_summary=" | ".join(context['raw_titles'][:3]),
                user_risk_profile="moderate"
            )
            
            st.session_state.last_analysis = analysis
            st.session_state.last_news = context

    # Mostrar resultado si existe
    if 'last_analysis' in st.session_state:
        analysis = st.session_state.last_analysis
        news_ctx = st.session_state.get('last_news', {})
        
        # Health Score visual
        score = analysis.get('health_score', 50)
        score_color = "green" if score >= 70 else "yellow" if score >= 50 else "red"
        card("Portfolio Health", f"{score}/100", sub=analysis.get('summary', ''), badge=score_color)
        
        # Risk badge
        risk = analysis.get('risk_level', 'medium')
        risk_color = "green" if risk == 'low' else "yellow" if risk == 'medium' else "red"
        card("Risk Exposure", risk.upper(), badge=risk_color)
        
        # Acciones recomendadas
        st.markdown("#### 📋 Tactical Recommendations")
        for i, action in enumerate(analysis.get('actions', []), 1):
            act_type = action['action'].lower()
            accent = "#00ffa3" if act_type in ['buy', 'stake'] else "#ff2d55" if act_type in ['sell'] else "#00e5ff"
            st.markdown(f"""
            <div class="titanium-card" style="border-left: 4px solid {accent}; margin-bottom: 15px;">
                <div style="font-weight: 700; font-size: 16px;">#{i} {act_type.upper()} {action['asset']} — Size: {action['size']}</div>
                <div style="color: rgba(255,255,255,0.7); font-size: 13px; margin-top: 5px;">{action['rationale']}</div>
            </div>
            """, unsafe_allow_html=True)
        
        # Oportunidad
        if 'opportunity' in analysis:
            st.info(f"🎯 **72h Alpha:** {analysis['opportunity']}")
        
        # Alertas
        if analysis.get('warnings'):
            for w in analysis['warnings']:
                st.warning(f"⚠️ {w}")
        
        # Contexto de noticias
        with st.expander("📰 Market Context News"):
            for h in news_ctx.get('headlines', []):
                st.markdown(f"- **[{h['source'].upper()}]** {h['title']}")

    # Briefing de mercado
    st.markdown("---")
    if st.button("📊 Generar Briefing de Mercado", use_container_width=True):
        with st.spinner("Consultando inteligencia de mercado..."):
            news = NewsAggregator()
            ctx = news.get_market_context()
            advisor = AIAdvisor()
            brief = advisor.generate_market_brief(ctx['raw_titles'], st.session_state.get('regime_data', {}).get('regime', 'TREND'))
            st.markdown(f"""
            <div class="titanium-card">
                <div class="metric-label">Institutional Market Brief</div>
                <div style="font-size: 14px; line-height: 1.6; color: #e2e8f0; font-family: 'Outfit', sans-serif;">{brief}</div>
            </div>
            """, unsafe_allow_html=True)
