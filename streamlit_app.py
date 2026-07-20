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

# 2. CORE LOGIC FUNCTIONS
def fetch_stock_data(ticker_symbol):
    ticker_upper = ticker_symbol.upper().strip()
    info = None
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
    
    try:
        fin = stock.financials
        if fin is not None and not fin.empty and 'Net Income' in fin.index:
            ni_data = fin.loc['Net Income'].dropna()
            if len(ni_data) >= 2: metrics['net_income_trend'] = f"Net income moved from INR {ni_data.iloc[-1]:,.0f} to INR {ni_data.iloc[0]:,.0f}."
            else: metrics['net_income_trend'] = "Insufficient historical net income data."
        else: metrics['net_income_trend'] = "No historical net income available."
        bs = stock.balance_sheet
        if bs is not None and not bs.empty and 'Total Debt' in bs.index:
            td_data = bs.loc['Total Debt'].dropna()
            if len(td_data) >= 2: metrics['debt_trend'] = f"Total Debt moved from INR {td_data.iloc[-1]:,.0f} to INR {td_data.iloc[0]:,.0f}."
            else: metrics['debt_trend'] = "Insufficient historical debt data."
        else: metrics['debt_trend'] = "No historical debt available."
    except Exception: metrics['net_income_trend'] = metrics['debt_trend'] = "Could not fetch history."
    return metrics

def generate_report_content(ticker, metrics):
    client = genai.Client(api_key=st.secrets["API_KEY"])
    system_instruction = """
    Act as a ruthless institutional gatekeeper and trend analyst. 
    Begin with: DYNAMIC_SECTOR, DYNAMIC_RATING, DYNAMIC_DURATION.
    Use headers: COMPANY OVERVIEW, FUNDAMENTAL & MOMENTUM ANALYSIS, MACRO AND SECTOR CATALYSTS, KEY RISKS, ACTIONABLE VERDICT.
    ANALYST RULES: Heavily weight historical momentum (Delta Rule). 
    """
    user_prompt = f"Analyze: {ticker}. Metrics: {metrics}"
    response = client.models.generate_content(model='gemini-3.1-flash-lite', contents=user_prompt, config=types.GenerateContentConfig(system_instruction=system_instruction, temperature=0.1))
    return response.text

def build_pdf_report(pdf_buffer, ticker, metrics, ai_text):
    doc = SimpleDocTemplate(pdf_buffer, pagesize=letter, rightMargin=45, leftMargin=45, topMargin=45, bottomMargin=45)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('DocTitle', fontName='Helvetica-Bold', fontSize=24, textColor=colors.HexColor('#1A365D'))
    h1_style = ParagraphStyle('SectionH1', fontName='Helvetica-Bold', fontSize=14, textColor=colors.HexColor('#2B6CB0'), spaceBefore=15)
    body_style = ParagraphStyle('BodyText', fontName='Helvetica', fontSize=10, textColor=colors.HexColor('#2D3748'))
    table_text = ParagraphStyle('TableText', fontName='Helvetica', fontSize=9, textColor=colors.white)
    table_val = ParagraphStyle('TableVal', fontName='Helvetica-Bold', fontSize=9, textColor=colors.white)
    rating_colors = {"STRONG BUY": "#15803D", "DON'T BUY": "#DC2626", "BUY": "#172554", "HOLD": "#D97706", "SELL": "#1E3A8A"}
    
    clean_lines = []
    sector_val, duration_val, rating_val = "Growth", "N/A", "HOLD"
    for line in ai_text.split('\n'):
        if line.startswith("DYNAMIC_SECTOR:"): sector_val = line.replace("DYNAMIC_SECTOR:", "").strip()
        elif line.startswith("DYNAMIC_DURATION:"): duration_val = line.replace("DYNAMIC_DURATION:", "").strip()
        elif line.startswith("DYNAMIC_RATING:"): rating_val = line.replace("DYNAMIC_RATING:", "").strip()
        elif line.strip(): clean_lines.append(line.strip())
            
    story = [Paragraph("Smart Gains", title_style), Spacer(1, 15)]
    grid_rating = f"<font color='{rating_colors.get(rating_val, '#000000')}'><b>{rating_val}</b></font>"
    data = [[Paragraph("<b>Verdict:</b>", table_text), Paragraph(grid_rating, table_val)]]
    t = Table(data, colWidths=[100, 160])
    t.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#2B6CB0'))]))
    story.append(t); story.append(Spacer(1, 15))
    
    for line in clean_lines:
        if any(h in line for h in ["COMPANY OVERVIEW", "FUNDAMENTAL & MOMENTUM ANALYSIS", "MACRO AND SECTOR CATALYSTS", "KEY RISKS", "ACTIONABLE VERDICT"]):
            story.append(Paragraph(line, h1_style))
        else: story.append(Paragraph(line, body_style))
    doc.build(story)

# 3. STREAMLIT INTERFACE
if 'report_data' not in st.session_state: st.session_state.report_data = None

st.title("The Gatekeeper Institutional App")
ticker_input = st.text_input("Enter Ticker Symbol:", "BLUSPRING")

if st.button("Generate Report"):
    with st.spinner('Running Gatekeeper Engine...'):
        try:
            metrics = fetch_stock_data(ticker_input)
            ai_text = generate_report_content(ticker_input, metrics)
            st.session_state.report_data = {"metrics": metrics, "ai_text": ai_text, "ticker": ticker_input}
        except Exception as e: st.error(f"Error: {e}")

if st.session_state.report_data:
    data = st.session_state.report_data
    st.subheader("Market Metrics")
    st.table({"Metric": ["Price", "P/E", "Debt/Equity", "Margin", "Cap"], "Value": [data['metrics']['price'], data['metrics']['pe_ratio'], data['metrics']['debt_to_equity'], data['metrics']['net_margin'], data['metrics']['market_cap']]})
    
    display_text = re.sub(r'DYNAMIC_.*?\n', '', data['ai_text'])
    for h in ["COMPANY OVERVIEW", "FUNDAMENTAL & MOMENTUM ANALYSIS", "MACRO AND SECTOR CATALYSTS", "KEY RISKS", "ACTIONABLE VERDICT"]:
        display_text = display_text.replace(h, f"\n### {h}")
    st.markdown(display_text)
    
    pdf_buffer = io.BytesIO()
    build_pdf_report(pdf_buffer, data['ticker'], data['metrics'], data['ai_text'])
    pdf_buffer.seek(0)
    st.download_button("📥 Download Official PDF Report", data=pdf_buffer, file_name=f"{data['ticker']}_Report.pdf", mime="application/pdf")
