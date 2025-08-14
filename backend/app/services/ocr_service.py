# app/services/ocr_service.py

import os
import base64
import requests
from dotenv import load_dotenv
from app.services.supabase_client import supabase

load_dotenv()

DOCUMENTS_ROOT = os.path.join("backend", "documents", "id")

# === LLaMA 3.2 Vision CONFIG ===
LLAMA_API_KEY = os.getenv("OPENROUTER_API_KEY")  # Add this key to your .env file
LLAMA_API_URL = "https://openrouter.ai/api/v1/chat/completions"
LLAMA_MODEL_NAME = "meta-llama/llama-3.2-11b-vision-instruct:free"

def identify_document_type(extracted_text: str) -> str:
    """
    Analyze extracted text to determine document type
    Returns: 'commercial', 'eid', or 'unknown'
    """
    text_lower = extracted_text.lower()
    
    # Keywords for Commercial Registration Document
    commercial_keywords = [
        "commercial registration", "trade license", "business license",
        "commercial license", "establishment card", "commerce", "trading",
        "company registration", "business registration", "commercial permit"
    ]
    
    # Keywords for EID (Emirates ID / Resident Identity Card)
    eid_keywords = [
        "emirates id", "identity card", "resident identity", "emirates identity",
        "id card", "residence card", "national id", "civil id", "eid"
    ]
    
    # Check for commercial document
    commercial_score = sum(1 for keyword in commercial_keywords if keyword in text_lower)
    eid_score = sum(1 for keyword in eid_keywords if keyword in text_lower) 
    
    if commercial_score > 0 and commercial_score > eid_score:
        return "commercial"
    elif eid_score > 0:
        return "eid"
    else:
        return "unknown"

def extract_text_from_user_documents(user_email: str) -> dict:
    """
    Perform OCR using LLaMA 3.2 Vision on all image documents for a user.
    Returns a dict with format: {'filename': {'type': 'commercial'/'eid'/'unknown', 'text': 'extracted_text'}}
    Also saves the extracted results to 'ocr-res.txt' under the same folder.
    """
    user_folder = os.path.join(DOCUMENTS_ROOT, user_email)
    if not os.path.exists(user_folder):
        raise FileNotFoundError(f"[ERROR] No folder found for user: {user_folder}")

    # Get all image files in the folder
    image_files = [f for f in os.listdir(user_folder) 
                   if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))]
    
    if not image_files:
        raise Exception("[ERROR] No image files found for OCR processing.")

    ocr_results = {}
    result_text_for_file = ""

    for filename in image_files:
        file_path = os.path.join(user_folder, filename)
        print(f"[INFO] Processing file: {filename}")

        with open(file_path, "rb") as img_file:
            image_bytes = img_file.read()
        
        ext = os.path.splitext(file_path)[1].lower()
        mime_type = "jpeg" if ext in [".jpg", ".jpeg"] else "png"
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        image_url = f"data:image/{mime_type};base64,{image_b64}"

        # Enhanced prompt for better document identification
        prompt = """Analyze this document image and extract all visible text. 

Please identify what type of document this is:
1. If it's a Commercial Registration Document, Trade License, Business License, or any business-related official document
2. If it's an Emirates ID, Identity Card, Resident Identity Card, or any personal identification document
3. If it's neither of the above

Then extract all the text you can see in the document, including:
- All headers and titles
- All field names and their values
- All numbers, dates, and codes
- Any official seals or stamps text

Return the text in a clean, structured format."""

        headers = {
            "Authorization": f"Bearer {LLAMA_API_KEY}",
            "Content-Type": "application/json",
            "X-Title": "OCR Extraction"
        }

        payload = {
            "model": LLAMA_MODEL_NAME,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_url}}
                    ]
                }
            ]
        }

        try:
            response = requests.post(LLAMA_API_URL, headers=headers, json=payload)
            if response.status_code == 200:
                result = response.json()
                extracted_text = result["choices"][0]["message"]["content"].strip()
                
                # Identify document type based on extracted text
                doc_type = identify_document_type(extracted_text)
                
                # Store results
                ocr_results[filename] = {
                    "type": doc_type,
                    "text": extracted_text
                }
                
                result_text_for_file += f"--- [TYPE: {doc_type.upper()}] {filename} ---\n{extracted_text}\n\n"
                print(f"[INFO] Successfully processed {filename} as {doc_type}")
                
            else:
                error_msg = f"[ERROR extracting text: HTTP {response.status_code} - {response.text}]"
                ocr_results[filename] = {
                    "type": "unknown",
                    "text": error_msg
                }
                result_text_for_file += f"--- [TYPE: UNKNOWN] {filename} ---\n{error_msg}\n\n"
                print(f"[ERROR] Failed to process {filename}: {error_msg}")

        except Exception as e:
            error_msg = f"[ERROR extracting text: {str(e)}]"
            ocr_results[filename] = {
                "type": "unknown",
                "text": error_msg
            }
            result_text_for_file += f"--- [TYPE: UNKNOWN] {filename} ---\n{error_msg}\n\n"
            print(f"[ERROR] Failed to process {filename}: {e}")

    # Save extracted text to file
    output_file = os.path.join(user_folder, "ocr-res.txt")
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(result_text_for_file)

    print(f"[INFO] OCR results saved to: {output_file}")

    # Check if both required documents are present
    has_commercial = any(data["type"] == "commercial" for data in ocr_results.values())
    has_eid = any(data["type"] == "eid" for data in ocr_results.values())

    if has_commercial and has_eid:
        # Update Supabase only if both documents are verified
        supabase.table("users").update({"onboarding_step": "verification_complete"}).eq("email", user_email).execute()
        print(f"[INFO] Onboarding step set to verification_complete for {user_email}")
    else:
        print(f"[INFO] Documents incomplete for {user_email}. Commercial: {has_commercial}, EID: {has_eid}")

    return ocr_results