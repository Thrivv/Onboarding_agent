import os
import re
from typing import Dict
from datetime import datetime
from PIL import Image
from PIL.ExifTags import TAGS

# =====================================
# Constants
# =====================================
SOFTWARE = 305
DATETIME = 306
DATETIME_ORIGINAL = 36867
DATETIME_DIGITIZED = 36868
SOFTWARE_MIN_LEN = 3
XMP_END_OFFSET = 12
ACTION_MAX_LEN = 100
BASELINE_SCORE = 5
BASELINE_NO_META = 10
FLAG_SEVERITY_BASE = 1.0
FLAG_SEVERITY_MULT = 0.15
EOF_BASE = 50
EOF_MULT = 5
EDITOR_BASE = 60
EDITOR_MULT = 8
TIMESTAMP_BASE = 75
TIMESTAMP_MULT = 5
OTHER_BASE = 40
OTHER_MULT = 6
EOF_MIN = 3
EOF_MAX = 5
EOF_BASE = 3
EOF_MULT = 0.3


def is_editing_software(software_name: str) -> bool:
    if not software_name or len(software_name.strip()) < SOFTWARE_MIN_LEN:
        return False
    
    known_editing_software = [
        'photoshop', 'illustrator', 'indesign', 'premiere', 'after effects',
        'figma', 'sketch', 'gimp', 'inkscape', 'coreldraw', 'affinity',
        'paint.net', 'paint shop', 'picasa', 'lightroom', 'bridge'
    ]
    
    legitimate_software = [
        'telerik', 'adobe acrobat', 'adobe reader', 'microsoft', 'google', 'apple',
        'pdfsharp', 'itext', 'fpdf', 'tcpdf', 'pdfkit', 'windows photo editor',
        'jspdf', 'windows', 'photo editor', 'canva', 'select.pdf', 'select pdf'
    ]
    
    software_lower = software_name.strip().lower()
    for legit_sw in legitimate_software:
        if legit_sw in software_lower:
            return False
    
    for known_sw in known_editing_software:
        if known_sw in software_lower:
            return True
    
    hardware_patterns = [r'\b(EOS|Alpha|D\d+|ScanJet|Perfection|Mark\s+[IVX]+)\b']
    for pattern in hardware_patterns:
        if re.search(pattern, software_name, re.IGNORECASE):
            return False
    
    if re.search(r'\b(CS\d+|\d+\.\d+|v\d+\.\d+)\b', software_name):
        return True
    
    return False


def extract_xmp_metadata(file_path: str, is_image: bool) -> Dict:
    xmp_data = {}
    try:
        xmp_xml = ""
        if is_image:
            with open(file_path, 'rb') as f:
                data = f.read()
                xmp_start = data.find(b'<x:xmpmeta')
                if xmp_start != -1:
                    xmp_end = data.find(b'</x:xmpmeta>', xmp_start)
                    if xmp_end != -1:
                        xmp_xml = data[xmp_start:xmp_end + XMP_END_OFFSET].decode('utf-8', errors='ignore')
                        xmp_data['xmp_present'] = True
        else:
            import fitz
            doc = fitz.open(file_path)
            try:
                xmp_str = doc.metadata.get('xmp', '')
                if xmp_str:
                    xmp_data['xmp_present'] = True
                    xmp_xml = xmp_str
            finally:
                doc.close()
        
        if xmp_xml:
            history_entries = []
            
            if 'photoshop:History' in xmp_xml:
                xmp_data['has_editing_history'] = True
                import xml.etree.ElementTree as ET
                try:
                    root = ET.fromstring(xmp_xml)
                    for elem in root.iter():
                        if 'History' in elem.tag or 'history' in elem.tag.lower():
                            text = elem.text or ""
                            if text and text.strip():
                                history_entries.append({
                                    "action": text.strip(),
                                    "source": "photoshop:History"
                                })
                except (ET.ParseError, ValueError, AttributeError):
                    history_matches = re.findall(r'<photoshop:History[^>]*>(.*?)</photoshop:History>', xmp_xml, re.DOTALL)
                    for match in history_matches:
                        if match.strip():
                            history_entries.append({
                                "action": match.strip()[:ACTION_MAX_LEN],
                                "source": "photoshop:History"
                            })
            
            if 'xmpMM:History' in xmp_xml:
                xmp_data['has_editing_history'] = True
                history_matches = re.findall(r'<xmpMM:History[^>]*>(.*?)</xmpMM:History>', xmp_xml, re.DOTALL)
                for match in history_matches:
                    if match.strip():
                        history_entries.append({
                            "action": match.strip()[:100],
                            "source": "xmpMM:History"
                        })
            
            if history_entries:
                xmp_data['history_entries'] = history_entries
    except Exception:
        pass
    return xmp_data


def check_pdf_incremental_updates(file_path: str) -> int:
    try:
        with open(file_path, 'rb') as f:
            content = f.read()
        eof_count = len(re.findall(b'%%EOF', content))
        return eof_count
    except Exception:
        return 0


def extract_png_metadata(file_path: str) -> Dict:
    png_metadata = {}
    try:
        with Image.open(file_path) as img:
            if hasattr(img, 'text'):
                png_metadata = dict(img.text) if img.text else {}
    except Exception:
        pass
    return png_metadata


def build_metadata_timeline(evidence: Dict) -> Dict:
    canonical = evidence.get("canonical_metadata", {})
    exif = evidence.get("exif", {})
    pdf_meta = evidence.get("pdf", {})
    png_meta = evidence.get("png_metadata", {})
    xmp = evidence.get("xmp", {})
    
    original_creation = (canonical.get("capture_time") or 
                        canonical.get("digitize_time") or
                        (exif.get("datetimeoriginal") if evidence.get("exif_present") else None) or
                        pdf_meta.get("creationDate") or
                        png_meta.get("Creation Time"))
    
    last_modified = (canonical.get("modify_time") or 
                    pdf_meta.get("modDate") or 
                    exif.get("datetime"))
    
    creation_tool = (canonical.get("software") or 
                    canonical.get("creator") or 
                    canonical.get("producer") or
                    exif.get("software") or
                    pdf_meta.get("creator") or
                    pdf_meta.get("producer") or
                    png_meta.get("Software") or
                    "Unknown")
    
    source_type = "EXIF" if evidence.get("exif_present") else ("PDF" if pdf_meta else ("PNG" if png_meta else "Unknown"))
    
    edit_history = []
    modify_time = canonical.get("modify_time")
    
    if original_creation:
        edit_history.append({
            "date": str(original_creation),
            "source": source_type,
            "tool": creation_tool,
                    "event": "Created"
        })
    
    if xmp.get("history_entries"):
        for entry in xmp.get("history_entries", []):
            edit_history.append({
                "date": str(modify_time) if modify_time else "Unknown",
                "source": entry.get("source", "XMP History"),
                "tool": canonical.get("producer") or canonical.get("creator") or canonical.get("software") or "Unknown",
                "event": entry.get("action", "Modified"),
                    "details": entry.get("action", "")
            })
    
    if modify_time and original_creation:
        try:
            if isinstance(modify_time, str) and 'T' in modify_time and isinstance(original_creation, str) and 'T' in original_creation:
                modify_str = modify_time.split('+')[0].split('Z')[0]
                create_str = original_creation.split('+')[0].split('Z')[0]
                modify_dt = datetime.fromisoformat(modify_str)
                create_dt = datetime.fromisoformat(create_str)
                if modify_dt != create_dt:
                    already_added = any(e.get("date") == str(modify_time) for e in edit_history)
                    if not already_added:
                        edit_history.append({
                            "date": str(modify_time),
                            "source": "Metadata",
                            "tool": canonical.get("producer") or canonical.get("creator") or canonical.get("software") or "Unknown",
                            "event": "Modified" if modify_dt > create_dt else "Modified (timestamp anomaly)"
                        })
            elif isinstance(modify_time, str) and isinstance(original_creation, str):
                try:
                    modify_dt = datetime.fromisoformat(modify_time.replace('Z', '+00:00'))
                    create_dt = datetime.fromisoformat(original_creation.replace('Z', '+00:00'))
                    if modify_dt != create_dt:
                        already_added = any(e.get("date") == str(modify_time) for e in edit_history)
                        if not already_added:
                            edit_history.append({
                                "date": str(modify_time),
                                "source": "Metadata",
                                "tool": canonical.get("producer") or canonical.get("creator") or canonical.get("software") or "Unknown",
                                "event": "Modified" if modify_dt > create_dt else "Modified (timestamp anomaly)"
                            })
                except (ValueError, AttributeError):
                    if modify_time != original_creation:
                        already_added = any(e.get("date") == str(modify_time) for e in edit_history)
                        if not already_added:
                            edit_history.append({
                                "date": str(modify_time),
                                "source": "Metadata",
                                "tool": canonical.get("producer") or canonical.get("creator") or canonical.get("software") or "Unknown",
                                "event": "Modified" if modify_time > original_creation else "Modified (timestamp anomaly)"
                            })
        except (ValueError, AttributeError, TypeError):
            pass
    elif modify_time and not original_creation:
        already_added = any(e.get("date") == str(modify_time) for e in edit_history)
        if not already_added:
            edit_history.append({
                "date": str(modify_time),
                "source": "Metadata",
                "tool": canonical.get("producer") or canonical.get("creator") or "Unknown",
                "event": "Modified"
            })
    elif xmp.get("has_editing_history") and not xmp.get("history_entries"):
        already_added = any("XMP History" in e.get("source", "") for e in edit_history)
        if not already_added:
            edit_history.append({
                "date": str(modify_time) if modify_time else "Unknown",
                "source": "XMP History",
                "tool": canonical.get("producer") or canonical.get("creator") or "Unknown",
                "event": "Modified"
            })
    
    try:
        edit_history.sort(key=lambda x: x.get("date", ""), reverse=False)
    except (TypeError, ValueError, AttributeError):
        pass
    
    return {
        "original_creation": original_creation,
        "last_modified": last_modified,
        "total_edits": len(edit_history),
        "edit_history": edit_history,
        "creation_info": {
            "date": original_creation,
            "tool": creation_tool,
            "source": source_type
        } if original_creation else {}
    }


def test_metadata_verification(file_path: str) -> Dict:
    # Initialize Evidence Dictionary
    evidence = {
        "file_path": file_path,
        "exif": {},
        "pdf": {},
        "xmp": {},
        "png_metadata": {},
        "flags": [],
        "errors": [],
        "exif_present": False,
        "canonical_metadata": {
            "software": None,
            "capture_time": None,
            "digitize_time": None,
            "modify_time": None,
            "creator": None,
            "producer": None
        },
        "metadata_history": {}
    }
    
    # Validate Input File
    if not os.path.exists(file_path):
        evidence["errors"].append(f"File not found: {file_path}")
        evidence["flags"].append("file_not_found")
        return {
            "status": "FAIL",
            "evidence": evidence,
            "reason": f"File not found: {file_path}",
            "tampering_score": 0
        }
    
    if not os.path.isfile(file_path):
        evidence["errors"].append(f"Path is not a file: {file_path}")
        evidence["flags"].append("invalid_file_path")
        return {
            "status": "FAIL",
            "evidence": evidence,
            "reason": f"Path is not a file: {file_path}",
            "tampering_score": 0
    }
    
    # Determine File Type
    ext = os.path.splitext(file_path)[1].lower()
    is_image = ext in ['.jpg', '.jpeg', '.png']
    is_pdf = ext == '.pdf'
    
    if ext not in ['.jpg', '.jpeg', '.png', '.pdf']:
        return {
            "status": "PASS",
            "evidence": {"file_path": file_path},
            "reason": "Metadata verification only supports JPG, JPEG, PNG, PDF files",
            "tampering_score": 5
        }
    
    if is_image:
        # Extract EXIF Metadata from Images
        try:
            with Image.open(file_path) as img:
                exif = img.getexif()
                if exif:
                    evidence["exif_present"] = True
                    for tag_id, value in exif.items():
                        tag_name = TAGS.get(tag_id, f"Tag_{tag_id}")
                        evidence["exif"][tag_name] = str(value)
                        
                        if tag_id == SOFTWARE:
                            evidence["canonical_metadata"]["software"] = str(value)
                            evidence["exif"]["software"] = str(value)
                        elif tag_id == DATETIME_ORIGINAL:
                            evidence["canonical_metadata"]["capture_time"] = str(value)
                            evidence["exif"]["datetimeoriginal"] = str(value)
                        elif tag_id == DATETIME_DIGITIZED:
                            evidence["canonical_metadata"]["digitize_time"] = str(value)
                            evidence["exif"]["datetimedigitized"] = str(value)
                        elif tag_id == DATETIME:
                            evidence["canonical_metadata"]["modify_time"] = str(value)
                            evidence["exif"]["datetime"] = str(value)
                
        except Exception as e:
            evidence["errors"].append(f"EXIF extraction failed: {str(e)}")
            evidence["flags"].append("metadata_extraction_error")
        
        # Extract XMP Metadata from Images
        try:
            xmp_data = extract_xmp_metadata(file_path, True)
            if xmp_data:
                evidence["xmp"] = xmp_data
                if xmp_data.get("has_editing_history"):
                    evidence["flags"].append("xmp_editing_history")
        except Exception as e:
            evidence["errors"].append(f"XMP extraction failed: {str(e)}")
        
        # Extract PNG Metadata (for PNG files)
        if ext == '.png':
            try:
                png_meta = extract_png_metadata(file_path)
                if png_meta:
                    evidence["png_metadata"] = png_meta
            except Exception as e:
                evidence["errors"].append(f"PNG metadata extraction failed: {str(e)}")
        
        if not evidence["exif_present"] and ext not in ['.png']:
            evidence["flags"].append("metadata_missing")
    
    # Parse and Validate EXIF Timestamps
    if evidence.get("exif_present"):
        timestamps = {}
        for key in ["datetime", "datetimeoriginal", "datetimedigitized"]:
            if key in evidence["exif"]:
                try:
                    timestamps[key] = datetime.strptime(evidence["exif"][key], "%Y:%m:%d %H:%M:%S")
                except (ValueError, TypeError):
                    pass
        
        if timestamps:
            now = datetime.now()
            for ts in timestamps.values():
                if ts > now:
                    evidence["flags"].append("future_timestamp")
            
            if "datetimeoriginal" in timestamps and "datetime" in timestamps:
                if timestamps["datetimeoriginal"] > timestamps["datetime"]:
                    evidence["flags"].append("timestamp_order_violation")
    
    if is_pdf:
        # Extract PDF Metadata
        creator = ""
        producer = ""
        creation_date = ""
        mod_date = ""
        
        try:
            import fitz
            doc = fitz.open(file_path)
            try:
                pdf_meta = doc.metadata
                evidence["pdf"] = pdf_meta
            
                creator = pdf_meta.get("creator", "") or ""
                producer = pdf_meta.get("producer", "") or ""
                creation_date = pdf_meta.get("creationDate", "") or ""
                mod_date = pdf_meta.get("modDate", "") or ""
                
                evidence["canonical_metadata"]["creator"] = creator if creator else None
                evidence["canonical_metadata"]["producer"] = producer if producer else None
            
                # Parse PDF Date Strings
                def parse_pdf_date(date_str):
                    if date_str and date_str.startswith("D:") and len(date_str) >= 16:
                        try:
                            return datetime.strptime(date_str[2:16], "%Y%m%d%H%M%S").isoformat()
                        except (ValueError, IndexError):
                            pass
                    return date_str if date_str else None
                
                if mod_date:
                    evidence["canonical_metadata"]["modify_time"] = parse_pdf_date(mod_date)
                if creation_date:
                    evidence["canonical_metadata"]["capture_time"] = parse_pdf_date(creation_date)
                
                # Extract XMP Metadata from PDFs
                xmp_data = extract_xmp_metadata(file_path, False)
                if xmp_data:
                    evidence["xmp"] = xmp_data
                    if xmp_data.get("has_editing_history"):
                        evidence["flags"].append("xmp_editing_history")
                
                # Check PDF Incremental Updates (%%EOF count)
                eof_count = check_pdf_incremental_updates(file_path)
                if eof_count > 1:
                    evidence["flags"].append("pdf_incremental_update")
                    evidence["pdf"]["eof_count"] = eof_count
            finally:
                doc.close()
        except ImportError:
            evidence["errors"].append("PyMuPDF not available for PDF processing")
        except Exception as e:
            evidence["errors"].append(f"PDF processing failed: {str(e)}")
            evidence["flags"].append("pdf_extraction_error")
        
        if not (creator or producer or creation_date or mod_date) and "pdf_extraction_error" not in evidence["flags"]:
            evidence["flags"].append("metadata_missing")
        
        # Check PDF Timestamp Order Violations
        capture_time = evidence["canonical_metadata"].get("capture_time")
        modify_time = evidence["canonical_metadata"].get("modify_time")
        
        if capture_time and modify_time:
            try:
                if isinstance(capture_time, str) and 'T' in capture_time and isinstance(modify_time, str) and 'T' in modify_time:
                    capture_str = capture_time.split('+')[0].split('Z')[0]
                    modify_str = modify_time.split('+')[0].split('Z')[0]
                    capture_dt = datetime.fromisoformat(capture_str)
                    modify_dt = datetime.fromisoformat(modify_str)
                    if modify_dt < capture_dt:
                        evidence["flags"].append("timestamp_order_violation")
                elif isinstance(capture_time, str) and isinstance(modify_time, str):
                    try:
                        capture_dt = datetime.fromisoformat(capture_time.replace('Z', '+00:00'))
                        modify_dt = datetime.fromisoformat(modify_time.replace('Z', '+00:00'))
                        if modify_dt < capture_dt:
                            evidence["flags"].append("timestamp_order_violation")
                    except (ValueError, AttributeError):
                        if modify_time < capture_time:
                            evidence["flags"].append("timestamp_order_violation")
            except (ValueError, AttributeError, TypeError):
                pass
    
    # Check for Editing Software Signatures (After All Metadata Extraction)
    canonical = evidence["canonical_metadata"]
    software = canonical.get("software")
    creator = canonical.get("creator")
    producer = canonical.get("producer")
    
    if is_pdf:
        if (creator and is_editing_software(creator)) or (producer and is_editing_software(producer)):
            evidence["flags"].append("pdf_editor_signature")
    else:
        if (software and is_editing_software(software)) or (creator and is_editing_software(creator)):
            evidence["flags"].append("editor_signature")
    
    # Build Metadata History Timeline (Always Include)
    try:
        evidence["metadata_history"] = build_metadata_timeline(evidence)
    except Exception as e:
        evidence["errors"].append(f"Timeline construction failed: {str(e)}")
        evidence["metadata_history"] = {
            "original_creation": None,
            "last_modified": None,
            "total_edits": 0,
            "edit_history": [],
            "creation_info": {}
        }
    
    # =====================================
    # Filter Significant Flags for Decision Making
    # =====================================
    significant_flags = [f for f in evidence["flags"] if f not in ["metadata_missing", "metadata_extraction_error"]]
    
    # =====================================
    # Make Decision Based on Significant Flags
    # =====================================
    if significant_flags:
        # =====================================
        # Calculate Tampering Score (0-100, higher = more tampering risk)
        # =====================================
        tampering_score = 0
        num_flags = len(significant_flags)
        flag_severity_factor = FLAG_SEVERITY_BASE + (num_flags * FLAG_SEVERITY_MULT)
        
        if "pdf_incremental_update" in significant_flags:
            eof_count = evidence.get("pdf", {}).get("eof_count", 0)
            base_score = EOF_BASE + (eof_count * EOF_MULT)
            tampering_score = min(100, int(base_score * flag_severity_factor))
        elif "editor_signature" in significant_flags or "pdf_editor_signature" in significant_flags or "xmp_editing_history" in significant_flags:
            base_score = EDITOR_BASE + (num_flags * EDITOR_MULT)
            tampering_score = min(100, int(base_score * flag_severity_factor))
        elif "future_timestamp" in significant_flags or "timestamp_order_violation" in significant_flags:
            base_score = TIMESTAMP_BASE + (num_flags * TIMESTAMP_MULT)
            tampering_score = min(100, int(base_score * flag_severity_factor))
        else:
            base_score = OTHER_BASE + (num_flags * OTHER_MULT)
            tampering_score = min(100, int(base_score * flag_severity_factor))
        
        if "pdf_incremental_update" in significant_flags:
            eof_count = evidence.get("pdf", {}).get("eof_count", 0)
            eof_thresh = max(EOF_MIN, min(EOF_MAX, EOF_BASE + int(eof_count * EOF_MULT)))
            if eof_count > eof_thresh:
                return {
                    "status": "ESCALATE",
                    "evidence": evidence,
                    "reason": f"PDF incremental update detected ({eof_count} versions - file may have been re-saved multiple times)",
                    "tampering_score": tampering_score
                }
            else:
                significant_flags = [f for f in significant_flags if f != "pdf_incremental_update"]
                if not significant_flags:
                    return {
                        "status": "PASS",
                        "evidence": evidence,
                        "reason": "No significant metadata anomalies detected",
                        "tampering_score": 0
                    }
        if "editor_signature" in significant_flags or "pdf_editor_signature" in significant_flags or "xmp_editing_history" in significant_flags:
            detected_software = software or evidence["canonical_metadata"].get("creator") or evidence["canonical_metadata"].get("producer")
            return {
                "status": "FAIL",
                "evidence": evidence,
                "reason": f"Editing software detected: {detected_software}",
                "tampering_score": tampering_score
            }
        if "future_timestamp" in significant_flags:
            return {
                "status": "FAIL",
                "evidence": evidence,
                "reason": "Future timestamp detected",
                "tampering_score": tampering_score
            }
        if "timestamp_order_violation" in significant_flags:
            return {
                "status": "FAIL",
                "evidence": evidence,
                "reason": "Timestamp order violation (original after modified)",
                "tampering_score": tampering_score
            }
        return {
            "status": "ESCALATE",
            "evidence": evidence,
            "reason": f"Metadata anomalies detected: {', '.join(significant_flags)}",
            "tampering_score": tampering_score
        }
    
    # Return Pass Status When No Significant Issues Found
    # Minimal baseline score - reduced to prevent score inflation
    # Perfect PASS should be 0, only add minimal score if metadata is missing (indicates minor concern)
    has_metadata = evidence.get("exif_present", False) or bool(evidence.get("pdf", {}).get("creator")) or bool(evidence.get("pdf", {}).get("producer"))
    # Reduced baseline: 0 if metadata present, 3 if missing (was 5-10)
    baseline_score = 0 if has_metadata else 3
    
    return {
        "status": "PASS",
        "evidence": evidence,
        "reason": "No editing software signatures or timestamp anomalies detected",
        "tampering_score": baseline_score
    }

