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
                text = para.text.strip()
                if text and not text.startswith('<!--'):  # Skip HTML comments
                    content.append(text)
            faq_text = '\n\n'.join(content)
            logger.info(f"FAQ loaded successfully: {len(faq_text)} characters")
            return faq_text
        else:
            logger.warning(f"FAQ file not found at: {FAQ_DOC_PATH}")
    except Exception as e:
        logger.error(f"Failed to load FAQ: {e}")
    
    # Enhanced fallback content with complete information
    return """
1. Who can open a corporate bank account in the UAE?
- Any registered business in the UAE with a valid trade license can apply - including mainland, free zone, or offshore entities.

2. What documents are required?
- Commercial License (clear photo/scan)
- Emirates ID - Front and Back (clear photo/scan)  
- Company incorporation documents
- Business plan and source of funds
- Board resolution for authorized signatories

3. How long does account opening take?
- 7 to 15 working days depending on documentation and business activity.

4. What is the minimum balance requirement?
- Varies by account type but typically starts at AED 25,000 to AED 100,000.

5. Account Types Available:
- Basic Corporate Account: For small companies or startups
- Business Current Account: For businesses with regular transactions
- Corporate Savings Account: For businesses looking to save funds
- Corporate Term Deposit Account: For businesses seeking higher returns
- Multi-Currency Account: For businesses engaged in international trade
- Corporate Credit Card: For businesses needing flexible payment solutions
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
    """Enhanced API call with better timeout handling"""
    if not LLAMA_API_KEY:
        logger.error("❌ No API key configured")
        return "❌ API key not configured. Please set OPENROUTER_API_KEY in your environment."

    headers = {
        "Authorization": f"Bearer {LLAMA_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8000",
        "X-Title": "Thrivv Bank AI"
    }

    payload = {
        "model": LLAMA_MODEL,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 1000,  # Reduced from 2000 for faster response
        "top_p": 0.9,
        "stream": False  # Ensure non-streaming response
    }

    try:
        # Increased timeout to 120 seconds
        response = requests.post(
            LLAMA_API_URL, 
            headers=headers, 
            json=payload, 
            timeout=120  # Increased from 60 to 120 seconds
        )
        
        logger.info(f"📡 API Response Status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            if 'choices' in data and len(data['choices']) > 0:
                content = data['choices'][0]['message']['content'].strip()
                logger.info(f"✅ Successfully got AI response ({len(content)} chars)")
                return content
            else:
                return "❌ Invalid response format from AI service."
        
        elif response.status_code == 408:  # Request Timeout
            logger.error("❌ API request timeout")
            return "⏰ The AI service is taking longer than expected. Please try with a shorter question."
        
        elif response.status_code == 503:  # Service Unavailable
            logger.error("❌ API service unavailable")
            return "🔧 The AI service is temporarily unavailable. Please try again in a few moments."
        
        else:
            logger.error(f"❌ API error {response.status_code}: {response.text}")
            return f"❌ Service temporarily unavailable. Please try again."

    except requests.exceptions.Timeout:
        logger.error("❌ Request timeout after 120 seconds")
        return "⏰ Request timed out. The AI service is busy. Please try again with a shorter question."
    
    except requests.exceptions.ConnectionError:
        logger.error("❌ Connection error")
        return "🌐 Network connection issue. Please check your internet connection and try again."
    
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        return f"❌ Unexpected error occurred. Please try again."



# Banking keywords check
BANKING_KEYWORDS = ["account", "bank", "document", "license", "eid", "trade", "fee", "uae", "thrivv"]

def is_banking_related(text: str) -> bool:
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in BANKING_KEYWORDS)

@router.post("/chatbot/query")
async def chatbot_query_debug(request: dict):
    """Enhanced chatbot endpoint with complete responses"""
    logger.info("🚀 Chatbot query received")
    
    try:
        user_query = request.get("query")
        
        if not user_query:
            logger.error("❌ No query provided in request")
            raise HTTPException(status_code=400, detail="Query field is required")

        logger.info(f"💬 Query: {user_query[:100]}...")

        # Check if banking related
        if not is_banking_related(user_query):
            logger.info("ℹ️ Non-banking query detected")
            return {
                "response": "I'm Thrivv Bank's AI assistant. Please ask about banking services, account opening, or upload banking documents.",
                "is_banking_related": False
            }

        # Enhanced system prompt for complete responses
        system_prompt = f"""You are Thrivv Bank's AI assistant. Provide complete, helpful answers using this FAQ information:

{FAQ_CONTENT}

IMPORTANT INSTRUCTIONS:
- Always provide COMPLETE answers
- Don't cut off your response mid-sentence
- If listing multiple items, include ALL relevant items
- Be concise but thorough
- If the question isn't in the FAQ, provide general banking guidance and suggest contacting customer service

Answer the user's question completely and professionally."""

        messages = [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": f"Question: {user_query}"
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
                "query_length": len(user_query),
                "response_length": len(ai_response)
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
