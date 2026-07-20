import streamlit as st
import yfinance as yf
import logging
import re
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from google import genai
from google.genai import types
import io

# Setup
logging.getLogger('yfinance').setLevel(logging.CRITICAL)
st.set_page_config(page_title="Gatekeeper App")

st.title("The Gatekeeper Institutional App")
ticker = st.text_input("Enter Ticker Symbol (e.g. BLUSPRING, TATAMOTORS):", "BLUSPRING")

if st.button("Generate & Download Report"):
    # [Paste your fetch_stock_data and generate_report_content functions here]
    # Note: Replace 'files.download(pdf_name)' with the following:
    with open(pdf_name, "rb") as pdf_file:
        PDFbyte = pdf_file.read()
    st.download_button(label="Download PDF Report", data=PDFbyte, file_name=pdf_name, mime='application/pdf')