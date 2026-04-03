import streamlit as st
import pandas as pd
from PIL import Image
import pytesseract
from datetime import datetime
import json
import re
from pdf2image import convert_from_bytes
from google import genai
import requests


# --- Tesseract Path ---
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# --- Config ---
st.set_page_config(page_title="AI Document Orchestrator", layout="wide")
st.title("📄 AI Document Orchestrator (Stable Version)")

# --- Secrets ---
GEMINI_API_KEY = st.secrets.get("gemini_api_key", "")
N8N_WEBHOOK_URL = st.secrets.get("n8n_webhook_url", "")

# --- Gemini Client ---
client = None
if GEMINI_API_KEY:
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
    except:
        client = None

# --- Session ---
if "history" not in st.session_state:
    st.session_state.history = []

# --- Upload ---
files = st.file_uploader(
    "Upload Documents (PDF / Image)",
    type=["jpg", "png", "jpeg", "pdf"],
    accept_multiple_files=True
)

# --- OCR ---
def ocr_image(img):
    return pytesseract.image_to_string(img)

def ocr_pdf(file):
    try:
        pages = convert_from_bytes(file.read(), first_page=1, last_page=2)
        text = ""
        for p in pages:
            text += pytesseract.image_to_string(p)
        return text
    except:
        return ""

def extract_text(file):
    if file.type == "application/pdf":
        return ocr_pdf(file)
    else:
        return ocr_image(Image.open(file))

# --- Clean ---
def clean_amount(val):
    return re.sub(r"[^\d.]", "", str(val))

# --- Fallback Extraction ---
def fallback_extraction(text):
    return {
        "Document Type": "Invoice" if "invoice" in text.lower() else "Receipt",
        "Vendor": re.findall(r"[A-Z][A-Za-z ]+(?:Ltd|Pvt|Solutions|Enterprises)", text)[0] if re.findall(r"[A-Z][A-Za-z ]+(?:Ltd|Pvt|Solutions|Enterprises)", text) else "Unknown",
        "Invoice Number": re.findall(r"INV[-\w]+", text)[0] if re.findall(r"INV[-\w]+", text) else "N/A",
        "Date": re.findall(r"\d{1,2}\s\w+\s\d{4}", text)[0] if re.findall(r"\d{1,2}\s\w+\s\d{4}", text) else "N/A",
        "Total Amount": clean_amount(re.findall(r"Total.*?([\d,]+\.\d+)", text)[0] if re.findall(r"Total.*?([\d,]+\.\d+)", text) else "0"),
        "Taxes": clean_amount(re.findall(r"GST.*?([\d,]+\.\d+)", text)[0] if re.findall(r"GST.*?([\d,]+\.\d+)", text) else "0"),
    }

# --- Gemini ---
def call_gemini(text):
    if not client:
        return None
    try:
        response = client.models.generate_content(
            model="gemini-1.0-pro",
            contents=f"""
Extract structured data in JSON:

{{
"Document Type": "",
"Vendor": "",
"Invoice Number": "",
"Date": "",
"Total Amount": "",
"Taxes": ""
}}

Text:
{text}
"""
        )

        raw = response.text
        match = re.search(r"\{.*\}", raw, re.DOTALL)

        if not match:
            return None

        data = json.loads(match.group())
        data["Total Amount"] = clean_amount(data.get("Total Amount", "0"))
        data["Taxes"] = clean_amount(data.get("Taxes", "0"))
        return data

    except:
        return None

# --- Duplicate ---
def is_duplicate(new):
    return any(old.get("Invoice Number") == new.get("Invoice Number") for old in st.session_state.history)

# --- n8n Trigger (Debugged Version) ---
def trigger_n8n(data):
    try:
        amount = float(data.get("Total Amount", 0))
        tax = float(data.get("Taxes", 0))
        vendor = data.get("Vendor", "").strip().lower()
        doc_type = data.get("Document Type", "").strip().lower()
        invoice_no = data.get("Invoice Number", "").strip()

        approved_vendors = ["amazon", "flipkart", "abc tech solutions"]

        alerts = []

        st.write("--- Debug trigger_n8n ---")
        st.write(f"Vendor: {vendor}, Amount: {amount}, Taxes: {tax}, Doc Type: {doc_type}, Invoice No: {invoice_no}")

        # --- Conditions ---
        if amount > 10000:
            alerts.append("High Value")
        if amount > 50000:
            alerts.append("URGENT: Very High Value")
        if not invoice_no or invoice_no.upper() == "N/A":
            alerts.append("Missing Invoice Number")
        if vendor not in approved_vendors:
            alerts.append("Unapproved Vendor")
        if tax > 0.3 * amount:
            alerts.append("High Tax Anomaly")
        if is_duplicate(data):
            alerts.append("Duplicate Invoice")

        if doc_type != "invoice":
            st.write("Document is not an invoice → ignoring email trigger")
            return False

        # --- Trigger Webhook ---
        if alerts:
            payload = {"alerts": alerts, "data": data}
            st.write("Alerts triggered:", alerts)
            try:
                response = requests.post(N8N_WEBHOOK_URL, json=payload)
                st.write("Webhook POST status:", response.status_code)
                if response.status_code == 200:
                    st.success("🚀 Email triggered via n8n")
                else:
                    st.error(f"Webhook returned status {response.status_code}")
            except Exception as e:
                st.error(f"Error sending webhook: {e}")
            return True
        else:
            st.write("No alerts → email not sent")
            return False

    except Exception as e:
        st.error(f"n8n error: {e}")
        return False

# --- Processing ---
if files:
    for file in files:
        st.subheader(f"📄 {file.name}")

        text = extract_text(file)
        st.text_area("Extracted Text", text, height=150)

        if st.button(f"Process {file.name}"):

            data = call_gemini(text)

            if data:
                st.success("🤖 Gemini extraction successful")
            else:
                st.warning("⚠️ Gemini failed → Using fallback")
                data = fallback_extraction(text)

            # --- Classification ---
            doc_type = data.get("Document Type", "Unknown")
            if doc_type.lower() == "invoice":
                st.success("📄 Invoice detected")
            elif doc_type.lower() == "receipt":
                st.info("🧾 Receipt detected")

            # --- Duplicate ---
            if is_duplicate(data):
                st.warning("⚠️ Duplicate detected")

            # --- Anomaly ---
            amt = float(data.get("Total Amount", 0))
            if amt > 20000:
                st.error("🚨 High-value anomaly")

            # --- n8n ---
            trigger_n8n(data)

            st.json(data)

            data["Filename"] = file.name
            data["Processed At"] = datetime.now()

            st.session_state.history.append(data)

# --- Dashboard ---
if st.session_state.history:
    st.header("📊 Dashboard")

    df = pd.DataFrame(st.session_state.history)

    min_amt = st.number_input("Minimum Amount", 0)
    df = df[df["Total Amount"].astype(float) >= min_amt]

    col1, col2, col3 = st.columns(3)
    col1.metric("Documents", len(df))
    col2.metric("Total Amount", df["Total Amount"].astype(float).sum())
    col3.metric("Invoices", len(df[df["Document Type"].str.lower() == "invoice"]))

    st.dataframe(df, use_container_width=True)

    st.download_button(
        "Download CSV",
        df.to_csv(index=False).encode("utf-8"),
        "documents.csv"
    )
