# app/api/routes/chatbot.py

import os
import logging
from typing import List, Optional
from fastapi import APIRouter, UploadFile, File, Form, Body, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv
import requests
from io import BytesIO
from PIL import Image
import base64

# Enable detailed logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

load_dotenv()
router = APIRouter()

# Configuration with debugging
LLAMA_API_KEY = os.getenv("OPENROUTER_API_KEY")
LLAMA_API_URL = "https://openrouter.ai/api/v1/chat/completions"
LLAMA_MODEL = os.getenv("LLAMA_MODEL_NAME", "qwen/qwen2.5-vl-32b-instruct")
FAQ_DOC_PATH = r"D:\Thrivv.ai\Dummy\Onboard2\FAQs.docx"

logger.info(f"API Key configured: {'Yes' if LLAMA_API_KEY else 'No'}")
logger.info(f"API URL: {LLAMA_API_URL}")
logger.info(f"Model: {LLAMA_MODEL}")

class ChatQuery(BaseModel):
    query: str

# Simplified FAQ loading with fallback
def load_faq_content():
    try:
        from docx import Document
        if os.path.exists(FAQ_DOC_PATH):
            doc = Document(FAQ_DOC_PATH)
            content = []
            for para in doc.paragraphs:
                if para.text.strip():
                    content.append(para.text.strip())
            return '\n'.join(content)
    except:
        pass
    
    # Fallback FAQ content
    return """
    Q: Who can open a corporate bank account in the UAE?
    A: Any registered business in the UAE with a valid trade license can apply.
    
    Q: What documents are required?
    A: Emirates ID, Commercial License, company documents, and business plan.
    
    Q: How long does account opening take?
    A: 7 to 15 working days depending on documentation.
    """

FAQ_CONTENT = load_faq_content()
logger.info(f"FAQ loaded: {len(FAQ_CONTENT)} characters")

# Simplified image processing
def process_image(file: UploadFile) -> Optional[str]:
    try:
        content = file.file.read()
        file.file.seek(0)
        image = Image.open(BytesIO(content))
        if image.mode != 'RGB':
            image = image.convert('RGB')
        image.thumbnail((512, 512))  # Smaller size for debugging
        buf = BytesIO()
        image.save(buf, format='JPEG')
        b64 = base64.b64encode(buf.getvalue()).decode()
        return f"data:image/jpeg;base64,{b64}"
    except Exception as e:
        logger.error(f"Image processing error: {e}")
        return None

# Enhanced AI API call with detailed debugging
def call_ai_api_debug(messages: List[dict]) -> str:
    """Debug version of AI API call with detailed logging"""
    
    if not LLAMA_API_KEY:
        logger.error("❌ No API key configured")
        return "❌ API key not configured. Please set OPENROUTER_API_KEY in your environment."
    
    headers = {
        "Authorization": f"Bearer {LLAMA_API_KEY}",
        "Content-Type": "application/json",
    }
    
    payload = {
        "model": LLAMA_MODEL,
        "messages": messages,
        "temperature": 0.5,
        "max_tokens": 500,  # Reduced for debugging
    }
    
    logger.debug(f"🔄 Making API request to: {LLAMA_API_URL}")
    logger.debug(f"🔄 Using model: {LLAMA_MODEL}")
    logger.debug(f"🔄 Message count: {len(messages)}")
    
    try:
        response = requests.post(LLAMA_API_URL, headers=headers, json=payload, timeout=30)
        
        logger.info(f"📡 API Response Status: {response.status_code}")
        logger.debug(f"📡 Response headers: {dict(response.headers)}")
        
        if response.status_code == 200:
            try:
                data = response.json()
                logger.debug(f"📡 Response data keys: {list(data.keys())}")
                
                if 'choices' in data and len(data['choices']) > 0:
                    content = data['choices'][0]['message']['content'].strip()
                    logger.info(f"✅ Successfully got AI response ({len(content)} chars)")
                    return content
                else:
                    logger.error(f"❌ No choices in response: {data}")
                    return "❌ Invalid response format from AI service."
                    
            except Exception as json_error:
                logger.error(f"❌ JSON parsing error: {json_error}")
                logger.error(f"❌ Raw response: {response.text[:500]}")
                return "❌ Failed to parse AI response."
                
        elif response.status_code == 401:
            logger.error("❌ Authentication failed - Invalid API key")
            return "❌ Authentication failed. Please check your API key."
            
        elif response.status_code == 429:
            logger.error("❌ Rate limit exceeded")
            return "❌ API rate limit exceeded. Please wait and try again."
            
        else:
            logger.error(f"❌ API error {response.status_code}: {response.text}")
            return f"❌ API error ({response.status_code}). Please try again."
            
    except requests.exceptions.Timeout:
        logger.error("❌ Request timeout")
        return "❌ Request timeout. Please try again."
        
    except requests.exceptions.ConnectionError:
        logger.error("❌ Connection error")
        return "❌ Cannot connect to AI service. Please check your internet connection."
        
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        return f"❌ Unexpected error: {str(e)}"

# Banking keywords check
BANKING_KEYWORDS = ["account", "bank", "document", "license", "eid", "trade", "fee", "uae", "thrivv"]

def is_banking_related(text: str) -> bool:
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in BANKING_KEYWORDS)

@router.post("/chatbot/query")
async def chatbot_query_debug(
    query: Optional[str] = Form(None),
    json_data: Optional[ChatQuery] = Body(None),
    files: Optional[List[UploadFile]] = File(None)
):
    """Debug version of chatbot endpoint with detailed logging"""
    
    logger.info("🚀 Chatbot query received")
    
    try:
        # Get query
        user_query = query or (json_data.query if json_data else None)
        
        if not user_query:
            logger.error("❌ No query provided")
            raise HTTPException(status_code=400, detail="Query required")
        
        logger.info(f"💬 Query: {user_query[:100]}...")
        
        # Check if banking related
        if not is_banking_related(user_query):
            logger.info("ℹ️ Non-banking query detected")
            return {
                "response": "I'm Thrivv Bank's AI assistant. Please ask about banking services, account opening, or upload banking documents.",
                "is_banking_related": False
            }
        
        # Simple test message first
        messages = [
            {
                "role": "system",
                "content": "You are Thrivv Bank's helpful AI assistant. Answer banking questions clearly and professionally."
            },
            {
                "role": "user", 
                "content": user_query
            }
        ]
        
        logger.info("🤖 Calling AI API...")
        ai_response = call_ai_api_debug(messages)
        
        return {
            "response": ai_response,
            "is_banking_related": True,
            "debug_info": {
                "api_key_present": bool(LLAMA_API_KEY),
                "model": LLAMA_MODEL,
                "query_length": len(user_query)
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Chatbot error: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "response": f"Internal error: {str(e)}",
                "debug_info": {
                    "error_type": type(e).__name__,
                    "error_message": str(e)
                }
            }
        )

@router.get("/chatbot/status")
async def chatbot_status():
    """Enhanced status endpoint for debugging"""
    return {
        "status": "active",
        "api_key_configured": bool(LLAMA_API_KEY),
        "api_key_preview": LLAMA_API_KEY[:10] + "..." if LLAMA_API_KEY else None,
        "model": LLAMA_MODEL,
        "api_url": LLAMA_API_URL,
        "faq_loaded": bool(FAQ_CONTENT),
        "faq_length": len(FAQ_CONTENT),
        "debug_mode": True
    }

@router.get("/chatbot/test")
async def test_api():
    """Test endpoint to check AI API connectivity"""
    test_messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Say 'Hello from Thrivv Bank API test'"}
    ]
    
    result = call_ai_api_debug(test_messages)
    return {"test_response": result}
