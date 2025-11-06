from flask import Flask, render_template, request, send_file
import os
from PyPDF2 import PdfReader
import pandas as pd
import re
import json
from dotenv import load_dotenv
from google import genai
from pdf2image import convert_from_path
import pytesseract

load_dotenv()

# Initialize Gemini client
key = os.getenv("GEMINI_API")
client = genai.Client(api_key=key)


app = Flask(__name__)

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

ALLOWED_EXTENSIONS = {'pdf'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def pdf_has_text(filepath):
    """Check if PDF has extractable text."""
    reader = PdfReader(filepath)
    for page in reader.pages:
        if page.extract_text():
            return True
    return False

def extract_text_from_pdf(filepath):
    """Extract text from a text-based PDF."""
    text = ""
    reader = PdfReader(filepath)
    for page in reader.pages:
        text += page.extract_text() or ""
    return text.strip()

def ocr_pdf(filepath):
    """Extract text from scanned/image-based PDF using OCR."""
    text = ""
    images = convert_from_path(filepath)
    for img in images:
        text += pytesseract.image_to_string(img)
    return text.strip()

def extract_product_name_from_invoice(pdf_path):
    # Step 1: Read and extract text
    if pdf_has_text(pdf_path):
        pdf_text = extract_text_from_pdf(pdf_path)
    else:
        pdf_text = ocr_pdf(pdf_path)
    if not pdf_text:
        return "No text could be extracted from the PDF."

    # Step 2: Prepare the prompt
    prompt = f"""
    You are an intelligent invoice data extraction assistant.

    Your goal is to read the invoice text below and return structured data in valid JSON format.

    ### Instructions:
    1. Identify and extract key fields such as:
       - invoice_number
       - date
       - vendor_name
       - customer_name
       - total_amount
       - tax_amount
       - currency
       - items (a list of objects with columns like item_name, quantity, unit_price, total_price)
    2. If some fields are missing, leave them as null.
    3. Do not include explanations or text outside the JSON.
    4. Return only valid JSON (no text, no code blocks).

    ### Example Output:
    {{
      "invoice_number": "INV-2024-001",
      "date": "2024-07-25",
      "vendor_name": "ABC Supplies Ltd.",
      "customer_name": "John Doe",
      "total_amount": "1245.50",
      "tax_amount": "45.50",
      "currency": "USD",
      "items": [
        {{"item_name": "MacBook Air", "quantity": 1, "unit_price": 1000, "total_price": 1000}},
        {{"item_name": "Charger", "quantity": 1, "unit_price": 200, "total_price": 200}}
      ]
    }}

    ### Invoice Text:
    {pdf_text}
    """

    # Step 3: Send to Gemini
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )

    return response.text

@app.route('/')
def index():
    return render_template('upload.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return "No file part", 400

    file = request.files['file']
    if file.filename == '':
        return "No selected file", 400

    if file and allowed_file(file.filename):
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        file.save(filepath)

        result = extract_product_name_from_invoice(filepath)
        cleaned_json = re.sub(r"```(?:json)?", "", result).strip()

        data = json.loads(cleaned_json)
        # print(data)
        print("🧾 Extracted Product Names:")
        # Create a DataFrame for the main info
        main_data = {k: v for k, v in data.items() if k != "items"}
        main_df = pd.DataFrame([main_data])

        # Create a DataFrame for the items (if present)
        if "items" in data:
            items_df = pd.DataFrame(data["items"])
        else:
            items_df = pd.DataFrame()

        # Write both to Excel
        excel_path = os.path.join(app.config['UPLOAD_FOLDER'], "invoice_data.xlsx")
        name_output_file = "invoice_data.xlsx"
        with pd.ExcelWriter(name_output_file, engine="openpyxl") as writer:
            main_df.to_excel(writer, sheet_name="Invoice Info", index=False)
            if not items_df.empty:
                items_df.to_excel(writer, sheet_name="Items", index=False)

        return send_file(name_output_file, as_attachment=True)

    return "Invalid file type. Only PDF allowed.", 400

@app.route('/download/<filename>')
def download_file(filename):
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    return send_file(filepath, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)
