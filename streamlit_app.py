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
st.set_page_config(page_title="ASW Stock Ideas", layout="wide")

# 2. CORE LOGIC FUNCTIONS

# NEW FUNCTION: AI Ticker Resolver
def resolve_ticker_with_ai(stock_name):
    client = genai.Client(api_key=st.secrets["API_KEY"])
    search_tool = types.Tool(google_search=types.GoogleSearch())
    
    prompt = f"""
    Find the exact Yahoo Finance ticker symbol for the company or search term: '{stock_name}'.
    Rules:
    1. If it's an Indian stock listed on the NSE, return the symbol with '.NS' (e.g., 'TATAMOTORS.NS', 'ZOMATO.NS').
    2. If it's an Indian stock listed ONLY on the BSE (like Taparia Tools), find its 6-digit numeric BSE code and return it with '.BO' (e.g., '505685.BO').
    3. If it's a US stock, return the raw ticker (e.g., 'AAPL', 'MSFT').
    OUTPUT ONLY THE TICKER SYMBOL. Do not include any extra words, symbols, or explanations.
    """
    
    response = client.models.generate_content(
        model='gemini-3.1-flash-lite', 
        contents=prompt, 
        config=types.GenerateContentConfig(
            temperature=0.1,
            tools=[search_tool]
        )
    )
    return response.text.strip().replace(" ", "").upper()

def fetch_stock_data(ticker_symbol):
    ticker_upper = ticker_symbol.upper().strip()
    info = None
    
    # Try the exact AI-provided ticker first
    try:
        stock = yf.Ticker(ticker_upper)
        info = stock.info
        if 'currentPrice' not in info: raise ValueError
    except Exception:
        # Fallback just in case the AI missed the suffix
        if not ticker_upper.endswith(('.NS', '.BO')):
            try:
                stock = yf.Ticker(ticker_upper + '.NS')
                info = stock.info
                if 'currentPrice' not in info: raise ValueError
            except Exception:
                try:
                    stock = yf.Ticker(ticker_upper + '.BO')
                    info = stock.info
                    if 'currentPrice' not in info: raise ValueError("Stock not found.")
                except Exception: raise ValueError("Stock not found on NSE or BSE.")
        else:
            raise ValueError("Stock not found.")
            
    metrics = {
        "name": info.get("longName", ticker_upper),
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
    except Exception: 
        metrics['net_income_trend'] = "Could not fetch history."
        metrics['debt_trend'] = "Could not fetch history."
        
    return metrics

def generate_report_content(stock_name, metrics):
    client = genai.Client(api_key=st.secrets["API_KEY"])
    
    system_instruction = """
    Act as an automated, professional-grade equity research assistant built in the style of an institutional advisory report. You are a ruthless analyst evaluating 360-degree risk.
    Do not use any markdown tags, asterisks, or hash symbols in your response. Output raw text separated by clean line breaks.
    
    CRITICAL STRUCTURE INSTRUCTION:
    Your response MUST begin exactly with these three variables for the engine parser, substituting the brackets with values:
    DYNAMIC_SECTOR: [Insert brief industry category]
    DYNAMIC_RATING: [Insert exactly one of these: STRONG BUY, BUY, HOLD, DON'T BUY, SELL]
    DYNAMIC_DURATION: [STRICT RULE: If Rating is DON'T BUY or SELL, this MUST be "N/A". If Swing Trade/Momentum, use "1-3 Months". If Long-Term Compounder, use "3-5 Years".]
    
    Following those lines, proceed immediately to the standard report using these exact headers:
    COMPANY OVERVIEW
    FUNDAMENTAL & MOMENTUM ANALYSIS
    MACRO AND SECTOR CATALYSTS
    KEY RISKS
    ACTIONABLE VERDICT
    
    ANALYST RULES (LIVE MACRO & RISKS):
    1. You MUST use your Google Search tool to look up the most recent news, geopolitical impacts, regulatory audits (like FDA), and tariff/supply chain issues affecting this specific company and its sector today.
    2. Examples to check: For airlines/hospitality/tyres, assess crude oil price shocks and West Asian crises. For Pharma, assess FDA audits, plant inspections, and licensing. For exporters (IT/Manufacturing), assess tariffs and freight costs. For domestic players, assess import duty threats.
    3. OVERRIDE RULE: If severe macro headwinds, thin margins, geopolitical supply chain risks, or regulatory threats exist in the current news, you MUST downgrade the rating (e.g., to HOLD, DON'T BUY, or SELL), even if historical financial momentum looks excellent.
    
    VERDICT FORMATTING RULE:
    Under the ACTIONABLE VERDICT header, you must output exactly two things:
    Line 1: The DYNAMIC_RATING itself in all caps (e.g., HOLD).
    Line 2: The detailed explanation of the verdict, explicitly weighing the financials against the live macro/regulatory risks found in the news.
    """
    
    user_prompt = f"""
    Analyze this stock:
    Company Name: {metrics['name']}
    Stock Name/Ticker: {stock_name}
    Current Price: INR {metrics['price']}
    TTM P/E Ratio: {metrics['pe_ratio']}
    Debt-to-Equity Ratio: {metrics['debt_to_equity']}
    Net Profit Margin: {metrics['net_margin']}
    Market Cap: INR {metrics['market_cap']}
    
    HISTORICAL MOMENTUM METRICS:
    Net Income Trend: {metrics['net_income_trend']}
    Debt Trend: {metrics['debt_trend']}
    """
    
    search_tool = types.Tool(google_search=types.GoogleSearch())
    
    response = client.models.generate_content(
        model='gemini-3.1-flash-lite', 
        contents=user_prompt, 
        config=types.GenerateContentConfig(
            system_instruction=system_instruction, 
            temperature=0.15,
            tools=[search_tool]
        )
    )
    return response.text

def build_pdf_report(pdf_buffer, stock_name, metrics, ai_text):
    doc = SimpleDocTemplate(pdf_buffer, pagesize=letter, rightMargin=45, leftMargin=45, topMargin=45, bottomMargin=45)
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('DocTitle', fontName='Helvetica-Bold', fontSize=24, leading=28, textColor=colors.HexColor('#1A365D'))
    subtitle_style = ParagraphStyle('DocSub', fontName='Helvetica-Bold', fontSize=12, leading=16, textColor=colors.HexColor('#718096'))
    h1_style = ParagraphStyle('SectionH1', fontName='Helvetica-Bold', fontSize=14, leading=18, textColor=colors.HexColor('#2B6CB0'), spaceBefore=15, spaceAfter=8)
    body_style = ParagraphStyle('BodyTextCustom', fontName='Helvetica', fontSize=10, leading=15, textColor=colors.HexColor('#2D3748'))
    table_text = ParagraphStyle('TableText', fontName='Helvetica', fontSize=9, leading=12, textColor=colors.white)
    table_val = ParagraphStyle('TableVal', fontName='Helvetica-Bold', fontSize=9, leading=12, textColor=colors.white)
    
    rating_colors = {
        "STRONG BUY": "#15803D", "DON'T BUY": "#DC2626", "BUY": "#172554", "HOLD": "#D97706", "SELL": "#1E3A8A"
    }
    
    sector_val, duration_val, rating_val = "Growth / Cyclical", "N/A", "EVALUATED"
    clean_lines = []
    
    for line in ai_text.split('\n'):
        line_str = line.strip()
        if line_str.startswith("DYNAMIC_SECTOR:"): sector_val = line_str.replace("DYNAMIC_SECTOR:", "").strip()
        elif line_str.startswith("DYNAMIC_DURATION:"): duration_val = line_str.replace("DYNAMIC_DURATION:", "").strip()
        elif line_str.startswith("DYNAMIC_RATING:"): rating_val = line_str.replace("DYNAMIC_RATING:", "").strip()
        elif line_str: clean_lines.append(line_str)
                
    story = [
        Paragraph("ASW Stock Ideas", title_style), 
        Paragraph("Automated Equity Research Report — Institutional Series", subtitle_style),
        Spacer(1, 15)
    ]
    
    current_rating = rating_val.upper().strip()
    target_hex = rating_colors.get(current_rating, "#FFFFFF")
    grid_rating_display = f"<font color='{target_hex}'><b>{current_rating}</b></font>"
    
    data = [
        [Paragraph("<b>Company:</b>", table_text), Paragraph(str(metrics['name']), table_val), Paragraph("<b>Category:</b>", table_text), Paragraph(sector_val, table_val)],
        [Paragraph("<b>Current Price:</b>", table_text), Paragraph(f"INR {metrics['price']}", table_val), Paragraph("<b>Time Horizon:</b>", table_text), Paragraph(duration_val, table_val)],
        [Paragraph("<b>TTM P/E Ratio:</b>", table_text), Paragraph(f"{metrics['pe_ratio']}x", table_val), Paragraph("<b>Debt-to-Equity:</b>", table_text), Paragraph(str(metrics['debt_to_equity']), table_val)],
        [Paragraph("<b>Net Margin:</b>", table_text), Paragraph(str(metrics['net_margin']), table_val), Paragraph("<b>Verdict Rating:</b>", table_text), Paragraph(grid_rating_display, table_val)]
    ]
    
    t = Table(data, colWidths=[100, 160, 100, 160])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#2B6CB0')),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('LEFTPADDING', (0,0), (-1,-1), 10),
        ('RIGHTPADDING', (0,0), (-1,-1), 10),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#4299E1')),
    ]))
    story.append(t)
    story.append(Spacer(1, 15))
    
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
            story.append(Spacer(1, 4))
            
    doc.build(story)

# 3. STREAMLIT INTERFACE
if 'report_data' not in st.session_state:
    st.session_state.report_data = None

st.title("ASW Stock Ideas")
stock_input = st.text_input("Enter Stock Name (e.g., Tata Motors, Apple, Taparia Tools):", "Tata Motors")

if st.button("Generate Report"):
    with st.spinner('AI is resolving the company name to a valid ticker...'):
        try:
            # 1. Ask the AI to figure out what stock you mean
            resolved_ticker = resolve_ticker_with_ai(stock_input)
            st.success(f"Resolved '{stock_input}' to Yahoo Finance Ticker: **{resolved_ticker}**")
            
            # 2. Fetch the data using the perfectly resolved code
            with st.spinner('Fetching Data & Analyzing Live Macro Risks...'):
                metrics = fetch_stock_data(resolved_ticker)
                ai_text = generate_report_content(resolved_ticker, metrics)
                st.session_state.report_data = {"metrics": metrics, "ai_text": ai_text, "stock": stock_input, "ticker": resolved_ticker}
        except Exception as e:
            st.error(f"Error: {e}")

if st.session_state.report_data:
    data = st.session_state.report_data
    
    st.subheader("Market Metrics")
    st.table({
        "Metric": ["Price", "P/E Ratio", "Debt/Equity", "Net Margin", "Market Cap"], 
        "Value": [data['metrics']['price'], data['metrics']['pe_ratio'], data['metrics']['debt_to_equity'], data['metrics']['net_margin'], data['metrics']['market_cap']]
    })
    
    display_text = re.sub(r'DYNAMIC_.*?\n', '', data['ai_text'])
    for h in ["COMPANY OVERVIEW", "FUNDAMENTAL & MOMENTUM ANALYSIS", "MACRO AND SECTOR CATALYSTS", "KEY RISKS", "ACTIONABLE VERDICT"]:
        display_text = display_text.replace(h, f"\n### {h}")
    st.markdown("---")
    st.markdown(display_text)
    st.markdown("---")
    
    pdf_buffer = io.BytesIO()
    build_pdf_report(pdf_buffer, data['ticker'], data['metrics'], data['ai_text'])
    pdf_buffer.seek(0)
    
    st.download_button(
        label="📥 Download Official PDF Report", 
        data=pdf_buffer, 
        file_name=f"{data['ticker']}_ASW_Report.pdf", 
        mime="application/pdf"
    )
