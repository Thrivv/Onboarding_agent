import os
from typing import Dict, List, Set
from collections import Counter

# =====================================
# Constants
# =====================================
FONT_MAX = 8
EMBED_MIN = 80
VARIANCE_MAX = 3
SIZE_CONSIST = 70
SUSPICIOUS_COUNT = 3
ISSUE_WEIGHT_MIN = 15
ISSUE_WEIGHT_MAX = 22
ISSUE_WEIGHT_BASE = 18
ISSUE_MULT = 0.5
FONT_MIN = 8
FONT_MAX_VAL = 15
FONT_BASE = 12
FONT_PAGE_MULT = 0.3
EMBED_MIN_VAL = 80
EMBED_MAX_VAL = 90
EMBED_BASE = 85
EMBED_PAGE_MULT = 0.5
SIZE_MIN_VAL = 70
SIZE_MAX_VAL = 80
SIZE_BASE = 75
SIZE_PAGE_MULT = 0.3
VAR_MIN = 1
VAR_MAX = 3
VAR_BASE = 2
VAR_PAGE_MULT = 0.1
FONT_PENALTY_BASE = 5
FONT_PENALTY_MULT = 0.1
CONSIST_DIV_MIN = 1.2
CONSIST_DIV_MAX = 2.0
CONSIST_DIV_BASE = 1.5
CONSIST_PAGE_MULT = 0.05
SIZE_DIV_MIN = 2.0
SIZE_DIV_MAX = 3.5
SIZE_DIV_BASE = 2.5
SIZE_PAGE_MULT_DIV = 0.08
VAR_PENALTY_BASE = 3
VAR_PENALTY_MULT = 0.2
FAIL_MIN = 95
FAIL_MAX = 100
FAIL_BASE = 98
FAIL_FONT_MULT = 0.3
FAIL_PAGE_MULT = 0.5
ESCALATE_MIN = 90
ESCALATE_MAX = 100
ESCALATE_BASE = 95
ESCALATE_FONT_MULT = 0.2
ESCALATE_PAGE_MULT = 0.3
BASELINE_MIN = 5
BASELINE_MAX = 20
BASELINE_FONT_MULT = 3
BASELINE_ISSUE_MULT = 2


def extract_font_info(file_path: str) -> Dict:
    # =====================================
    # Extract Font Information from PDF
    # =====================================
    fonts_by_page = {}
    all_fonts = []
    font_sizes_by_page = {}
    
    try:
        import fitz
        doc = fitz.open(file_path)
        try:
            for page_num in range(doc.page_count):
                page = doc[page_num]
                page_fonts = page.get_fonts()
                
                fonts_by_page[page_num] = []
                for font_info in page_fonts:
                    font_data = {
                        'name': font_info[3] if len(font_info) > 3 else 'Unknown',
                        'type': font_info[1] if len(font_info) > 1 else 'Unknown',
                        'embedded': font_info[4] if len(font_info) > 4 else False,
                        'subset': font_info[5] if len(font_info) > 5 else False
                    }
                    fonts_by_page[page_num].append(font_data)
                    all_fonts.append(font_data['name'])
                
                if not fonts_by_page[page_num]:
                    fonts_by_page[page_num] = []
                
                text_dict = page.get_text('dict')
                sizes = []
                for block in text_dict.get('blocks', []):
                    if 'lines' in block:
                        for line in block['lines']:
                            for span in line.get('spans', []):
                                size = span.get('size', 0)
                                if size > 0:
                                    sizes.append(size)
                font_sizes_by_page[page_num] = sizes
        finally:
            doc.close()
        
    except ImportError:
        return {
            'fonts_by_page': {},
            'all_fonts': [],
            'font_sizes_by_page': {},
            'error': 'PyMuPDF not available'
        }
    except Exception as e:
        return {
            'fonts_by_page': {},
            'all_fonts': [],
            'font_sizes_by_page': {},
            'error': str(e)
        }
    
    return {
        'fonts_by_page': fonts_by_page,
        'all_fonts': all_fonts,
        'font_sizes_by_page': font_sizes_by_page,
        'error': None
    }


def analyze_font_consistency(font_data: Dict) -> Dict:
    # =====================================
    # Analyze Font Consistency Patterns
    # =====================================
    fonts_by_page = font_data.get('fonts_by_page', {})
    all_fonts = font_data.get('all_fonts', [])
    font_sizes_by_page = font_data.get('font_sizes_by_page', {})
    
    if not fonts_by_page or not all_fonts:
        return {
            'unique_fonts': 0,
            'issues': [],
            'font_distribution': {},
            'embedding_consistency': 0.0,
            'page_font_counts': {},
            'size_consistency': 100.0
        }
    
    unique_fonts = len(set(all_fonts))
    font_counter = Counter(all_fonts)
    
    page_font_counts = {}
    for page_num, fonts in fonts_by_page.items():
        page_font_counts[page_num] = len(set(f['name'] for f in fonts))
    
    embedded_count = 0
    total_font_instances = 0
    for page_fonts in fonts_by_page.values():
        for font in page_fonts:
            total_font_instances += 1
            if font.get('embedded', False):
                embedded_count += 1
    
    embedding_consistency = (embedded_count / total_font_instances * 100) if total_font_instances > 0 else 0.0
    
    all_sizes = []
    for sizes in font_sizes_by_page.values():
        all_sizes.extend(sizes)
    
    size_consistency = 100.0
    if all_sizes:
        unique_sizes = set(all_sizes)
        if len(unique_sizes) > 1:
            size_range = max(all_sizes) - min(all_sizes)
            avg_size = sum(all_sizes) / len(all_sizes)
            size_variance = size_range / avg_size if avg_size > 0 else 0
            size_consistency = max(0, 100 - (size_variance * 50))
    
    issues = []
    
    if unique_fonts > FONT_MAX:
        issues.append(f"Too many unique fonts detected ({unique_fonts})")
    
    if embedding_consistency < EMBED_MIN and total_font_instances > 0:
        issues.append(f"Inconsistent font embedding ({embedding_consistency:.1f}% embedded)")
    
    if page_font_counts:
        font_count_values = list(page_font_counts.values())
        if max(font_count_values) - min(font_count_values) > VARIANCE_MAX:
            issues.append("Inconsistent font count across pages")
    
    if all_sizes and size_consistency < SIZE_CONSIST:
        unique_sizes = len(set(all_sizes))
        if unique_sizes > 5:
            issues.append(f"Inconsistent font sizes detected ({unique_sizes} different sizes)")
    
    suspicious_fonts = ['Calibri', 'Helvetica', 'Arial', 'Times-Roman']
    unique_font_set = set(all_fonts)
    suspicious_count = sum(1 for font in unique_font_set if any(sf in font for sf in suspicious_fonts))
    if suspicious_count > SUSPICIOUS_COUNT:
        issues.append("Multiple suspicious font substitutions detected")
    
    return {
        'unique_fonts': unique_fonts,
        'issues': issues,
        'font_distribution': dict(font_counter),
        'embedding_consistency': embedding_consistency,
        'page_font_counts': page_font_counts,
        'size_consistency': size_consistency
    }


def calculate_font_tampering_score(font_data: Dict, analysis: Dict) -> int:
    # =====================================
    # Calculate Tampering Score
    # =====================================
    score = 0
    
    unique_fonts = analysis.get('unique_fonts', 0)
    issues = analysis.get('issues', [])
    embedding_consistency = analysis.get('embedding_consistency', 100.0)
    size_consistency = analysis.get('size_consistency', 100.0)
    
    if unique_fonts == 0:
        return 0
    
    total_pages = analysis.get('total_pages', 1)
    issue_weight = max(ISSUE_WEIGHT_MIN, min(ISSUE_WEIGHT_MAX, ISSUE_WEIGHT_BASE + (unique_fonts * ISSUE_MULT)))
    font_thresh = max(FONT_MIN, min(FONT_MAX_VAL, FONT_BASE + int(total_pages * FONT_PAGE_MULT)))
    embed_thresh = max(EMBED_MIN_VAL, min(EMBED_MAX_VAL, EMBED_BASE + int(total_pages * EMBED_PAGE_MULT)))
    size_thresh = max(SIZE_MIN_VAL, min(SIZE_MAX_VAL, SIZE_BASE + int(total_pages * SIZE_PAGE_MULT)))
    var_thresh = max(VAR_MIN, min(VAR_MAX, VAR_BASE + int(total_pages * VAR_PAGE_MULT)))
    
    score += len(issues) * int(issue_weight)
    
    if unique_fonts > font_thresh:
        score += (unique_fonts - font_thresh) * int(FONT_PENALTY_BASE + (unique_fonts * FONT_PENALTY_MULT))
    
    if embedding_consistency < embed_thresh and embedding_consistency > 0:
        consistency_penalty = (100 - embedding_consistency) / max(CONSIST_DIV_MIN, min(CONSIST_DIV_MAX, CONSIST_DIV_BASE - (total_pages * CONSIST_PAGE_MULT)))
        score += int(consistency_penalty)
    
    if size_consistency < size_thresh:
        size_penalty = (100 - size_consistency) / max(SIZE_DIV_MIN, min(SIZE_DIV_MAX, SIZE_DIV_BASE - (total_pages * SIZE_PAGE_MULT_DIV)))
        score += int(size_penalty)
    
    page_font_counts = analysis.get('page_font_counts', {})
    if page_font_counts:
        font_count_values = list(page_font_counts.values())
        if len(font_count_values) > 1:
            variance = max(font_count_values) - min(font_count_values)
            if variance > var_thresh:
                score += variance * int(VAR_PENALTY_BASE + (variance * VAR_PENALTY_MULT))
    
    return min(score, FAIL_MAX)


def test_font_consistency(file_path: str) -> Dict:
    # Initialize Evidence Dictionary
    evidence = {
        "file_path": file_path,
        "font_analysis": {}
    }
    
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in ['.pdf', '.jpg', '.jpeg', '.png']:
        return {
            "status": "PASS",
            "evidence": evidence,
            "reason": "Font analysis only applicable to PDF, JPG, JPEG, PNG files",
            "tampering_score": BASELINE_MIN
        }
    
    if ext != '.pdf':
        return {
            "status": "PASS",
            "evidence": evidence,
            "reason": "Font analysis primarily for PDF files; image files processed with baseline score",
            "tampering_score": BASELINE_MIN
        }
    
    try:
        font_data = extract_font_info(file_path)
        
        if font_data.get('error'):
            evidence["font_analysis"]["error"] = font_data['error']
            return {
                "status": "PASS",
                "evidence": evidence,
                "reason": f"Font extraction failed: {font_data['error']}",
                "tampering_score": 0
            }
        
        if not font_data.get('fonts_by_page') or not font_data.get('all_fonts'):
            evidence["font_analysis"] = {
                "unique_fonts": 0,
                "font_distribution": {},
                "embedding_consistency": 0.0,
                "size_consistency": 0.0,
                "page_font_counts": {},
                "issues": ["No fonts detected in document"]
            }
            return {
                "status": "PASS",
                "evidence": evidence,
                "reason": "No fonts detected in document (may be image-based PDF)",
                "tampering_score": 0
            }
        
        # Analyze Font Consistency
        analysis = analyze_font_consistency(font_data)
        
        total_pages = len(font_data.get('fonts_by_page', {}))
        analysis['total_pages'] = total_pages if total_pages > 0 else 1
        
        tampering_score = calculate_font_tampering_score(font_data, analysis)
        
        evidence["font_analysis"] = {
            "unique_fonts": analysis['unique_fonts'],
            "font_distribution": analysis['font_distribution'],
            "embedding_consistency": round(analysis['embedding_consistency'], 2),
            "size_consistency": round(analysis['size_consistency'], 2),
            "page_font_counts": analysis['page_font_counts'],
            "issues": analysis['issues']
        }
        
        unique_fonts = analysis.get('unique_fonts', 0)
        fail_thresh = max(FAIL_MIN, min(FAIL_MAX, FAIL_BASE + (unique_fonts * FAIL_FONT_MULT) - (total_pages * FAIL_PAGE_MULT)))
        escalate_thresh = max(ESCALATE_MIN, min(ESCALATE_MAX, ESCALATE_BASE + (unique_fonts * ESCALATE_FONT_MULT) - (total_pages * ESCALATE_PAGE_MULT)))
        
        if tampering_score >= fail_thresh:
            status = "FAIL"
            reason = f"Font consistency analysis detected {len(analysis['issues'])} issue(s): {', '.join(analysis['issues'][:2])}"
        elif tampering_score >= escalate_thresh:
            status = "ESCALATE"
            reason = f"Font inconsistencies detected: {len(analysis['issues'])} issue(s)"
        else:
            status = "PASS"
            reason = "Font usage appears consistent throughout document"
            if len(analysis.get('issues', [])) > 0:
                baseline_score = min(5, len(analysis.get('issues', [])) * 2)
            else:
                baseline_score = 0
            tampering_score = max(tampering_score, baseline_score)
        
        return {
            "status": status,
            "evidence": evidence,
            "reason": reason,
            "tampering_score": tampering_score
        }
        
    except Exception as e:
        return {
            "status": "PASS",
            "evidence": evidence,
            "reason": f"Font analysis error: {str(e)}",
            "tampering_score": 0
        }

