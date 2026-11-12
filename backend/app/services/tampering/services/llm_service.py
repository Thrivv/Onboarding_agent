import json
import requests
from typing import Dict, Optional
from app.services.supabase_client import get_supabase_client, get_tampering_table
import logging
from app import config

logger = logging.getLogger(__name__)

# =====================================
# AWS Bedrock Configuration
# =====================================
def get_bedrock_api_key():
    api_key = config.AWS_BEARER_TOKEN_BEDROCK
    if not api_key:
        raise ValueError("AWS_BEARER_TOKEN_BEDROCK not found in .env file")
    return api_key

def call_llm_api(system_prompt: str, user_prompt: str) -> str:
    # Model + endpoint come from llm_client (backed by bedrock_client.py).
    from app.services.llm_client import LLM_API_URL, TEXT_PRIMARY
    from app.services import bedrock_client

    api_key = get_bedrock_api_key()
    model = TEXT_PRIMARY

    url = LLM_API_URL
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.3,
        "max_tokens": 150
    }
    
    response = bedrock_client.post(url, headers=headers, json=payload)
    response.raise_for_status()
    
    result = response.json()
    return result['choices'][0]['message']['content']

# =====================================
# Fetch Data from Supabase
# =====================================
def fetch_test_report_data(test_report_id: str) -> Optional[Dict]:
    try:
        client = get_supabase_client()
        
        # Fetch main test report
        from app.services.supabase_client import get_tampering_table
        report_result = get_tampering_table("test_reports").select("*").eq("id", test_report_id).execute()
        if not report_result.data:
            return None
        
        report = report_result.data[0]
        
        # Fetch module results
        modules_result = get_tampering_table("module_results").select("*").eq("test_report_id", test_report_id).execute()
        modules = modules_result.data if modules_result.data else []
        
        # Fetch tampered regions
        regions_result = get_tampering_table("tampered_regions").select("*").eq("test_report_id", test_report_id).execute()
        regions = regions_result.data if regions_result.data else []
        
        return {
            "report": report,
            "modules": modules,
            "regions": regions
        }
    except Exception as e:
        logger.info(f"Error fetching test report data: {str(e)}")
        return None

# =====================================
# Format Data for LLM Prompt
# =====================================
def format_data_for_llm(data: Dict) -> str:
    report = data["report"]
    modules = data["modules"]
    regions = data["regions"]
    
    prompt = f"""DOCUMENT TAMPERING ANALYSIS REPORT

Document Information:
- Document Name: {report.get('document_name', 'Unknown')}
- File Type: {report.get('file_type', 'Unknown')}
- Overall Tampering Score: {report.get('overall_score', 0.0)}/100
- Final Decision: {report.get('decision', 'UNKNOWN')}
- Status: {report.get('status', 'UNKNOWN')}
- Case ID: {report.get('case_id', 'N/A')}
- Processing Time: {report.get('processing_time', 0.0):.2f} seconds

FORENSIC MODULE RESULTS:
"""
    
    failed_modules = [m for m in modules if m.get('status') == 'FAIL']
    other_modules = [m for m in modules if m.get('status') != 'FAIL']
    
    if failed_modules:
        prompt += "\n⚠️ FAILED MODULES (Primary Issues - Document Rejected):\n"
        for i, module in enumerate(failed_modules, 1):
            module_name = module.get('module_name', 'Unknown')
            status = module.get('status', 'UNKNOWN')
            score = module.get('score', 0.0)
            reason = module.get('reason', 'No reason provided')
            
            prompt += f"""
Module {i}: {module_name} - STATUS: {status}
- Tampering Score: {score}/100
- Reason: {reason}
"""
            
            evidence = module.get('evidence', {})
            if evidence:
                flags = evidence.get('flags', [])
                if flags:
                    prompt += f"- Flags: {', '.join(flags)}\n"
    
    if other_modules:
        prompt += "\n✅ Other Modules:\n"
        for i, module in enumerate(other_modules, 1):
            module_name = module.get('module_name', 'Unknown')
            status = module.get('status', 'UNKNOWN')
            score = module.get('score', 0.0)
            
            prompt += f"""
Module: {module_name} - Status: {status} (Score: {score}/100)
"""
    
    if regions:
        prompt += "\nTAMPERED REGIONS DETECTED:\n"
        for i, region in enumerate(regions, 1):
            module_name = region.get('module_name', 'Unknown')
            coordinates = region.get('region_coordinates', {})
            confidence = region.get('confidence', 0.0)
            tampering_type = region.get('tampering_type', 'Unknown')
            
            prompt += f"""
Region {i}:
- Detected by: {module_name}
- Confidence: {confidence}%
- Tampering Type: {tampering_type}
- Coordinates: {json.dumps(coordinates, indent=2)}
"""
    else:
        prompt += "\nNo specific tampered regions were detected.\n"
    
    return prompt

# =====================================
# Generate LLM Analysis
# =====================================
def generate_llm_analysis(test_report_id: str, use_cache: bool = True) -> Optional[Dict]:
    try:
        client = get_supabase_client()
        
        # Check if analysis already exists
        if use_cache:
            existing = get_tampering_table("llm_analysis").select("*").eq("test_report_id", test_report_id).order("generated_at", desc=True).limit(1).execute()
            if existing.data:
                return existing.data[0]
        
        # Fetch data from database
        data = fetch_test_report_data(test_report_id)
        if not data:
            return None
        
        # Check if document is tampered - only call LLM for REJECT or ESCALATE
        report = data.get("report", {})
        decision = report.get("decision", "").upper()
        
        if decision == "ACCEPT":
            # Document is authentic, no need for LLM analysis
            return None
        
        # Format data for LLM
        formatted_data = format_data_for_llm(data)
        
        # Create LLM prompt
        system_prompt = """You are a forensic document analyst. Provide ONLY a 2-line response:
Line 1: Identify which module(s) FAILED and what tampering was detected. If modules have FAIL status, mention those first. Only mention regions if no modules failed.
Line 2: Suggest uploading an untampered document.

Be concise, direct, and professional. Maximum 2 sentences. Prioritize FAILED modules over regions."""
        
        user_prompt = f"""Analyze this forensic report and respond in exactly 2 lines:

{formatted_data}

IMPORTANT: Focus on modules with FAIL status first. Only mention regions if no modules failed.
Line 1: Which module(s) failed and what tampering was detected?
Line 2: Suggest uploading untampered document."""
        
        # Call the Bedrock API
        analysis_text = call_llm_api(system_prompt, user_prompt)
        
        # Extract tampered sections from regions
        tampered_sections = []
        for region in data["regions"]:
            tampered_sections.append({
                "module": region.get('module_name'),
                "coordinates": region.get('region_coordinates'),
                "confidence": region.get('confidence'),
                "type": region.get('tampering_type')
            })
        
        # Generate recommendations
        recommendations = generate_recommendations(data)
        
        # Save to database
        analysis_data = {
            "test_report_id": test_report_id,
            "analysis_text": analysis_text,
            "tampered_sections": tampered_sections,
            "recommendations": recommendations
        }
        
        result = get_tampering_table("llm_analysis").insert(analysis_data).execute()
        return result.data[0] if result.data else None
        
    except Exception as e:
        logger.info(f"Error generating LLM analysis: {str(e)}")
        return None

# =====================================
# Generate Recommendations
# =====================================
def generate_recommendations(data: Dict) -> str:
    report = data["report"]
    decision = report.get('decision', 'UNKNOWN')
    status = report.get('status', 'UNKNOWN')
    
    recommendations = []
    
    if decision == "REJECT":
        recommendations.append("This document has been rejected due to evidence of tampering.")
        recommendations.append("Please provide an original, unmodified document for verification.")
        recommendations.append("If you believe this is an error, contact support with your case ID.")
    elif decision == "ESCALATE":
        recommendations.append("This document requires manual review.")
        recommendations.append("Please ensure you are submitting the original document.")
        recommendations.append("A review team will examine your document shortly.")
    else:
        recommendations.append("Your document appears to be authentic.")
        recommendations.append("No evidence of tampering was detected.")
    
    return "\n".join(recommendations)

# =====================================
# Get LLM Analysis from Database
# =====================================
def get_llm_analysis(test_report_id: str) -> Optional[Dict]:
    try:
        client = get_supabase_client()
        result = get_tampering_table("llm_analysis").select("*").eq("test_report_id", test_report_id).order("generated_at", desc=True).limit(1).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        logger.info(f"Error fetching LLM analysis: {str(e)}")
        return None

