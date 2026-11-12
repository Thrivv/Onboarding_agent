import os
import json
import cv2
from typing import Dict, List, Tuple
from datetime import datetime
from .utils.file_utils import get_evidence_file_extension

# =====================================
# Constants
# =====================================
OVERALL_SCORE = 100.0
CORR_BOOST_SPATIAL = 0.15
CORR_BOOST_CONTRADICT = 0.20
CORR_BOOST_PATTERN = 0.10
ANOMALY_RATIO = 0.45
CLUSTER_MIN = 4
CLUSTER_MAX = 7
PATTERN_AGREEMENT = 1.7
ANOMALY_MIN = 5
ANOMALY_MAX = 8
STD_Q = 7.0
ELA_SCORE = 25
MAX_RE_SAVE_SCORE = 100
MAX_ELA_SCORE = 50

EVIDENCE_ORIGINAL_FILENAME = "original"
EVIDENCE_REPORT_FILENAME = "forensic_report.json"
EVIDENCE_SUMMARY_FILENAME = "decision_summary.txt"
DEFAULT_EVIDENCE_DIR = "evidence"


def _cross_module_correlation(test_results: List[Dict]) -> Dict:
    correlations = {
        "spatial_overlap": False,
        "contradiction_detected": False,
        "pattern_match": False,
        "confidence_boost": 0.0,
        "correlation_flags": []
    }
    
    jpeg_result = next((t for t in test_results if t.get("test") == "JPEG Quantization Forensics"), None)
    ela_result = next((t for t in test_results if t.get("test") == "Error Level Analysis (ELA)"), None)
    copy_move_result = next((t for t in test_results if t.get("test") == "Copy-Move Detection"), None)
    metadata_result = next((t for t in test_results if t.get("test") == "Metadata Verification"), None)
    
    if not jpeg_result or not ela_result:
        return correlations
    
    jpeg_evidence = jpeg_result.get("evidence", {})
    ela_evidence = ela_result.get("evidence", {})
    metadata_evidence = metadata_result.get("evidence", {}) if metadata_result else {}
    copy_move_evidence = copy_move_result.get("evidence", {}) if copy_move_result else {}
    
    jpeg_doc = jpeg_evidence.get("document_analysis", {})
    ela_doc = ela_evidence.get("document_analysis", {})
    
    print_scan_conf = jpeg_doc.get("print_scan_confidence", 0)
    if jpeg_doc.get("camera_recapture", False) or print_scan_conf > 0.4:
        correlations["camera_recapture"] = True
        correlations["correlation_flags"].append("camera_recapture_detected")
    
    ela_inconsistent = len(ela_doc.get("inconsistent_regions", []))
    if not correlations.get("camera_recapture", False) and ela_inconsistent >= 3:
        ela_stats = ela_evidence.get("ela_stats", {})
        overall_stats = ela_stats.get("overall", {})
        doc_mean = overall_stats.get("mean", 0)
        if 0.5 < doc_mean < 0.65 and ela_result.get("status") in ["PASS", "ESCALATE"]:
            correlations["camera_recapture"] = True
            correlations["correlation_flags"].append("camera_recapture_detected")
    
    jpeg_status = jpeg_result.get("status", "PASS")
    ela_status = ela_result.get("status", "PASS")
    if not correlations.get("camera_recapture", False) and jpeg_status == "FAIL" and ela_status == "FAIL":
        if print_scan_conf > 0.1 or jpeg_doc.get("camera_recapture", False):
            correlations["camera_recapture"] = True
            correlations["correlation_flags"].append("camera_recapture_detected")
    
    jpeg_anomalies = jpeg_doc.get("anomalous_regions", 0)
    ela_inconsistent = len(ela_doc.get("inconsistent_regions", []))
    copy_move_detected = copy_move_evidence.get("detection_result", {}).get("detected", False)
    metadata_status = metadata_result.get("status", "PASS") if metadata_result else "PASS"
    
    if jpeg_anomalies > 0 and ela_inconsistent > 0 and copy_move_detected:
        correlations["spatial_overlap"] = True
        correlations["confidence_boost"] += CORR_BOOST_SPATIAL
        correlations["correlation_flags"].append("spatial_correlation")
    
    if metadata_status == "PASS" and (jpeg_result.get("status") == "FAIL" or ela_result.get("status") == "FAIL"):
        correlations["contradiction_detected"] = True
        correlations["confidence_boost"] += CORR_BOOST_CONTRADICT
        correlations["correlation_flags"].append("metadata_cleaning_suspected")
    
    jpeg_pattern = jpeg_doc.get("pattern_agreement", 0)
    if jpeg_pattern > PATTERN_AGREEMENT and ela_inconsistent >= 3 and copy_move_detected:
        correlations["pattern_match"] = True
        correlations["confidence_boost"] += CORR_BOOST_PATTERN
        correlations["correlation_flags"].append("pattern_correlation")
    
    return correlations


def _check_priority_flags(test_results: List[Dict]) -> Tuple[List[str], bool]:
    # =====================================
    # Collect All Flags and Check Priority Flags
    # =====================================
    all_flags = []
    for t in test_results:
        if "evidence" in t and "flags" in t["evidence"]:
            all_flags.extend(t["evidence"]["flags"])
        if "flags" in t:
            all_flags.extend(t["flags"])
    
    priority_flags = [
        "editing_software"
    ]
    
    found_priority = any(flag in all_flags for flag in priority_flags)
    return list(set(all_flags)), found_priority


def _calculate_module_scores(test_results: List[Dict]) -> Dict:
    # =====================================
    # Calculate Individual Module Tampering Scores
    # =====================================
    module_scores = {}
    
    for test in test_results:
        test_name = test.get("test", "")
        tampering_score = test.get("tampering_score", 0)
        module_scores[test_name] = tampering_score
    
    return module_scores


def _calculate_overall_score(module_scores: Dict) -> float:
    # =====================================
    # Calculate Overall Document Tampering Score
    # =====================================
    if not module_scores:
        return 0.0
    
    module_weights = {
        "JPEG Quantization Forensics": 0.30,
        "Error Level Analysis (ELA)": 0.35,
        "Metadata Verification": 0.20,
        "Font Consistency Analysis": 0.10,
        "Copy-Move Detection": 0.05
    }
    
    weighted_sum = 0.0
    total_weight = 0.0
    
    for test_name, score in module_scores.items():
        weight = module_weights.get(test_name, 0.10)
        weighted_sum += score * weight
        total_weight += weight
    
    if total_weight == 0:
        return 0.0
    
    overall = weighted_sum / total_weight
    return round(min(100, overall), 2)




def make_decision(test_results: List[Dict]) -> Dict:
    # =====================================
    # Check Priority Flags for Auto-Reject
    # =====================================
    all_flags, has_priority_flag = _check_priority_flags(test_results)
    
    if has_priority_flag:
        failed_tests = [t.get("test") for t in test_results if t.get("status") == "FAIL"]
        return {
            "decision": "REJECT",
            "status": "TAMPERED",
            "reason": "Priority flag detected - auto-reject",
            "failed_tests": failed_tests,
            "flags": all_flags,
            "decision_rationale": f"Priority flags: {', '.join([f for f in all_flags if f in ['editing_software', 'invalid_file_format', 'file_not_found', 'image_load_failed', 'suspicious_blur', 'bleached_document']])}",
            "module_scores": {},
            "overall_tampering_score": OVERALL_SCORE
        }
    
    module_scores = _calculate_module_scores(test_results)
    overall_score = _calculate_overall_score(module_scores)
    
    correlation_analysis = _cross_module_correlation(test_results)
    if correlation_analysis["confidence_boost"] > 0:
        boost_points = min(10, correlation_analysis["confidence_boost"] * 20)
        overall_score = min(100, overall_score + boost_points)
        if correlation_analysis["correlation_flags"]:
            all_flags.extend(correlation_analysis["correlation_flags"])
    
    if correlation_analysis.get("camera_recapture", False):
        failed_tests_list = [t for t in test_results if t.get("status") == "FAIL"]
        if len(failed_tests_list) >= 2 and overall_score >= 60:
            return {
                "decision": "REJECT",
                "status": "TAMPERED",
                "reason": "Camera recapture detected with multiple tampering indicators",
                "failed_tests": [t.get("test") for t in failed_tests_list],
                "flags": all_flags,
                "decision_rationale": "Camera recapture pattern detected with additional tampering evidence",
                "module_scores": module_scores,
                "overall_tampering_score": min(100, overall_score + 20),
                "correlation_analysis": correlation_analysis
            }
        else:
            return _create_decision_dict(
                "ESCALATE", "REVIEW_REQUIRED",
                "Camera recapture/scan pattern detected - document may be scanned (legitimate) or tampered"
            )
    
    # =====================================
    # Identify Failed and Escalated Tests
    # =====================================
    failed = [t for t in test_results if t.get("status") == "FAIL"]
    escalated = [t for t in test_results if t.get("status") == "ESCALATE"]
    
    def _add_correlation_reason(base_reason: str) -> str:
        if correlation_analysis["contradiction_detected"]:
            base_reason += " (metadata contradiction: clean metadata but image shows tampering)"
        elif correlation_analysis["spatial_overlap"]:
            base_reason += " (spatial correlation: multiple modules detected tampering in same regions)"
        return base_reason
    
    def _create_decision_dict(decision: str, status: str, reason: str, 
                              failed_tests_list: List[str] = None,
                              escalated_tests_list: List[str] = None) -> Dict:
        result = {
            "decision": decision,
            "status": status,
            "reason": reason,
            "flags": all_flags,
            "module_scores": module_scores,
            "overall_tampering_score": overall_score,
            "correlation_analysis": correlation_analysis
        }
        if failed_tests_list:
            result["failed_tests"] = failed_tests_list
        if escalated_tests_list:
            result["escalated_tests"] = escalated_tests_list
        return result
    
    # =====================================
    # Process Failed Tests and Return Reject Decisions
    # =====================================
    if failed:
        all_flags = list(set(all_flags))
        
        num_failed = len(failed)
        max_fail_score = max([t.get("tampering_score", 0) for t in failed], default=0)
        
        should_reject = False
        
        camera_recapture_detected = correlation_analysis.get("camera_recapture", False)
        
        jpeg_failed_check = [t for t in failed if t.get("test") == "JPEG Quantization Forensics"]
        ela_result_check = next((t for t in test_results if t.get("test") == "Error Level Analysis (ELA)"), None)
        
        if not camera_recapture_detected and num_failed >= 2:
            jpeg_result_check = next((t for t in test_results if t.get("test") == "JPEG Quantization Forensics"), None)
            if jpeg_result_check:
                jpeg_evidence_check = jpeg_result_check.get("evidence", {})
                jpeg_doc_check = jpeg_evidence_check.get("document_analysis", {})
                print_scan_conf_check = jpeg_doc_check.get("print_scan_confidence", 0)
                editing_boundaries_count_check = jpeg_doc_check.get("editing_boundaries_count", 0)
                pattern_agreement_check = jpeg_doc_check.get("pattern_agreement", 0)
                anomalous_regions_check = jpeg_doc_check.get("anomalous_regions", 0)
                cluster_anomalies_check = jpeg_doc_check.get("cluster_anomalies", 0)
                distribution_anomalies_check = jpeg_doc_check.get("distribution_anomalies", 0)
                
                if print_scan_conf_check > 0.1 or jpeg_doc_check.get("camera_recapture", False):
                    camera_recapture_detected = True
                elif (editing_boundaries_count_check == 0 and 
                      pattern_agreement_check < 2.0 and 
                      anomalous_regions_check >= 3 and 
                      anomalous_regions_check <= 10 and
                      overall_score < 65 and
                      max_fail_score < 90 and
                      cluster_anomalies_check < 5 and
                      distribution_anomalies_check < 3):
                    camera_recapture_detected = True
        
        is_re_save_pattern = False
        if jpeg_failed_check and ela_result_check and num_failed == 1:
            ela_status = ela_result_check.get("status", "PASS")
            ela_score = ela_result_check.get("tampering_score", 0)
            jpeg_score = jpeg_failed_check[0].get("tampering_score", 0)
            jpeg_evidence = jpeg_failed_check[0].get("evidence", {})
            doc_analysis = jpeg_evidence.get("document_analysis", {})
            editing_boundaries = doc_analysis.get("editing_boundaries", [])
            editing_boundaries_count = doc_analysis.get("editing_boundaries_count", len(editing_boundaries) if isinstance(editing_boundaries, list) else 0)
            if ela_status == "ESCALATE" and ela_score <= 50 and jpeg_score < 85 and overall_score < 52 and editing_boundaries_count == 0:
                is_re_save_pattern = True
        
        if num_failed >= 2:
            if camera_recapture_detected and max_fail_score < 90:
                should_reject = False
            elif overall_score >= 65:
                should_reject = True
            elif overall_score >= 55 and max_fail_score >= 70:
                should_reject = True
            elif overall_score < 60 and max_fail_score < 90:
                should_reject = False
        elif num_failed == 1:
            if is_re_save_pattern:
                should_reject = False
            elif max_fail_score >= 90:
                should_reject = True
            elif max_fail_score >= 70 and overall_score >= 60:
                should_reject = True
            elif max_fail_score >= 75 and overall_score >= 47:
                should_reject = True
            elif max_fail_score < 70 and overall_score < 50:
                should_reject = False
            elif max_fail_score < 80 and overall_score < 45:
                should_reject = False
        
        if not should_reject:
            escalated_tests_list = [t.get("test") for t in failed]
            if num_failed >= 2:
                reason_text = f"Multiple tests failed ({num_failed}) but overall score ({overall_score:.1f}) suggests review needed - may require manual verification"
            else:
                if max_fail_score < 80 and overall_score < 45:
                    return _create_decision_dict(
                        "ACCEPT", "AUTHENTIC",
                        f"Low confidence anomaly detected (score {max_fail_score}, overall {overall_score:.1f}) - likely natural variation"
                    )
                reason_text = f"Single test failed"
                if max_fail_score < 70:
                    reason_text += f" with low confidence ({max_fail_score})"
                if overall_score < 60:
                    reason_text += f" and overall score ({overall_score:.1f}) suggests review needed"
                reason_text += f" - may be natural variation: {failed[0].get('reason', 'Unknown')}"
            
            reason_text = _add_correlation_reason(reason_text)
            
            decision_dict = _create_decision_dict(
                "ESCALATE", "REVIEW_REQUIRED", reason_text,
                escalated_tests_list=escalated_tests_list
            )
            decision_dict["decision_rationale"] = f"{num_failed} test(s) failed (max score {max_fail_score}, overall {overall_score:.1f}) - requires review"
            return decision_dict
        
        
        if len(failed) > 1:
            reason = f"Multiple tests failed ({len(failed)}): {', '.join([t.get('test') for t in failed[:2]])}"
        else:
            reason = failed[0].get("reason", "Tampering detected")
        
        reason = _add_correlation_reason(reason)
        
        decision_dict = _create_decision_dict(
            "REJECT", "TAMPERED", reason,
            failed_tests_list=[t.get("test") for t in failed]
        )
        decision_dict["decision_rationale"] = f"Failed tests: {', '.join([t.get('test') for t in failed])}. Overall score: {overall_score:.1f}"
        return decision_dict
    
    # =====================================
    # Process Escalated Tests and Return Escalate Decision
    # =====================================
    if escalated:
        all_flags = list(set(all_flags))
        
        copy_move_escalated = any(t.get("test") == "Copy-Move Detection" for t in escalated)
        other_escalated = [t for t in escalated if t.get("test") != "Copy-Move Detection"]
        
        if copy_move_escalated and not other_escalated and len(failed) == 0:
            return _create_decision_dict(
                "ACCEPT", "AUTHENTIC",
                "Copy-move patterns detected but likely legitimate document elements"
            )
        
        reason = escalated[0].get("reason", "Metadata anomalies detected")
        if correlation_analysis["pattern_match"]:
            reason += " (pattern correlation: multiple indicators detected)"
        
        decision_dict = _create_decision_dict(
            "ESCALATE", "REVIEW_REQUIRED", reason,
            escalated_tests_list=[t.get("test") for t in escalated]
        )
        decision_dict["decision_rationale"] = f"Escalated tests: {', '.join([t.get('test') for t in escalated])}"
        return decision_dict
    
    # =====================================
    # Return Accept Decision When All Tests Pass
    # =====================================
    return _create_decision_dict(
        "ACCEPT", "AUTHENTIC", "All forensic tests passed"
    )


def generate_evidence_package(
    file_path: str,
    image,
    test_results: List[Dict],
    decision: Dict,
    evidence_dir: str = DEFAULT_EVIDENCE_DIR
) -> Dict:
    case_id = f"FORENSIC-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    case_dir = os.path.join(evidence_dir, case_id)
    os.makedirs(case_dir, exist_ok=True)
    
    evidence_ext = get_evidence_file_extension(file_path)
    original_filename = f"{EVIDENCE_ORIGINAL_FILENAME}{evidence_ext}"
    
    # =====================================
    # Save Original Image as Visual Evidence
    # =====================================
    cv2.imwrite(os.path.join(case_dir, original_filename), image)
    
    # =====================================
    # Generate JSON Forensic Report
    # =====================================
    report = {
        "case_id": case_id,
        "timestamp": datetime.now().isoformat(),
        "file_path": file_path,
        "decision": decision,
        "test_results": test_results
    }
    
    report_path = os.path.join(case_dir, EVIDENCE_REPORT_FILENAME)
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    
    # =====================================
    # Generate Text Summary Report
    # =====================================
    summary_path = os.path.join(case_dir, EVIDENCE_SUMMARY_FILENAME)
    with open(summary_path, 'w') as f:
        f.write(f"Case ID: {case_id}\n")
        f.write(f"Timestamp: {datetime.now().isoformat()}\n")
        f.write(f"File: {file_path}\n\n")
        f.write(f"Decision: {decision['decision']}\n")
        f.write(f"Status: {decision['status']}\n\n")
        f.write(f"Reason: {decision['reason']}\n\n")
        f.write(f"Tests Run: {len(test_results)}\n")
        f.write(f"Passed: {len([t for t in test_results if t['status'] == 'PASS'])}\n")
        f.write(f"Failed: {len([t for t in test_results if t['status'] == 'FAIL'])}\n\n")
        f.write("Test Results:\n")
        for i, test in enumerate(test_results, 1):
            f.write(f"\n{i}. {test['test']}: {test['status']}\n")
            f.write(f"   {test['reason']}\n")
    
    # =====================================
    # Return Evidence Package Information
    # =====================================
    return {
        "case_id": case_id,
        "timestamp": datetime.now().isoformat(),
        "original_file": file_path,
        "evidence_dir": case_dir,
        "files": [original_filename, EVIDENCE_REPORT_FILENAME, EVIDENCE_SUMMARY_FILENAME]
    }
