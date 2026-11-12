import os
import cv2
import numpy as np
from typing import Dict, Tuple
from scipy.fftpack import dct

# =====================================
# Constants
# =====================================
PATTERN_AGREEMENT = 1.7
PATTERN_STRONG = 2.0
PATTERN_MODERATE = 1.5
STD_HIGH = 5.0
STD_MODERATE = 4.0
FREQ_CONF = 0.80
PRINT_SCAN = 0.5
ANOMALY_MIN = 3
ANOMALY_MAX = 8
ANOMALY_FAIL = 6
RE_SAVE_RATIO = 0.6
RE_SAVE_PATTERN = 1.7
PDF_ANOMALY = 7
PDF_CLUSTER = 3
PDF_ANOMALY_TOTAL = 9
PDF_FREQ_ANOMALY = 9
PDF_PATTERN = 2.0
PDF_ANOMALY_MIN = 6
PDF_CLUSTER_MIN = 3
PNG_FREQ = 0.85
MULTIPLE_TABLES = 2
TABLE_RANGE = 9


def load_image(file_path: str) -> Tuple[np.ndarray, str]:
    # =====================================
    # Validate Input File
    # =====================================
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    
    if not os.path.isfile(file_path):
        raise ValueError(f"Path is not a file: {file_path}")
    
    # =====================================
    # Determine File Extension and Load Image
    # =====================================
    ext = os.path.splitext(file_path)[1].lower()
    
    if ext == '.pdf':
        image = extract_from_pdf(file_path)
        return image, 'pdf'
    elif ext in ['.jpg', '.jpeg', '.png']:
        image = cv2.imread(file_path)
        if image is None:
            raise ValueError(f"Could not load image from {file_path}")
        return image, 'image'
    else:
        raise ValueError(f"Unsupported file type: {ext}")


def extract_from_pdf(file_path: str) -> np.ndarray:
    # =====================================
    # Extract First Image from PDF Document
    # =====================================
    try:
        import fitz
        doc = fitz.open(file_path)
        try:
            if doc.page_count == 0:
                raise ValueError("PDF has no pages")
            images = doc[0].get_images(full=True)
            if not images:
                pix = doc[0].get_pixmap(matrix=fitz.Matrix(2, 2))
                img_data = pix.tobytes("png")
                image = cv2.imdecode(np.frombuffer(img_data, np.uint8), cv2.IMREAD_COLOR)
                if image is None:
                    raise ValueError("Could not render PDF page as image")
                return image
            image_bytes = doc.extract_image(images[0][0])["image"]
            image = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                raise ValueError("Could not decode image from PDF")
            return image
        finally:
            doc.close()
    except Exception as e:
        raise ValueError(f"Error extracting image from PDF: {str(e)}")


def extract_quantization_tables(file_path: str) -> Dict:
    # =====================================
    # Initialize Tables Dictionary and Read File
    # =====================================
    tables = {}
    try:
        with open(file_path, 'rb') as f:
            data = f.read()
        
        # =====================================
        # Search for Quantization Table Markers
        # =====================================
        pos = 0
        while pos < len(data):
            marker_pos = data.find(b'\xFF\xDB', pos)
            if marker_pos == -1:
                break
            
            if marker_pos + 3 >= len(data):
                break
            
            # =====================================
            # Extract Table ID and Precision Information
            # =====================================
            table_info = data[marker_pos + 2]
            table_id = table_info & 0x0F
            precision = (table_info & 0xF0) >> 4
            
            table_values = []
            start_pos = marker_pos + 3
            
            # =====================================
            # Read Table Values Based on Precision
            # =====================================
            if precision == 0:
                if start_pos + 64 > len(data):
                    break
                for i in range(64):
                    table_values.append(data[start_pos + i])
            else:
                if start_pos + 128 > len(data):
                    break
                for i in range(64):
                    value = (data[start_pos + i*2] << 8) | data[start_pos + i*2 + 1]
                    table_values.append(value)
            
            # =====================================
            # Reshape Table Values into 8x8 Matrix
            # =====================================
            if len(table_values) == 64:
                table_matrix = np.array(table_values).reshape(8, 8)
                tables[table_id] = table_matrix
            
            pos = marker_pos + 1
        
        return tables
    except Exception as e:
        return {"error": str(e)}


def estimate_local_quantization(image_region: np.ndarray) -> float:
    try:
        if len(image_region.shape) == 3:
            gray = np.mean(image_region, axis=2).astype(np.float32)
        else:
            gray = image_region.astype(np.float32)
        
        h, w = gray.shape
        h = (h // 8) * 8
        w = (w // 8) * 8
        gray = gray[:h, :w]
        
        if h < 16 or w < 16:
            return 30.0
        
        q_estimates = []
        
        step = 16
        for y in range(0, h - 7, step):
            for x in range(0, w - 7, step):
                block = gray[y:y+8, x:x+8]
                
                # =====================================
                # Apply 2D DCT Transform to Block
                # =====================================
                dct_block = np.zeros_like(block, dtype=np.float64)
                for i in range(8):
                    dct_block[i, :] = dct(block[i, :], norm='ortho')
                for j in range(8):
                    dct_block[:, j] = dct(dct_block[:, j], norm='ortho')
                
                # =====================================
                # Estimate Quantization from High Frequency Components
                # =====================================
                high_freq = np.abs(dct_block[4:, 4:])
                non_zero_count = np.count_nonzero(high_freq > 0.5)
                
                if non_zero_count > 0:
                    q_estimate = 50.0 / (1 + non_zero_count / 8.0)
                else:
                    q_estimate = 35.0
                
                q_estimates.append(q_estimate)
        
        return np.mean(q_estimates) if q_estimates else 30.0
    except Exception:
        return 30.0


def detect_print_scan_cycles(image: np.ndarray, file_path: str) -> Dict:
    try:
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
        else:
            gray = image.astype(np.float32)
        
        h, w = gray.shape
        if h < 64 or w < 64:
            return {"detected": False, "confidence": 0.0, "indicators": []}
        
        max_dim = 512
        if h > max_dim or w > max_dim:
            scale = max_dim / max(h, w)
            gray = cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
            h, w = gray.shape
        
        gray_uint8 = (gray * 255).astype(np.uint8) if gray.max() <= 1.0 else gray.astype(np.uint8)
        
        indicators = []
        confidence = 0.0
        
        fft = np.fft.fft2(gray)
        fft_shift = np.fft.fftshift(fft)
        magnitude = np.abs(fft_shift)
        phase = np.angle(fft_shift)
        
        center_h, center_w = h // 2, w // 2
        radius = min(h, w) // 4
        
        y, x = np.ogrid[:h, :w]
        mask = (x - center_w)**2 + (y - center_h)**2 <= radius**2
        center_energy = np.sum(magnitude[mask])
        total_energy = np.sum(magnitude)
        center_ratio = center_energy / (total_energy + 1e-6)
        
        phase_std = np.std(phase)
        phase_mean = np.mean(phase)
        
        if center_ratio > 0.55:
            indicators.append("high_center_frequency_energy")
            confidence += 0.25
        
        if phase_std < 0.6 or phase_std > 2.5:
            indicators.append("phase_spectrum_anomaly")
            confidence += 0.20
        
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        lap_var = cv2.blur((laplacian ** 2), (5, 5))
        lap_mean = np.mean(lap_var)
        lap_std = np.std(lap_var)
        
        if lap_mean < 0.0008 and lap_std < 0.0004:
            indicators.append("unnatural_smoothness_pattern")
            confidence += 0.20
        
        hist, _ = np.histogram(gray_uint8.flatten(), bins=128, range=(0, 256))
        hist_norm = hist / (h * w + 1e-6)
        peaks = len([i for i in range(1, len(hist)-1) if hist[i] > hist[i-1] and hist[i] > hist[i+1] and hist[i] > np.max(hist) * 0.15])
        
        hist_entropy = -np.sum((hist_norm + 1e-10) * np.log(hist_norm + 1e-10))
        
        if peaks > 4:
            indicators.append("multiple_compression_artifacts")
            confidence += 0.30
        
        if hist_entropy < 4.5:
            indicators.append("histogram_entropy_anomaly")
            confidence += 0.15
        
        edges = cv2.Canny(gray_uint8, 30, 100)
        edge_density = np.sum(edges > 0) / edges.size
        
        edges_coarse = cv2.Canny(gray_uint8, 50, 150)
        edge_density_coarse = np.sum(edges_coarse > 0) / edges_coarse.size
        
        edge_ratio = edge_density / (edge_density_coarse + 1e-6)
        
        if edge_density < 0.015:
            indicators.append("camera_recapture_pattern")
            confidence += 0.15
        
        if edge_ratio > 2.0 or edge_ratio < 0.3:
            indicators.append("multi_scale_edge_inconsistency")
            confidence += 0.15
        
        sobel_x = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
        sobel_y = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
        sobel_mag = np.sqrt(sobel_x**2 + sobel_y**2)
        sobel_mean = np.mean(sobel_mag)
        sobel_std = np.std(sobel_mag)
        
        if sobel_mean < 0.01 and sobel_std < 0.005:
            indicators.append("gradient_magnitude_anomaly")
            confidence += 0.15
        
        grid_rows, grid_cols = 4, 4
        region_h, region_w = h // grid_rows, w // grid_cols
        region_variances = []
        
        for row in range(grid_rows):
            for col in range(grid_cols):
                y = row * region_h
                x = col * region_w
                region = gray[y:y+region_h, x:x+region_w]
                region_variances.append(np.var(region))
        
        variance_mean = np.mean(region_variances)
        variance_std = np.std(region_variances)
        variance_cv = variance_std / (variance_mean + 1e-6)
        
        if variance_cv < 0.1:
            indicators.append("uniform_variance_pattern")
            confidence += 0.15
        
        detected = confidence >= 0.50
        
        return {
            "detected": detected,
            "confidence": min(confidence, 1.0),
            "indicators": indicators
        }
    except Exception:
        return {"detected": False, "confidence": 0.0, "indicators": []}


def analyze_frequency_domain(image: np.ndarray, file_path: str) -> Dict:
    try:
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
        else:
            gray = image.astype(np.float32)
        
        h, w = gray.shape
        if h < 64 or w < 64:
            return {"detected": False, "anomalies": [], "confidence": 0.0}
        
        max_dim = 512
        if h > max_dim or w > max_dim:
            scale = max_dim / max(h, w)
            new_h, new_w = int(h * scale), int(w * scale)
            gray = cv2.resize(gray, (new_w, new_h), interpolation=cv2.INTER_AREA)
        
        h_aligned = (gray.shape[0] // 8) * 8
        w_aligned = (gray.shape[1] // 8) * 8
        gray = gray[:h_aligned, :w_aligned]
        
        fft = np.fft.fft2(gray)
        fft_shift = np.fft.fftshift(fft)
        fft_magnitude = np.abs(fft_shift)
        fft_phase = np.angle(fft_shift)
        
        anomalies = []
        dct_coefficients = []
        block_correlations = []
        
        step = 8
        for y in range(0, h_aligned - 7, step):
            for x in range(0, w_aligned - 7, step):
                block = gray[y:y+8, x:x+8]
                
                dct_block = np.zeros_like(block, dtype=np.float64)
                for i in range(8):
                    dct_block[i, :] = dct(block[i, :], norm='ortho')
                for j in range(8):
                    dct_block[:, j] = dct(dct_block[:, j], norm='ortho')
                
                dc = abs(dct_block[0, 0])
                low_freq = np.abs(dct_block[0:4, 0:4])
                mid_freq = np.abs(dct_block[2:6, 2:6])
                high_freq = np.abs(dct_block[4:, 4:])
                
                ac_energy = np.sum(np.abs(dct_block[1:, 1:]))
                dc_energy = abs(dc)
                ac_dc_ratio = ac_energy / (dc_energy + 1e-6)
                
                freq_distribution = [
                    np.mean(low_freq),
                    np.mean(mid_freq),
                    np.mean(high_freq)
                ]
                freq_variance = np.var(freq_distribution)
                
                coeff_hist = np.histogram(dct_block.flatten(), bins=32)[0]
                coeff_entropy = -np.sum((coeff_hist / (coeff_hist.sum() + 1e-6)) * np.log(coeff_hist / (coeff_hist.sum() + 1e-6) + 1e-10))
                
                zero_coeff_ratio = np.sum(np.abs(dct_block) < 0.1) / dct_block.size
                
                dct_coefficients.append({
                    "dc": float(dc),
                    "low_freq_mean": float(np.mean(low_freq)),
                    "low_freq_std": float(np.std(low_freq)),
                    "mid_freq_mean": float(np.mean(mid_freq)),
                    "mid_freq_std": float(np.std(mid_freq)),
                    "high_freq_mean": float(np.mean(high_freq)),
                    "high_freq_std": float(np.std(high_freq)),
                    "ac_dc_ratio": float(ac_dc_ratio),
                    "freq_variance": float(freq_variance),
                    "coeff_entropy": float(coeff_entropy),
                    "zero_coeff_ratio": float(zero_coeff_ratio),
                    "position": (int(x), int(y))
                })
        
        if len(dct_coefficients) < 4:
            return {"detected": False, "anomalies": [], "confidence": 0.0}
        
        for i in range(len(dct_coefficients) - 1):
            for j in range(i + 1, min(i + 3, len(dct_coefficients))):
                c1, c2 = dct_coefficients[i], dct_coefficients[j]
                dc_corr = abs(c1["dc"] - c2["dc"]) / (max(abs(c1["dc"]), abs(c2["dc"])) + 1e-6)
                freq_corr = abs(c1["low_freq_mean"] - c2["low_freq_mean"]) / (max(c1["low_freq_mean"], c2["low_freq_mean"]) + 1e-6)
                block_correlations.append({
                    "dc_corr": float(dc_corr),
                    "freq_corr": float(freq_corr),
                    "positions": (c1["position"], c2["position"])
                })
        
        dc_values = [c["dc"] for c in dct_coefficients]
        low_freq_means = [c["low_freq_mean"] for c in dct_coefficients]
        mid_freq_means = [c["mid_freq_mean"] for c in dct_coefficients]
        high_freq_means = [c["high_freq_mean"] for c in dct_coefficients]
        ac_dc_ratios = [c["ac_dc_ratio"] for c in dct_coefficients]
        freq_variances = [c["freq_variance"] for c in dct_coefficients]
        coeff_entropies = [c.get("coeff_entropy", 0.0) for c in dct_coefficients]
        zero_coeff_ratios = [c.get("zero_coeff_ratio", 0.0) for c in dct_coefficients]
        
        dc_mean = np.mean(dc_values)
        dc_std = np.std(dc_values)
        low_freq_mean = np.mean(low_freq_means)
        low_freq_std = np.std(low_freq_means)
        mid_freq_mean = np.mean(mid_freq_means)
        mid_freq_std = np.std(mid_freq_means)
        high_freq_mean = np.mean(high_freq_means)
        high_freq_std = np.std(high_freq_means)
        ac_dc_mean = np.mean(ac_dc_ratios)
        ac_dc_std = np.std(ac_dc_ratios)
        freq_var_mean = np.mean(freq_variances)
        freq_var_std = np.std(freq_variances)
        entropy_mean = np.mean(coeff_entropies) if coeff_entropies else 0.0
        entropy_std = np.std(coeff_entropies) if coeff_entropies else 0.0
        zero_ratio_mean = np.mean(zero_coeff_ratios) if zero_coeff_ratios else 0.0
        zero_ratio_std = np.std(zero_coeff_ratios) if zero_coeff_ratios else 0.0
        
        center_h, center_w = h_aligned // 2, w_aligned // 2
        radius = min(h_aligned, w_aligned) // 4
        y_coords, x_coords = np.ogrid[:h_aligned, :w_aligned]
        center_mask = (x_coords - center_w)**2 + (y_coords - center_h)**2 <= radius**2
        center_energy = np.sum(fft_magnitude[center_mask])
        total_energy = np.sum(fft_magnitude)
        center_ratio = center_energy / (total_energy + 1e-6)
        
        phase_std = np.std(fft_phase)
        
        for coeff in dct_coefficients:
            is_anomalous = False
            reasons = []
            anomaly_score = 0.0
            
            if dc_std > 0:
                dc_z_score = abs(coeff["dc"] - dc_mean) / dc_std
                if dc_z_score > 2.5:
                    is_anomalous = True
                    reasons.append("unusual_dc_component")
                    anomaly_score += 0.20
            
            if coeff["low_freq_mean"] < low_freq_mean - 2.0 * low_freq_std:
                if coeff["high_freq_mean"] > high_freq_mean - high_freq_std:
                    is_anomalous = True
                    reasons.append("frequency_masking")
                    anomaly_score += 0.25
            
            if coeff["low_freq_std"] < low_freq_mean * 0.06 and coeff["high_freq_std"] < high_freq_mean * 0.06:
                is_anomalous = True
                reasons.append("unnatural_dct_pattern")
                anomaly_score += 0.20
            
            if abs(coeff["ac_dc_ratio"] - ac_dc_mean) > 1.8 * ac_dc_std:
                is_anomalous = True
                reasons.append("ac_dc_ratio_anomaly")
                anomaly_score += 0.15
            
            if coeff["freq_variance"] < freq_var_mean - 1.8 * freq_var_std:
                is_anomalous = True
                reasons.append("frequency_distribution_anomaly")
                anomaly_score += 0.15
            
            if coeff["mid_freq_mean"] > mid_freq_mean + 1.8 * mid_freq_std:
                is_anomalous = True
                reasons.append("mid_frequency_manipulation")
                anomaly_score += 0.20
            
            if abs(coeff["coeff_entropy"] - entropy_mean) > 1.5 * entropy_std:
                is_anomalous = True
                reasons.append("coefficient_entropy_anomaly")
                anomaly_score += 0.15
            
            if abs(coeff["zero_coeff_ratio"] - zero_ratio_mean) > 1.5 * zero_ratio_std:
                is_anomalous = True
                reasons.append("zero_coefficient_ratio_anomaly")
                anomaly_score += 0.15
            
            if is_anomalous:
                anomalies.append({
                    "position": coeff["position"],
                    "reasons": reasons,
                    "dc": coeff["dc"],
                    "low_freq_mean": coeff["low_freq_mean"],
                    "mid_freq_mean": coeff["mid_freq_mean"],
                    "high_freq_mean": coeff["high_freq_mean"],
                    "ac_dc_ratio": coeff["ac_dc_ratio"],
                    "anomaly_score": float(anomaly_score)
                })
        
        if block_correlations:
            corr_mean = np.mean([c["dc_corr"] for c in block_correlations])
            corr_std = np.std([c["dc_corr"] for c in block_correlations])
            inconsistent_blocks = sum(1 for c in block_correlations 
                                    if c["dc_corr"] > corr_mean + 2 * corr_std or 
                                       c["freq_corr"] > 0.3)
            if inconsistent_blocks > len(block_correlations) * 0.15:
                anomalies.append({
                    "position": (0, 0),
                    "reasons": ["block_correlation_inconsistency"],
                    "dc": 0.0,
                    "low_freq_mean": 0.0,
                    "mid_freq_mean": 0.0,
                    "high_freq_mean": 0.0,
                    "ac_dc_ratio": 0.0,
                    "anomaly_score": 0.25
                })
        
        if center_ratio > 0.65 or phase_std < 0.5:
            anomalies.append({
                "position": (center_w, center_h),
                "reasons": ["fft_spectrum_anomaly"],
                "dc": 0.0,
                "low_freq_mean": 0.0,
                "mid_freq_mean": 0.0,
                "high_freq_mean": 0.0,
                "ac_dc_ratio": 0.0,
                "anomaly_score": 0.20
            })
        
        detected = len(anomalies) >= 1
        total_anomaly_score = sum(a.get("anomaly_score", 0.1) for a in anomalies)
        confidence = min(total_anomaly_score / max(len(anomalies), 1), 1.0) if detected else 0.0
        
        return {
            "detected": detected,
            "anomalies": anomalies,
            "confidence": float(confidence),
            "anomaly_count": len(anomalies),
            "total_blocks": len(dct_coefficients)
        }
    except Exception:
        return {"detected": False, "anomalies": [], "confidence": 0.0}


def test_jpeg_quantization(file_path: str, image: np.ndarray) -> Dict:
    # =====================================
    # Initialize Evidence Dictionary
    # =====================================
    evidence = {
        "file_path": file_path,
        "quantization_tables": {}
    }
    
    # =====================================
    # Check if File is JPEG Format or PDF with Image
    # =====================================
    ext = os.path.splitext(file_path)[1].lower()
    is_pdf = file_path.lower().endswith('.pdf')
    is_jpeg = file_path.lower().endswith(('.jpg', '.jpeg'))
    is_png = file_path.lower().endswith('.png')
    
    if ext not in ['.jpg', '.jpeg', '.png', '.pdf']:
        return {
            "status": "PASS",
            "evidence": evidence,
            "reason": "Quantization analysis only supports JPG, JPEG, PNG, PDF files",
            "tampering_score": 0
        }
    
    # =====================================
    # Extract Quantization Tables from JPEG File (skip for PDFs and PNGs)
    # =====================================
    if is_jpeg:
        tables = extract_quantization_tables(file_path)
        
        if "error" in tables:
            return {
                "status": "PASS",
                "evidence": evidence,
                "reason": f"Could not extract quantization tables: {tables['error']}",
                "tampering_score": 0
            }
        
        if not tables:
            return {
                "status": "PASS",
                "evidence": evidence,
                "reason": "No quantization tables found in file",
                "tampering_score": 0
            }
        
        evidence["quantization_tables"] = {str(k): v.tolist() for k, v in tables.items()}
        
        # =====================================
        # Check for Multiple Distinct Quantization Tables
        # =====================================
        if len(tables) > MULTIPLE_TABLES:
            table_means = [np.mean(table) for table in tables.values()]
            table_range = max(table_means) - min(table_means)
            if table_range > TABLE_RANGE:
                return {
                    "status": "FAIL",
                    "evidence": evidence,
                    "reason": "Multiple distinct quantization tables detected (possible re-save or manipulation)",
                    "tampering_score": 85
                }
    
    # =====================================
    # Frequency Domain Analysis (Detect DCT Manipulation)
    # =====================================
    frequency_analysis = analyze_frequency_domain(image, file_path)
    evidence["frequency_analysis"] = frequency_analysis
    
    if is_png:
        frequency_detected = frequency_analysis.get("detected", False)
        frequency_confidence = frequency_analysis.get("confidence", 0.0)
        
        if frequency_detected and frequency_confidence > PNG_FREQ:
            return {
                "status": "FAIL",
                "evidence": evidence,
                "reason": f"Frequency-domain manipulation detected in PNG (confidence: {frequency_confidence:.2f})",
                "tampering_score": min(100, int(60 + (frequency_confidence * 30)))
            }
        else:
            baseline_score = max(1, min(10, int(frequency_confidence * 15)))
            return {
                "status": "PASS",
                "evidence": evidence,
                "reason": "PNG file analyzed - no frequency-domain anomalies detected",
                "tampering_score": baseline_score
            }
    
    # =====================================
    # Divide Document into Grid Regions for Analysis
    # =====================================
    h, w = image.shape[:2]
    
    grid_rows, grid_cols = 4, 4
    region_h, region_w = h // grid_rows, w // grid_cols
    
    all_region_q_values = []
    region_results = []
    
    for row in range(grid_rows):
        for col in range(grid_cols):
            y = row * region_h
            x = col * region_w
            region_h_actual = region_h if row < grid_rows - 1 else h - y
            region_w_actual = region_w if col < grid_cols - 1 else w - x
            
            if region_h_actual < 8 or region_w_actual < 8:
                continue
            
            # =====================================
            # Estimate Quantization Value for Each Region
            # =====================================
            region = image[y:y+region_h_actual, x:x+region_w_actual]
            region_q = estimate_local_quantization(region)
            all_region_q_values.append(region_q)
            region_results.append({
                "position": (int(x), int(y), int(region_w_actual), int(region_h_actual)),
                "q_value": float(region_q)
            })
    
    if len(all_region_q_values) < 4:
        return {
            "status": "PASS",
            "evidence": evidence,
            "reason": "Document too small for regional analysis",
            "tampering_score": 0
        }
    
    # =====================================
    # Calculate Document-Wide Statistics
    # =====================================
    doc_mean_q = np.mean(all_region_q_values)
    doc_std_q = np.std(all_region_q_values)
    doc_cv = doc_std_q / (doc_mean_q + 1e-6)
    
    # =====================================
    # Intelligent Pattern-Based Detection
    # =====================================
    grid_positions = {}
    for i, (row, col) in enumerate([(r, c) for r in range(grid_rows) for c in range(grid_cols)]):
        if i < len(all_region_q_values):
            grid_positions[i] = (row, col)
    
    # =====================================
    # Pattern 1: Neighbor Comparison Analysis
    # =====================================
    neighbor_anomalies = []
    editing_boundaries = []
    
    for i, region_q in enumerate(all_region_q_values):
        if i not in grid_positions:
            continue
            
        row, col = grid_positions[i]
        neighbors = []
        
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            n_row, n_col = row + dr, col + dc
            if 0 <= n_row < grid_rows and 0 <= n_col < grid_cols:
                neighbor_idx = n_row * grid_cols + n_col
                if neighbor_idx < len(all_region_q_values):
                    neighbors.append((neighbor_idx, all_region_q_values[neighbor_idx]))
        
        if neighbors:
            neighbor_values = [nq for _, nq in neighbors]
            neighbor_mean = np.mean(neighbor_values)
            neighbor_std = np.std(neighbor_values) if len(neighbors) > 1 else abs(neighbor_mean - region_q)
            
            diff_from_neighbors = abs(region_q - neighbor_mean)
            neighbor_relative_diff = diff_from_neighbors / (neighbor_mean + 1e-6)
            
            if neighbor_std > 0:
                neighbor_z = diff_from_neighbors / (neighbor_std + 1e-6)
                is_anomalous = neighbor_z > 2.0 or neighbor_relative_diff > 0.25
            else:
                is_anomalous = neighbor_relative_diff > 0.25
            
            if is_anomalous:
                neighbor_anomalies.append(i)
                if neighbor_relative_diff > 0.3:
                    editing_boundaries.append(i)
    
    # =====================================
    # Pattern 2: Clustering Analysis
    # =====================================
    cluster_anomalies = []
    cluster_separation_ratio = 0.0
    if len(all_region_q_values) >= 4:
        try:
            q_array = np.array(all_region_q_values)
            center1 = np.min(q_array)
            center2 = np.max(q_array)
            
            for _ in range(10):
                clusters = np.zeros(len(q_array), dtype=int)
                for i, q_val in enumerate(q_array):
                    if abs(q_val - center1) < abs(q_val - center2):
                        clusters[i] = 0
                    else:
                        clusters[i] = 1
                
                if np.sum(clusters == 0) > 0:
                    center1 = np.mean(q_array[clusters == 0])
                if np.sum(clusters == 1) > 0:
                    center2 = np.mean(q_array[clusters == 1])
            
            cluster_separation = abs(center1 - center2)
            cluster_separation_ratio = cluster_separation / (doc_mean_q + 1e-6)
            
            if cluster_separation_ratio > 0.15:
                cluster_counts = [np.sum(clusters == 0), np.sum(clusters == 1)]
                min_cluster_size = min(cluster_counts)
                
                if min_cluster_size >= 2 and min_cluster_size < len(all_region_q_values) * 0.4:
                    smaller_cluster = 0 if cluster_counts[0] < cluster_counts[1] else 1
                    cluster_anomalies = [i for i, c in enumerate(clusters) if c == smaller_cluster]
        except (ValueError, IndexError, ZeroDivisionError):
            pass
    
    # =====================================
    # Pattern 3: Distribution Pattern Analysis
    # =====================================
    q_median = np.median(all_region_q_values)
    
    distribution_anomalies = []
    for i, region_q in enumerate(all_region_q_values):
        median_deviation = abs(region_q - q_median) / (q_median + 1e-6)
        percentile_rank = (np.sum(np.array(all_region_q_values) <= region_q) / len(all_region_q_values)) * 100
        
        if median_deviation > 0.2 and (percentile_rank < 10 or percentile_rank > 90):
            distribution_anomalies.append(i)
    
    # =====================================
    # Pattern 4: Compression Pattern Detection
    # =====================================
    compression_anomalies = []
    compression_std = np.std(all_region_q_values)
    
    for i, region_q in enumerate(all_region_q_values):
        std_deviations = abs(region_q - doc_mean_q) / (compression_std + 1e-6)
        relative_diff = abs(region_q - doc_mean_q) / (doc_mean_q + 1e-6)
        
        if std_deviations > 2.0 or (relative_diff > 0.2 and std_deviations > 1.5):
            compression_anomalies.append(i)
    
    all_anomalies = set(neighbor_anomalies + cluster_anomalies + distribution_anomalies + compression_anomalies)
    
    for i in range(len(all_region_q_values)):
        if i in all_anomalies:
            region_results[i]["status"] = "FAIL"
            region_results[i]["difference"] = float(abs(all_region_q_values[i] - doc_mean_q))
            region_results[i]["relative_difference"] = float(abs(all_region_q_values[i] - doc_mean_q) / (doc_mean_q + 1e-6))
        else:
            region_results[i]["status"] = "PASS"
    
    # =====================================
    # Calculate Pattern Metrics
    # =====================================
    anomaly_density = len(all_anomalies) / (len(all_region_q_values) + 1e-6)
    pattern_count = len([p for p in [neighbor_anomalies, cluster_anomalies, distribution_anomalies, compression_anomalies] if len(p) > 0])
    expected_variation = max(1, int(len(all_region_q_values) * 0.1))
    anomaly_ratio = len(all_anomalies) / (expected_variation + 1e-6)
    
    pattern_agreement = 0
    if len(all_anomalies) > 0:
        pattern_scores = {}
        for pattern in [neighbor_anomalies, cluster_anomalies, distribution_anomalies, compression_anomalies]:
            for anomaly in pattern:
                pattern_scores[anomaly] = pattern_scores.get(anomaly, 0) + 1
        if pattern_scores:
            pattern_agreement = np.mean(list(pattern_scores.values()))
    
    # =====================================
    # Check Frequency Domain Analysis Results
    # =====================================
    frequency_detected = frequency_analysis.get("detected", False)
    frequency_confidence = frequency_analysis.get("confidence", 0.0)
    
    # =====================================
    # Check Print-Scan-Photo Cycle Detection
    # =====================================
    print_scan_analysis = detect_print_scan_cycles(image, file_path)
    print_scan_detected = print_scan_analysis.get("detected", False)
    print_scan_confidence = print_scan_analysis.get("confidence", 0.0)
    
    # =====================================
    # Intelligent Decision Logic
    # =====================================
    has_editing_boundaries = len(editing_boundaries) >= 2
    has_clustered_anomalies = len(cluster_anomalies) >= 2
    
    # =====================================
    # Re-save Pattern Detection
    # =====================================
    total_regions = len(all_region_q_values)
    anomaly_ratio = len(all_anomalies) / max(1, total_regions)
    
    re_save_std = max(4.0, min(7.5, doc_std_q * 1.25 + (doc_cv * 0.35)))
    re_save_anomaly = max(6, min(11, int(total_regions * 0.65)))
    re_save_cluster = max(5, min(9, int(total_regions * 0.55)))
    
    is_re_save_pattern = (len(editing_boundaries) == 0 and 
                          doc_std_q < re_save_std and 
                          len(all_anomalies) <= re_save_anomaly and
                          len(cluster_anomalies) < re_save_cluster and
                          anomaly_ratio < 1.0 and
                          pattern_agreement < RE_SAVE_PATTERN and
                          (not has_clustered_anomalies or len(cluster_anomalies) < PDF_CLUSTER) and
                          len(all_anomalies) >= ANOMALY_MIN and
                          len(all_anomalies) <= ANOMALY_MAX)
    
    cluster_thresh = max(2, min(4, int(total_regions * 0.18)))
    anomaly_primary = max(4, min(9, int(total_regions * 0.40)))
    anomaly_secondary = max(3, min(6, int(total_regions * 0.28)))
    anomaly_tertiary = max(3, min(7, int(total_regions * 0.32)))
    separation_thresh = max(0.10, min(0.18, 0.12 + (doc_cv * 0.01)))
    ratio_secondary = max(1.8, min(3.0, 2.2 + (doc_cv * 0.08)))
    ratio_tertiary = max(2.2, min(3.5, 2.7 + (doc_cv * 0.10)))
    pattern_primary = max(PATTERN_STRONG, min(3.5, 2.5 + (anomaly_ratio * 0.3)))
    pattern_tertiary = max(PATTERN_MODERATE, min(2.5, PATTERN_STRONG + (anomaly_ratio * 0.2)))
    freq_thresh = max(0.60, min(0.75, 0.65 + (frequency_confidence * 0.05)))
    freq_anomaly = max(2, min(5, int(total_regions * 0.15)))
    
    primary_indicators = (
        has_editing_boundaries or
        (has_clustered_anomalies and len(cluster_anomalies) >= cluster_thresh and cluster_separation_ratio > separation_thresh and not is_re_save_pattern) or
        (pattern_agreement >= pattern_primary and len(all_anomalies) >= anomaly_tertiary and not is_re_save_pattern) or
        (len(all_anomalies) >= anomaly_primary) or
        (len(all_anomalies) >= anomaly_secondary and len(cluster_anomalies) >= cluster_thresh and not is_re_save_pattern and has_editing_boundaries)
    )
    
    secondary_indicators = (
        has_editing_boundaries and
        (anomaly_ratio > ratio_secondary) and
        (pattern_count >= max(2, min(4, int(total_regions * 0.15)))) and
        (len(all_anomalies) >= anomaly_secondary)
    )
    
    tertiary_indicators = (
        (len(all_anomalies) >= anomaly_tertiary) and
        (pattern_count >= max(2, min(4, int(total_regions * 0.15)))) and
        (anomaly_ratio > ratio_tertiary) and
        (pattern_agreement >= pattern_tertiary) and
        (has_editing_boundaries or (has_clustered_anomalies and len(cluster_anomalies) >= cluster_thresh + 1)) and
        not is_re_save_pattern
    )
    
    frequency_indicator = frequency_detected and frequency_confidence > freq_thresh and (len(all_anomalies) >= freq_anomaly or has_editing_boundaries)
    print_scan_indicator = print_scan_detected and print_scan_confidence > PRINT_SCAN
    
    camera_recapture = print_scan_detected and print_scan_confidence > 0.6
    
    if is_pdf:
        is_re_save_strong = False
    else:
        is_re_save_strong = (len(editing_boundaries) == 0 and 
                            doc_std_q < re_save_std and 
                            len(all_anomalies) >= ANOMALY_MIN and 
                            len(all_anomalies) <= ANOMALY_MAX and
                            pattern_agreement < RE_SAVE_PATTERN and
                            anomaly_ratio < RE_SAVE_RATIO)
    
    if is_re_save_strong or (is_re_save_pattern and len(all_anomalies) >= ANOMALY_MIN and len(all_anomalies) <= ANOMALY_MAX and not is_pdf):
        if (frequency_indicator and frequency_confidence > 0.5) or pattern_agreement >= PATTERN_MODERATE or len(all_anomalies) >= 6:
            overall_status = "FAIL"
        elif len(all_anomalies) >= ANOMALY_FAIL or has_editing_boundaries:
            overall_status = "FAIL"
        else:
            overall_status = "ESCALATE"
    else:
        if is_pdf:
            has_strong_pattern = pattern_agreement >= PATTERN_STRONG
            has_moderate_pattern = pattern_agreement >= PATTERN_MODERATE
            has_high_std = doc_std_q > STD_HIGH
            has_moderate_std = doc_std_q > STD_MODERATE
            
            is_tampered = (has_editing_boundaries and len(all_anomalies) >= PDF_ANOMALY and pattern_agreement >= PDF_PATTERN) or \
                         (len(all_anomalies) >= anomaly_primary + PDF_ANOMALY_MIN and pattern_agreement >= PDF_PATTERN) or \
                         (has_clustered_anomalies and len(cluster_anomalies) >= cluster_thresh + PDF_CLUSTER and len(all_anomalies) >= PDF_ANOMALY_TOTAL and pattern_agreement >= PDF_PATTERN) or \
                         (has_strong_pattern and len(all_anomalies) >= PDF_ANOMALY_MIN and has_editing_boundaries) or \
                         (frequency_indicator and len(all_anomalies) >= PDF_FREQ_ANOMALY and frequency_confidence > FREQ_CONF) or \
                         (len(all_anomalies) >= PDF_ANOMALY_MIN and has_strong_pattern and has_moderate_std and has_clustered_anomalies and len(cluster_anomalies) >= PDF_CLUSTER_MIN and has_editing_boundaries)
        else:
            is_tampered = primary_indicators or secondary_indicators or tertiary_indicators or frequency_indicator or print_scan_indicator or camera_recapture
        
        if is_tampered:
            overall_status = "FAIL"
        else:
            overall_status = "PASS"
    
    evidence["document_analysis"] = {
        "total_regions": len(all_region_q_values),
        "mean_quantization": float(doc_mean_q),
        "std_quantization": float(doc_std_q),
        "coefficient_of_variation": float(doc_cv),
        "anomalous_regions": len(all_anomalies),
        "neighbor_anomalies": len(neighbor_anomalies),
        "cluster_anomalies": len(cluster_anomalies),
        "distribution_anomalies": len(distribution_anomalies),
        "compression_anomalies": len(compression_anomalies),
        "editing_boundaries": editing_boundaries,
        "editing_boundaries_count": len(editing_boundaries),
        "pattern_agreement": float(pattern_agreement),
        "anomaly_density": float(anomaly_density),
        "region_results": region_results,
        "camera_recapture": camera_recapture,
        "print_scan_confidence": print_scan_confidence
    }
    
    # =====================================
    # Calculate Tampering Score
    # =====================================
    tampering_score = 0
    if overall_status == "FAIL":
        base_score = 60 if not frequency_indicator else 65
        
        anomaly_base = min(20, len(all_anomalies) * 2)
        anomaly_ratio_factor = min(10, int(anomaly_ratio * 20))
        
        std_factor = min(3, int((doc_std_q - 3.0) * 0.5)) if doc_std_q > 3.0 else 0
        mean_factor = min(3, int((doc_mean_q - 25.0) * 0.15)) if doc_mean_q > 25.0 else 0
        pattern_factor = min(2, int((pattern_agreement - 1.0) * 1)) if pattern_agreement > 1.0 else 0
        density_factor = min(2, int(anomaly_density * 15))
        
        tampering_score = base_score + anomaly_base + anomaly_ratio_factor + std_factor + mean_factor + pattern_factor + density_factor
        
        if frequency_indicator:
            frequency_penalty = min(10, int(frequency_confidence * 10))
            tampering_score += frequency_penalty
        
        tampering_score = min(100, max(60, tampering_score))
    elif overall_status == "ESCALATE":
        tampering_score = int(20 + (anomaly_ratio * 40))
        tampering_score = min(60, max(20, tampering_score))
    else:
        if len(all_anomalies) > 0:
            tampering_score = min(10, int(len(all_anomalies) * 2))
        else:
            tampering_score = 0
    
    if overall_status == "ESCALATE":
        return {
            "status": "ESCALATE",
            "evidence": evidence,
            "reason": "Re-save pattern detected (uniform quantization with low anomaly density - document may have been re-saved)",
            "tampering_score": tampering_score
        }
    
    if overall_status == "FAIL":
        reasons = []
        if len(all_anomalies) > 0:
            reasons.append(f"quantization anomalies in {len(all_anomalies)} region(s)")
        if frequency_indicator:
            reasons.append(f"frequency-domain manipulation detected ({frequency_analysis.get('anomaly_count', 0)} anomalies)")
        if print_scan_indicator:
            reasons.append(f"print-scan-photo cycle detected (confidence: {print_scan_confidence:.2f})")
        reason = "Pattern-based analysis detected " + " and ".join(reasons) + " - possible tampering"
        
        return {
            "status": "FAIL",
            "evidence": evidence,
            "reason": reason,
            "tampering_score": tampering_score
        }
    
    return {
        "status": "PASS",
        "evidence": evidence,
        "reason": "Quantization patterns consistent throughout entire document",
        "tampering_score": tampering_score
    }
