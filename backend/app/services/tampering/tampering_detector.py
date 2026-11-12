from typing import Dict
from datetime import datetime

# ✅ FIXED: All relative imports
from .modules.jpeg_quantization import (
    load_image,
    test_jpeg_quantization
)
from .modules.metadata_verification import test_metadata_verification
from .modules.error_level_analysis import test_error_level_analysis
from .modules.font_consistency import test_font_consistency
from .modules.copy_move_detection import test_copy_move_detection
from .decision_engine import make_decision


def detect_tampering(
    file_path: str,
    generate_evidence: bool = False,
    evidence_dir: str = None
) -> Dict:
    start_time = datetime.now()
    
    try:
        image, _ = load_image(file_path)
        
        result1 = test_jpeg_quantization(file_path, image)
        result2 = test_metadata_verification(file_path)
        result3 = test_error_level_analysis(file_path, image)
        result4 = test_font_consistency(file_path)
        result5 = test_copy_move_detection(file_path, image)
        
        test_results = [
            {
                "test": "JPEG Quantization Forensics",
                "status": result1["status"],
                "reason": result1["reason"],
                "evidence": result1["evidence"],
                "tampering_score": result1.get("tampering_score", 0)
            },
            {
                "test": "Metadata Verification",
                "status": result2["status"],
                "reason": result2["reason"],
                "evidence": result2["evidence"],
                "tampering_score": result2.get("tampering_score", 0)
            },
            {
                "test": "Error Level Analysis (ELA)",
                "status": result3["status"],
                "reason": result3["reason"],
                "evidence": result3["evidence"],
                "tampering_score": result3.get("tampering_score", 0)
            },
            {
                "test": "Font Consistency Analysis",
                "status": result4["status"],
                "reason": result4["reason"],
                "evidence": result4["evidence"],
                "tampering_score": result4.get("tampering_score", 0)
            },
            {
                "test": "Copy-Move Detection",
                "status": result5["status"],
                "reason": result5["reason"],
                "evidence": result5["evidence"],
                "tampering_score": result5.get("tampering_score", 0)
            }
        ]
        
        decision = make_decision(test_results)
        evidence = None
        processing_time_sec = (datetime.now() - start_time).total_seconds()
        case_id = f"FORENSIC-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        
        forensic_report = {
            "case_id": case_id,
            "timestamp": datetime.now().isoformat(),
            "file_path": file_path,
            "decision": decision,
            "test_results": test_results
        }
        
        try:
            from app.services.supabase_client import save_test_report
            test_report_id = save_test_report(file_path, decision, test_results, processing_time_sec, forensic_report)
            forensic_report["test_report_id"] = test_report_id
        except Exception as e:
            test_report_id = None
            forensic_report["test_report_id"] = None
        
        return {
            "is_tampered": decision["decision"] == "REJECT",
            "decision": decision["decision"],
            "status": decision["status"],
            "reason": decision["reason"],
            "test_results": test_results,
            "evidence": evidence,
            "processing_time": processing_time_sec,
            "flags": decision.get("flags", []),
            "decision_rationale": decision.get("decision_rationale", ""),
            "weighted_score": decision.get("weighted_score", 0.0),
            "module_scores": decision.get("module_scores", {}),
            "overall_tampering_score": decision.get("overall_tampering_score", 0.0),
            "test_report_id": test_report_id,
            "forensic_report": forensic_report
        }
    
    except Exception as e:
        return {
            "is_tampered": False,
            "decision": "ERROR",
            "status": "ERROR",
            "reason": f"Error processing document: {str(e)}",
            "test_results": [],
            "evidence": None,
            "processing_time": (datetime.now() - start_time).total_seconds()
        }