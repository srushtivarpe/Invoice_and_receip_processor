import streamlit as st
import pytesseract
from PIL import Image
from pdf2image import convert_from_bytes
import google.generativeai as genai
import json
import re
import requests

# ---------------- CONFIG ----------------
GEMINI_API_KEY = "YOUR_API_KEY"
N8N_WEBHOOK_URL = "YOUR_WEBHOOK_URL"

pytesseract.pytesseract.tesseract_cmd = r"C:\\Program Files\\Tesseract-OCR\\tesseract.exe"

genai.configure(api_key=GEMINI_API_KEY)

# ---------------- PROMPT ----------------
PROMPT = """
Extract structured invoice data from the following text.

Return ONLY valid JSON. No explanation.

Fields required:
- Vendor
- Invoice Number
- Date
- Total Amount
- Email

Rules:
- Do NOT extract phone numbers as date
- Do NOT return 'INVOICE' as invoice number
- Total Amount must be numeric only
- If not found return "N/A"

Format:
{
  "Vendor": "",
  "Invoice Number": "",
  "Date": "",
  "Total Amount": "",
  "Email": ""
}

Text:
"""

# ---------------- FUNCTIONS ----------------

def extract_text(file):
    if file.type == "application/pdf":
        images = convert_from_bytes(file.read())
        text = ""
        for img in images:
            text += pytesseract.image_to_string(img)
        return text
    else:
        image = Image.open(file)
        return pytesseract.image_to_string(image)


def extract_json(text):
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(PROMPT + text)

        raw = response.text.strip()

        start = raw.find("{")
        end = raw.rfind("}") + 1

        json_text = raw[start:end]
        data = json.loads(json_text)

        return data

    except Exception as e:
        print("ERROR:", e)
        return {}


def clean_data(data):
    # Amount cleanup
    amount = data.get("Total Amount", "0")
    amount = re.sub(r"[^\d.]", "", str(amount))
    amount = float(amount) if amount else 0

    # Date validation
    date = data.get("Date", "N/A")
    if re.search(r"\d{10}", str(date)):
        date = "N/A"

    # Invoice validation
    invoice = data.get("Invoice Number", "N/A")
    if str(invoice).strip().lower() == "invoice":
        invoice = "N/A"

    return {
        "vendor": data.get("Vendor", "N/A"),
        "invoice_number": invoice,
        "date": date,
        "amount": amount,
        "email": data.get("Email", "test@gmail.com")
    }


def generate_alerts(data):
    alerts = []

    if data["amount"] > 5000:
        alerts.append("High Value")

    if data["vendor"] == "N/A":
        alerts.append("Missing Vendor")

    if data["amount"] == 0:
        alerts.append("Invalid Amount")

    return alerts


def send_to_n8n(payload):
    try:
        response = requests.post(N8N_WEBHOOK_URL, json=payload)
        return response.status_code
    except Exception as e:
        print("Webhook Error:", e)
        return None

# ---------------- UI ----------------

st.title("📄 AI Invoice Processor")

file = st.file_uploader("Upload Invoice", type=["pdf", "png", "jpg", "jpeg"])

if file:
    st.info("Processing...")

    text = extract_text(file)
    st.subheader("OCR Text")
    st.write(text)

    ai_data = extract_json(text)
    st.subheader("AI Output")
    st.write(ai_data)

    cleaned = clean_data(ai_data)
    alerts = generate_alerts(cleaned)

    st.subheader("Final Structured Data")
    st.write(cleaned)

    st.subheader("Alerts")
    st.write(alerts)

    payload = {
        "body": {
            "data": {
                "Vendor": cleaned["vendor"],
                "Invoice Number": cleaned["invoice_number"],
                "Date": cleaned["date"],
                "Total Amount": cleaned["amount"]
            },
            "alerts": alerts
        }
    }

    status = send_to_n8n(payload)

    if status == 200:
        st.success("Sent to workflow successfully!")
    else:
        st.error("Failed to send to workflow")
