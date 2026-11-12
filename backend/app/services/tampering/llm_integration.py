from typing import Dict, Optional
from .services.llm_service import generate_llm_analysis, get_llm_analysis

# =====================================
# LLM Integration Wrapper
# =====================================
def get_document_analysis(test_report_id: str, regenerate: bool = False) -> Optional[Dict]:
    if not test_report_id:
        return None
    
    if regenerate:
        return generate_llm_analysis(test_report_id, use_cache=False)
    else:
        existing = get_llm_analysis(test_report_id)
        if existing:
            return existing
        else:
            return generate_llm_analysis(test_report_id, use_cache=False)

