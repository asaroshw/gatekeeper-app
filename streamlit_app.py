import streamlit as st
import yfinance as yf
import logging
import re
import io
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from google import genai
from google.genai import types

# 1. Setup
logging.getLogger('yfinance').setLevel(logging.CRITICAL)
st.set_page_config(page_title="The Gatekeeper Institutional App", layout="wide")

# 2. Logic Functions
def fetch_stock_data(ticker_symbol):
    ticker_upper = ticker_symbol.upper().strip()
    # Try NSE/BSE
    if not ticker_upper.endswith(('.NS', '.BO')):
        try:
            stock = yf.Ticker(ticker_upper + '.NS')
            info = stock.info
            if 'currentPrice' not in info: raise ValueError
        except Exception:
            try:
                stock = yf.Ticker(ticker_upper + '.BO')
                info = stock.info
                if 'currentPrice' not in info: raise ValueError("Ticker not found.")
            except Exception: raise ValueError("Ticker not found on NSE or BSE.")
    else:
        stock = yf.Ticker(ticker_upper)
        info = stock.info
        if 'currentPrice' not in info: raise ValueError("Ticker not found.")
            
    metrics = {
        "name": info.get("longName", ticker_symbol),
        "price": info.get("currentPrice", "N/A"),
        "pe_ratio": info.get("trailingPE", "N/A"),
        "debt_to_equity": info.get("debtToEquity", "N/A"),
        "net_margin": info.get("profitMargins", "N/A"),
        "market_cap": info.get("marketCap", "N/A")
    }
    if metrics["debt_to_equity"] != "N/A": metrics["debt_to_equity"] = round(metrics["debt_to_equity"] / 100, 2)
    if metrics["net_margin"] != "N/A": metrics["net_margin"] = f"{round(metrics['net_margin'] * 100, 2)}%"
    
    # Historical Data
    fin = stock.financials
    metrics['net_income_trend'] = "Data unavailable" if fin is None or 'Net Income' not in fin.index else f"Net income: {fin.loc['Net Income'].dropna().iloc[-1]:,.0f} to {fin.loc['Net Income'].dropna().iloc[0]:,.0f}"
    bs = stock.balance_sheet
    metrics['debt_trend'] = "Data unavailable" if bs is None or 'Total Debt' not in bs.index else f"Total Debt: {bs.loc['Total Debt'].dropna().iloc[-1]:,.0f} to {bs.loc['Total Debt'].dropna().iloc[0]:,.0f}"
    return metrics

def generate_report_content(ticker, metrics):
    # Security: Uses st.secrets instead of hardcoded key
    client = genai.Client(api_key=st.secrets["API_KEY"])
    
    system_instruction = """
    Act as an institutional equity research assistant. Output raw text. 
    Begin with: DYNAMIC_SECTOR, DYNAMIC_RATING, DYNAMIC_DURATION.
    Use headers: COMPANY OVERVIEW, FUNDAMENTAL & MOMENTUM ANALYSIS, MACRO AND SECTOR CATALYSTS, KEY RISKS, ACTIONABLE VERDICT.
    If loss-making, evaluate turnaround momentum. If liquidity trap, force DON'T BUY.
    """
    user_prompt = f"Analyze: {ticker}. Metrics: {metrics}"
    
    response = client.models.generate_content(
        model='gemini-3.1-flash-lite',
        contents=user_prompt,
        config=types.GenerateContentConfig(system_instruction=system_instruction, temperature=0.1)
    )
    return response.text

def build_pdf_report(pdf_buffer, ticker, metrics, ai_text):
    doc = SimpleDocTemplate(pdf_buffer, pagesize=letter, rightMargin=45, leftMargin=45, topMargin=45, bottomMargin=45)
    styles = getSampleStyleSheet()
    
    # Styles
    title_style = ParagraphStyle('DocTitle', fontName='Helvetica-Bold', fontSize=24, textColor=colors.HexColor('#1A365D'))
    h1_style = ParagraphStyle('SectionH1', fontName='Helvetica-Bold', fontSize=14, textColor=colors.HexColor('#2B6CB0'), spaceBefore=15)
    body_style = ParagraphStyle('BodyText', fontName='Helvetica', fontSize=10, textColor=colors.HexColor('#2D3748'))
    table_text = ParagraphStyle('TableText', fontName='Helvetica', fontSize=9, textColor=colors.white)
    table_val = ParagraphStyle('TableVal', fontName='Helvetica-Bold', fontSize=9, textColor=colors.white)
    
    rating_colors = {"STRONG BUY": "#15803D", "DON'T BUY": "#DC2626", "BUY": "#172554", "HOLD": "#D97706", "SELL": "#1E3A8A"}
    
    # Parse lines
    clean_lines = []
    lines = ai_text.split('\n')
    sector, duration, rating = "Growth", "N/A", "HOLD"
    for line in lines:
        if line.startswith("DYNAMIC_SECTOR:"): sector = line.replace("DYNAMIC_SECTOR:", "").strip()
        elif line.startswith("DYNAMIC_DURATION:"): duration = line.replace("DYNAMIC_DURATION:", "").strip()
        elif line.startswith("DYNAMIC_RATING:"): rating = line.replace("DYNAMIC_RATING:", "").strip()
        elif line.strip(): clean_lines.append(line.strip())
            
    story = [Paragraph("Smart Gains", title_style), Spacer(1, 15)]
    
    # Table
    data = [[Paragraph("<b>Verdict Rating:</b>", table_text), Paragraph(f"<font color='{rating_colors.get(rating, '#000000')}'><b>{rating}</b></font>", table_val)]]
    t = Table(data, colWidths=[100, 160])
    t.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#2B6CB0'))]))
    story.append(t); story.append(Spacer(1, 15))
    
    # Content
    for line in clean_lines:
        if any(h in line for h in ["COMPANY OVERVIEW", "FUNDAMENTAL & MOMENTUM ANALYSIS", "MACRO AND SECTOR CATALYSTS", "KEY RISKS", "ACTIONABLE VERDICT"]):
            story.append(Paragraph(line, h1_style))
        else:
            processed_line = line
            for r_text in sorted(rating_colors.keys(), key=len, reverse=True):
                if r_text in processed_line.upper():
                    pattern = r'(?i)(?<![a-zA-Z])' + re.escape(r_text) + r'(?![a-zA-Z])'
                    processed_line = re.sub(pattern, f'<font color="{rating_colors[r_text]}"><b>{r_text}</b></font>', processed_line)
            story.append(Paragraph(processed_line, body_style))
            
    doc.build(story)

# 3. STREAMLIT INTERFACE
st.title("The Gatekeeper Institutional App")
ticker_input = st.text_input("Enter Ticker Symbol:", "BLUSPRING")

if st.button("Generate & Download Report"):
    with st.spinner('Running Gatekeeper Engine...'):
        try:
            metrics = fetch_stock_data(ticker_input)
            ai_text = generate_report_content(ticker_input, metrics)
            pdf_buffer = io.BytesIO()
            build_pdf_report(pdf_buffer, ticker_input, metrics, ai_text)
            pdf_buffer.seek(0)
            st.download_button("Download PDF Report", data=pdf_buffer, file_name=f"{ticker_input}_Report.pdf", mime="application/pdf")
        except Exception as e: st.error(f"Error: {e}")
