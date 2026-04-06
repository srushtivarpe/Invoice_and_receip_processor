import os
import re
import json
import requests
import streamlit as st
import pandas as pd
from datetime import datetime
from PIL import Image
import pytesseract
from pdf2image import convert_from_bytes

# ---------------- CONFIG ----------------
N8N_WEBHOOK_URL = "https://srushti-2002.app.n8n.cloud/webhook/b11299f0-8f78-42d3-9977-1dd03d8fa49a"
approved_vendors = ["ABC Tech Solutions Pvt Ltd"]

# ---------------- OCR ----------------
def extract_text(file):
    text = ""
    if file.type == "application/pdf":
        images = convert_from_bytes(file.read())
        for img in images:
            text += pytesseract.image_to_string(img)
    else:
        image = Image.open(file)
        text = pytesseract.image_to_string(image)
    return text

# ---------------- CLEAN TEXT ----------------
def clean_text(text):
    text = re.sub(r'[^\x00-\x7F]+', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.lower()
# ---------------- CLEAN TEXT ----------------
def clean_text(text):
    text = re.sub(r'[^\x00-\x7F]+', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.lower()


# ---------------- DATE EXTRACTION ----------------
def extract_date(text):
    # Strict formats like: 20 April 2024
    match = re.search(r'\b\d{1,2}\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{4}\b', text, re.IGNORECASE)
    
    if match:
        return match.group()

    # Format: 20/04/2024 or 20-04-2024
    match = re.search(r'\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b', text)
    
    if match:
        return match.group()

    return "Unknown"

# ---------------- EXTRACTION ----------------
def extract_fields(text):
    cleaned = clean_text(text)

    # Invoice Number
    inv_match = re.search(r'inv[-\s]?\d{4}[-\s]?\d+', cleaned)
    invoice_no = inv_match.group().upper() if inv_match else "Unknown"

    # Date
    date = extract_date(cleaned)

    # Vendor
    vendor_match = re.search(r'abc tech solutions pvt ltd', cleaned)
    vendor = vendor_match.group().title() if vendor_match else "Unknown Vendor"

    # Amounts
    amounts = re.findall(r'\d{1,3}(?:,\d{3})*\.\d{2}', cleaned)
    amounts = [float(a.replace(',', '')) for a in amounts]
    total_amount = max(amounts) if amounts else 0.0

    # Tax
    tax_match = re.search(r'gst.*?(\d{1,3}(?:,\d{3})*\.\d{2})', cleaned)
    tax = float(tax_match.group(1).replace(',', '')) if tax_match else 0.0

    return {
        "Document Type": "Invoice",
        "Vendor": vendor,
        "Invoice Number": invoice_no,
        "Date": date,
        "Total Amount": total_amount,
        "Taxes": tax
    }

# ---------------- ALERTS ----------------
def generate_alerts(data):
    alerts = []

    if data["Vendor"] not in approved_vendors:
        alerts.append("Unapproved Vendor")

    if data["Taxes"] > 0.3 * data["Total Amount"] and data["Total Amount"] != 0:
        alerts.append("High Tax Anomaly")

    if data["Total Amount"] == 0:
        alerts.append("Amount Extraction Failed")

    if data["Invoice Number"] == "Unknown":
        alerts.append("Missing Invoice Number")

    return alerts

# ---------------- N8N ----------------
def trigger_n8n(data, alerts):
    payload = {
        "data": data,
        "alerts": alerts
    }

    try:
        response = requests.post(N8N_WEBHOOK_URL, json=payload)
        return response.status_code
    except Exception as e:
        return str(e)

# ---------------- STREAMLIT UI ----------------
st.set_page_config(page_title="AI Document Orchestrator", layout="wide")
st.title("📄 AI Document Orchestrator - Invoice Processor")

uploaded_file = st.file_uploader("Upload Invoice (PDF/Image)", type=["pdf", "png", "jpg", "jpeg"])

if uploaded_file:
    st.info("Processing document...")

    raw_text = extract_text(uploaded_file)
    st.subheader("Extracted Text")
    st.text_area("", raw_text, height=200)

    data = extract_fields(raw_text)
    alerts = generate_alerts(data)

    st.subheader("Extracted Data")
    st.json(data)

    st.subheader("Alerts")
    if alerts:
        for alert in alerts:
            st.warning(alert)
    else:
        st.success("No issues detected")

    status = trigger_n8n(data, alerts)
    st.success(f"Webhook Status: {status}")

    # Dashboard
    st.subheader("📊 Dashboard")
    df = pd.DataFrame([data])
    st.metric("Documents", len(df))
    st.metric("Total Amount", data["Total Amount"])
    st.metric("Invoices", 1)
