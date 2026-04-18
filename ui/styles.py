# ui/styles.py

STYLES = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:wght@700;800&family=Outfit:wght@300;400;500;600&family=JetBrains+Mono:wght@500;700&display=swap');

:root {
    --bg-dark: #030305;
    --accent-blue: #00e5ff;
    --accent-purple: #ab47bc;
    --card-bg: rgba(10, 10, 15, 0.85);
    --glass-border: rgba(255, 255, 255, 0.08);
}

html, body, [class*="css"] {
    font-family: 'Outfit', sans-serif;
    color: #f1f5f9;
}

.stApp {
    background-color: var(--bg-dark);
    background-image: 
        radial-gradient(circle at 10% 10%, rgba(0, 229, 255, 0.08) 0%, transparent 35%),
        radial-gradient(circle at 90% 90%, rgba(171, 71, 188, 0.08) 0%, transparent 35%),
        url("https://www.transparenttextures.com/patterns/black-linen.png");
    background-attachment: fixed;
}

.titanium-card {
    background: var(--card-bg);
    border: 1px solid var(--glass-border);
    border-radius: 2px;
    padding: 24px;
    backdrop-filter: blur(40px) saturate(180%);
    box-shadow: 0 4px 20px rgba(0,0,0,0.6);
    transition: 400ms cubic-bezier(0.16, 1, 0.3, 1);
    position: relative;
    overflow: hidden;
    cursor: pointer;
    margin-bottom: 20px;
}
.titanium-card:hover {
    border-color: var(--accent-blue);
    transform: translateY(-4px);
    background: rgba(15, 15, 25, 0.95);
}

.metric-label {
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: rgba(255,255,255,0.4);
    margin-bottom: 8px;
}
.metric-value {
    font-family: 'JetBrains Mono', monospace;
    font-size: 30px;
    font-weight: 700;
    color: #ffffff;
}
.metric-sub {
    font-size: 11px;
    color: rgba(255,255,255,0.3);
    margin-top: 10px;
}

.badge {
    padding: 2px 10px;
    border-radius: 1px;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
}
.badge-green  { background: rgba(0, 255, 163, 0.1); color: #00ffa3; border-left: 2px solid #00ffa3; }
.badge-red    { background: rgba(255, 45, 85, 0.1); color: #ff2d55; border-left: 2px solid #ff2d55; }
.badge-blue   { background: rgba(0, 229, 255, 0.1); color: #00e5ff; border-left: 2px solid #00e5ff; }
.badge-yellow { background: rgba(255, 204, 0, 0.1); color: #ffcc00; border-left: 2px solid #ffcc00; }

.titanium-header {
    font-family: 'Bricolage Grotesque', sans-serif;
    font-size: 48px;
    font-weight: 800;
    letter-spacing: -3px;
    background: linear-gradient(to right, #fff, var(--accent-blue));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}

[data-testid="stSidebar"] {
    background-color: #010102 !important;
    border-right: 1px solid var(--glass-border);
}

.stButton > button {
    width: 100%;
    background: transparent;
    border: 1px solid var(--glass-border);
    border-radius: 2px;
    font-weight: 600;
    letter-spacing: 2px;
    text-transform: uppercase;
    padding: 14px;
}
.stButton > button:hover {
    border-color: var(--accent-blue);
    color: var(--accent-blue);
}
</style>
"""
