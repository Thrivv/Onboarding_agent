import cv2
import numpy as np
from typing import Dict
import os
import warnings
try:
    from scipy.ndimage import median_filter
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    median_filter = None

warnings.filterwarnings('ignore', category=RuntimeWarning)

# =====================================
# Constants
# =====================================
ELA_MIN_REGIONS = 4
ELA_MAX_DIM = 1024
ELA_QUALITY = 95
ELA_MIN_SIZE = 64
IQR_MULT = 1.5
Z_SCORE_BASE = 1.5
PDF_MEAN_BASE = 3.0
PDF_MEAN_MAX = 5.0
PDF_STD_BASE = 0.8
PDF_STD_MAX = 2.0
PDF_HIGH_MEAN_BASE = 4.0
PDF_HIGH_MEAN_MAX = 6.0
PDF_HIGH_STD_BASE = 1.2
PDF_HIGH_STD_MAX = 2.5
PDF_VHIGH_MEAN_BASE = 5.0
PDF_VHIGH_MEAN_MAX = 7.0
PDF_VHIGH_STD_BASE = 1.5
PDF_VHIGH_STD_MAX = 3.0
PDF_EXTREME_HIGH = 6.0
PDF_EXTREME_LOW = 1.5
PDF_MEAN_EXTREME = 4.5
PNG_MEAN_VHIGH = 1.0
PNG_STD_VHIGH = 0.25
PNG_MEAN_HIGH = 0.95
PNG_STD_HIGH = 0.20
PNG_MEAN_MOD = 0.85
PNG_MEAN_CLUSTER = 0.80
JPEG_MEAN_BASE = 0.25
JPEG_MEAN_MAX = 0.50
JPEG_STD_BASE = 0.05
JPEG_STD_MAX = 0.12
JPEG_HIGH_BASE = 0.35
JPEG_HIGH_MAX = 0.60
RE_SAVE_PROB = 0.45
RE_SAVE_PROB_HIGH = 0.50
RE_SAVE_PROB_ELA = 0.55
RE_SAVE_UNIFORM = 0.75
RE_SAVE_CONSIST = 0.90
RE_SAVE_CONSIST_LOW = 0.85
RE_SAVE_UNIFORM_LOW = 0.70
GEOMETRIC = 0.70
STATISTICAL = 0.65
COLOR = 0.50
TEMPLATE = 0.45


def detect_noise_inconsistency(image: np.ndarray) -> Dict:
    if not SCIPY_AVAILABLE:
        return {"detected": False}
    
    try:
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
        else:
            gray = image.astype(np.float32)
        
        denoised = median_filter(gray, size=3)
        noise_map = cv2.absdiff(gray, denoised)
        
        block_size = 25
        local_mean = cv2.blur(noise_map, (block_size, block_size))
        local_sqr_mean = cv2.blur(noise_map**2, (block_size, block_size))
        local_variance = local_sqr_mean - (local_mean ** 2)
        
        variance_mean = np.mean(local_variance)
        variance_std = np.std(local_variance)
        threshold = variance_mean - (2 * variance_std)
        
        inconsistent_mask = local_variance < threshold
        inconsistent_pixels = np.sum(inconsistent_mask)
        total_pixels = local_variance.size
        inconsistency_ratio = inconsistent_pixels / total_pixels if total_pixels > 0 else 0
        
        detected = inconsistency_ratio > 0.05
        
        return {
            "detected": detected
        }
    except Exception:
        return {"detected": False}


def detect_lighting_direction_inconsistency(image: np.ndarray) -> Dict:
    try:
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
        else:
            gray = image.astype(np.float32)
        
        grad_x = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
        grad_y = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
        
        magnitude = np.sqrt(grad_x**2 + grad_y**2)
        direction = np.arctan2(grad_y, grad_x) * 180 / np.pi
        
        h, w = gray.shape
        regions = []
        block_size = 50
        
        for y in range(0, h - block_size, block_size):
            for x in range(0, w - block_size, block_size):
                region_mag = magnitude[y:y+block_size, x:x+block_size]
                region_dir = direction[y:y+block_size, x:x+block_size]
                
                if np.sum(region_mag > 10) > 0:
                    valid_dirs = region_dir[region_mag > 10]
                    valid_dirs = (valid_dirs + 360) % 360
                    hist, bins = np.histogram(valid_dirs, bins=36)
                    dominant_dir = bins[np.argmax(hist)]
                    regions.append({
                        "x": x, "y": y,
                        "direction": float(dominant_dir),
                        "magnitude_mean": float(np.mean(region_mag))
                    })
        
        if len(regions) < 4:
            return {"detected": False}
        
        directions = [r["direction"] for r in regions]
        dir_mean = np.mean(directions)
        dir_std = np.std(directions)
        
        inconsistent_count = 0
        for r in regions:
            dir_diff = abs(r["direction"] - dir_mean)
            if dir_diff > 180:
                dir_diff = 360 - dir_diff
            if dir_diff > 90 and r["magnitude_mean"] > 50:
                inconsistent_count += 1
        
        inconsistency_ratio = inconsistent_count / len(regions) if regions else 0
        detected = inconsistency_ratio > 0.5 and dir_std > 80
        
        return {
            "detected": detected
        }
    except Exception:
        return {"detected": False}


def detect_geometric_transformations(image: np.ndarray) -> Dict:
    try:
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
        else:
            gray = image.astype(np.float32)
        
        h, w = gray.shape
        if h < 100 or w < 100:
            return {"detected": False, "confidence": 0.0}
        
        max_dim = 512
        if h > max_dim or w > max_dim:
            scale_factor = max_dim / max(h, w)
            gray = cv2.resize(gray, (int(w * scale_factor), int(h * scale_factor)), interpolation=cv2.INTER_AREA)
            h, w = gray.shape
        
        scales = [0.5]
        scale_anomalies = []
        
        for scale in scales:
            if scale < 1.0:
                scaled = cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
            else:
                scaled = gray.copy()
            
            edges = cv2.Canny((scaled * 255).astype(np.uint8), 50, 150)
            
            sobel_x = cv2.Sobel(scaled, cv2.CV_64F, 1, 0, ksize=3)
            sobel_y = cv2.Sobel(scaled, cv2.CV_64F, 0, 1, ksize=3)
            angles = np.arctan2(sobel_y, sobel_x) * 180 / np.pi
            
            angle_hist, _ = np.histogram(angles[edges > 0], bins=36, range=(-180, 180))
            angle_std = np.std(angle_hist)
            angle_mean = np.mean(angle_hist)
            
            edge_density = np.sum(edges > 0) / edges.size
            
            left_half = edges[:, :edges.shape[1]//2]
            right_half = edges[:, edges.shape[1]//2:]
            left_density = np.sum(left_half > 0) / left_half.size if left_half.size > 0 else 0
            right_density = np.sum(right_half > 0) / right_half.size if right_half.size > 0 else 0
            asymmetry = abs(left_density - right_density)
            
            if angle_std > angle_mean * 1.5:
                scale_anomalies.append({"severity": min(angle_std / angle_mean, 2.0)})
            if asymmetry > 0.1:
                scale_anomalies.append({"severity": asymmetry * 10})
            if edge_density < 0.05 or edge_density > 0.3:
                scale_anomalies.append({"severity": abs(edge_density - 0.15) * 5})
        
        detected = len(scale_anomalies) >= 2
        confidence = min(sum(a.get("severity", 0) for a in scale_anomalies) / len(scale_anomalies) if scale_anomalies else 0, 1.0)
        
        return {
            "detected": detected,
            "confidence": float(confidence)
        }
    except Exception:
        return {"detected": False, "confidence": 0.0}


def detect_color_matched_edits(image: np.ndarray) -> Dict:
    try:
        if len(image.shape) != 3:
            return {"detected": False, "confidence": 0.0}
        
        h, w = image.shape[:2]
        if h < 100 or w < 100:
            return {"detected": False, "confidence": 0.0}
        
        max_dim = 512
        if h > max_dim or w > max_dim:
            scale = max_dim / max(h, w)
            new_h, new_w = int(h * scale), int(w * scale)
            image = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
            h, w = new_h, new_w
        
        bgr = image.astype(np.float32) / 255.0
        lab = cv2.cvtColor((bgr * 255).astype(np.uint8), cv2.COLOR_BGR2LAB).astype(np.float32)
        hsv = cv2.cvtColor((bgr * 255).astype(np.uint8), cv2.COLOR_BGR2HSV).astype(np.float32)
        
        grid_rows, grid_cols = 6, 6
        region_h, region_w = h // grid_rows, w // grid_cols
        
        color_anomalies = []
        region_features = []
        
        for row in range(grid_rows):
            for col in range(grid_cols):
                y = row * region_h
                x = col * region_w
                region_bgr = bgr[y:y+region_h, x:x+region_w]
                region_lab = lab[y:y+region_h, x:x+region_w]
                region_hsv = hsv[y:y+region_h, x:x+region_w]
                
                if region_bgr.size < 100:
                    continue
                
                bgr_mean = np.mean(region_bgr, axis=(0, 1))
                lab_mean = np.mean(region_lab, axis=(0, 1))
                hsv_mean = np.mean(region_hsv, axis=(0, 1))
                
                bgr_std = np.std(region_bgr, axis=(0, 1))
                lab_std = np.std(region_lab, axis=(0, 1))
                hsv_std = np.std(region_hsv, axis=(0, 1))
                
                bgr_cv = np.mean(bgr_std / (bgr_mean + 1e-6))
                lab_cv = np.mean(lab_std / (lab_mean + 1e-6))
                hsv_cv = np.mean(hsv_std / (hsv_mean + 1e-6))
                
                hist_b = cv2.calcHist([(region_bgr * 255).astype(np.uint8)], [0], None, [64], [0, 256])
                hist_g = cv2.calcHist([(region_bgr * 255).astype(np.uint8)], [1], None, [64], [0, 256])
                hist_r = cv2.calcHist([(region_bgr * 255).astype(np.uint8)], [2], None, [64], [0, 256])
                
                hist_b_norm = hist_b / (region_bgr.shape[0] * region_bgr.shape[1] + 1e-6)
                hist_g_norm = hist_g / (region_bgr.shape[0] * region_bgr.shape[1] + 1e-6)
                hist_r_norm = hist_r / (region_bgr.shape[0] * region_bgr.shape[1] + 1e-6)
                
                entropy_b = -np.sum(hist_b_norm * np.log(hist_b_norm + 1e-10))
                entropy_g = -np.sum(hist_g_norm * np.log(hist_g_norm + 1e-10))
                entropy_r = -np.sum(hist_r_norm * np.log(hist_r_norm + 1e-10))
                
                grad_x = cv2.Sobel(region_bgr, cv2.COLOR_BGR2GRAY if len(region_bgr.shape) == 3 else -1, 1, 0, ksize=3)
                grad_y = cv2.Sobel(region_bgr, cv2.COLOR_BGR2GRAY if len(region_bgr.shape) == 3 else -1, 0, 1, ksize=3)
                if len(grad_x.shape) == 3:
                    grad_mag = np.sqrt(np.sum(grad_x**2, axis=2) + np.sum(grad_y**2, axis=2))
                else:
                    grad_mag = np.sqrt(grad_x**2 + grad_y**2)
                grad_mean = np.mean(grad_mag)
                
                color_transition = np.std([np.mean(region_bgr[:, :, 0]), np.mean(region_bgr[:, :, 1]), np.mean(region_bgr[:, :, 2])])
                
                lab_de = np.sqrt(np.sum((lab_mean - np.mean(lab, axis=(0, 1)))**2))
                
                channel_corr = np.corrcoef([region_bgr[:, :, 0].flatten(), region_bgr[:, :, 1].flatten(), region_bgr[:, :, 2].flatten()])
                min_corr = np.min(channel_corr[np.triu_indices_from(channel_corr, k=1)])
                
                is_anomalous = False
                reasons = []
                anomaly_score = 0.0
                
                if bgr_cv < 0.03 and lab_cv < 0.05:
                    is_anomalous = True
                    reasons.append("unnatural_color_uniformity")
                    anomaly_score += 0.25
                
                if abs(entropy_b - entropy_g) > 0.3 or abs(entropy_g - entropy_r) > 0.3:
                    is_anomalous = True
                    reasons.append("color_channel_entropy_mismatch")
                    anomaly_score += 0.20
                
                if hsv_mean[1] < 15 and hsv_std[1] < 3:
                    is_anomalous = True
                    reasons.append("unnatural_saturation_pattern")
                    anomaly_score += 0.15
                
                if grad_mean < 0.01 and color_transition < 0.02:
                    is_anomalous = True
                    reasons.append("unnatural_gradient_smoothness")
                    anomaly_score += 0.20
                
                if lab_de > 10.0:
                    is_anomalous = True
                    reasons.append("perceptual_color_difference")
                    anomaly_score += 0.15
                
                if min_corr < 0.7:
                    is_anomalous = True
                    reasons.append("color_channel_correlation_anomaly")
                    anomaly_score += 0.15
                
                if is_anomalous:
                    color_anomalies.append({
                        "region": (int(x), int(y), int(region_w), int(region_h)),
                        "bgr_cv": float(bgr_cv),
                        "lab_cv": float(lab_cv),
                        "entropy_diff": float(max(abs(entropy_b - entropy_g), abs(entropy_g - entropy_r))),
                        "anomaly_score": float(anomaly_score),
                        "reasons": reasons
                    })
                
                region_features.append({
                    "bgr_mean": bgr_mean,
                    "lab_mean": lab_mean,
                    "hsv_mean": hsv_mean,
                    "grad_mean": float(grad_mean),
                    "color_transition": float(color_transition)
                })
        
        if len(region_features) < 4:
            return {"detected": False, "confidence": 0.0}
        
        feature_consistency = []
        for i in range(len(region_features) - 1):
            for j in range(i + 1, len(region_features)):
                bgr_diff = np.linalg.norm(region_features[i]["bgr_mean"] - region_features[j]["bgr_mean"])
                lab_diff = np.linalg.norm(region_features[i]["lab_mean"] - region_features[j]["lab_mean"])
                grad_diff = abs(region_features[i]["grad_mean"] - region_features[j]["grad_mean"])
                feature_consistency.append({
                    "bgr_diff": float(bgr_diff),
                    "lab_diff": float(lab_diff),
                    "grad_diff": float(grad_diff)
                })
        
        consistency_mean = np.mean([f["bgr_diff"] for f in feature_consistency])
        consistency_std = np.std([f["bgr_diff"] for f in feature_consistency])
        
        inconsistent_pairs = sum(1 for f in feature_consistency 
                                if f["bgr_diff"] > consistency_mean + 2 * consistency_std or 
                                   f["lab_diff"] > 15.0 or 
                                   f["grad_diff"] > 0.05)
        
        if inconsistent_pairs > len(feature_consistency) * 0.15:
            color_anomalies.append({
                "region": (0, 0, w, h),
                "bgr_cv": 0.0,
                "lab_cv": 0.0,
                "entropy_diff": 0.0,
                "anomaly_score": 0.3,
                "reasons": ["inter_region_color_inconsistency"]
            })
        
        detected = len(color_anomalies) >= 2
        total_anomaly_score = sum(a.get("anomaly_score", 0.1) for a in color_anomalies)
        confidence = min(total_anomaly_score / max(len(color_anomalies), 1), 1.0) if detected else 0.0
        
        return {
            "detected": detected,
            "confidence": float(confidence),
            "anomaly_count": len(color_anomalies)
        }
    except Exception:
        return {"detected": False, "confidence": 0.0}


def detect_template_replacement(image: np.ndarray) -> Dict:
    try:
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
        else:
            gray = image.astype(np.float32)
        
        h, w = gray.shape
        if h < 100 or w < 100:
            return {"detected": False, "confidence": 0.0}
        
        max_dim = 512
        if h > max_dim or w > max_dim:
            scale = max_dim / max(h, w)
            gray = cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
            h, w = gray.shape
        
        gray_uint8 = (gray * 255).astype(np.uint8) if gray.max() <= 1.0 else gray.astype(np.uint8)
        
        edges_fine = cv2.Canny(gray_uint8, 30, 100)
        edges_coarse = cv2.Canny(gray_uint8, 50, 150)
        
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        laplacian_var = cv2.blur((laplacian ** 2), (15, 15))
        
        grad_x = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
        grad_y = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
        grad_mag = np.sqrt(grad_x**2 + grad_y**2)
        grad_var = cv2.blur(grad_mag, (15, 15))
        
        texture = cv2.Laplacian(gray, cv2.CV_64F, ksize=5)
        texture_var = cv2.blur((texture ** 2), (15, 15))
        
        grid_rows, grid_cols = 6, 6
        region_h, region_w = h // grid_rows, w // grid_cols
        
        blending_anomalies = []
        region_features = []
        
        for row in range(grid_rows):
            for col in range(grid_cols):
                y = row * region_h
                x = col * region_w
                region_gray = gray[y:y+region_h, x:x+region_w]
                region_edges_fine = edges_fine[y:y+region_h, x:x+region_w]
                region_edges_coarse = edges_coarse[y:y+region_h, x:x+region_w]
                region_lap = laplacian_var[y:y+region_h, x:x+region_w]
                region_grad = grad_var[y:y+region_h, x:x+region_w]
                region_texture = texture_var[y:y+region_h, x:x+region_w]
                
                if region_gray.size < 100:
                    continue
                
                edge_density_fine = np.sum(region_edges_fine > 0) / region_edges_fine.size
                edge_density_coarse = np.sum(region_edges_coarse > 0) / region_edges_coarse.size
                lap_mean = np.mean(region_lap)
                lap_std = np.std(region_lap)
                gray_mean = np.mean(region_gray)
                gray_std = np.std(region_gray)
                grad_mean = np.mean(region_grad)
                grad_std = np.std(region_grad)
                texture_mean = np.mean(region_texture)
                texture_std = np.std(region_texture)
                
                edge_ratio = edge_density_fine / (edge_density_coarse + 1e-6)
                
                is_anomalous = False
                reasons = []
                anomaly_score = 0.0
                
                if edge_density_fine < 0.015 and lap_mean < 0.0008:
                    is_anomalous = True
                    reasons.append("unnatural_smoothness")
                    anomaly_score += 0.25
                
                if gray_std < 4.0 and lap_std < 0.0004:
                    is_anomalous = True
                    reasons.append("perfect_blending_artifact")
                    anomaly_score += 0.30
                
                if edge_density_coarse > 0.12 and lap_mean > 0.008:
                    is_anomalous = True
                    reasons.append("template_boundary_artifact")
                    anomaly_score += 0.20
                
                if edge_ratio > 2.5 or edge_ratio < 0.4:
                    is_anomalous = True
                    reasons.append("multi_scale_edge_inconsistency")
                    anomaly_score += 0.15
                
                if grad_mean < 0.005 and grad_std < 0.002:
                    is_anomalous = True
                    reasons.append("gradient_magnitude_anomaly")
                    anomaly_score += 0.20
                
                if texture_mean < 0.0005 and texture_std < 0.0002:
                    is_anomalous = True
                    reasons.append("texture_consistency_anomaly")
                    anomaly_score += 0.15
                
                if abs(gray_std - np.mean([np.std(gray[r:r+region_h, c:c+region_w]) 
                                          for r in range(0, h-region_h, region_h) 
                                          for c in range(0, w-region_w, region_w) 
                                          if r != y or c != x])) > 8.0:
                    is_anomalous = True
                    reasons.append("inter_region_texture_inconsistency")
                    anomaly_score += 0.15
                
                if is_anomalous:
                    blending_anomalies.append({
                        "region": (int(x), int(y), int(region_w), int(region_h)),
                        "edge_density": float(edge_density_fine),
                        "lap_mean": float(lap_mean),
                        "gray_std": float(gray_std),
                        "anomaly_score": float(anomaly_score),
                        "reasons": reasons
                    })
                
                region_features.append({
                    "gray_std": float(gray_std),
                    "lap_mean": float(lap_mean),
                    "grad_mean": float(grad_mean),
                    "texture_mean": float(texture_mean)
                })
        
        if len(region_features) >= 4:
            feature_consistency = []
            for i in range(len(region_features) - 1):
                for j in range(i + 1, len(region_features)):
                    std_diff = abs(region_features[i]["gray_std"] - region_features[j]["gray_std"])
                    lap_diff = abs(region_features[i]["lap_mean"] - region_features[j]["lap_mean"])
                    grad_diff = abs(region_features[i]["grad_mean"] - region_features[j]["grad_mean"])
                    feature_consistency.append({
                        "std_diff": float(std_diff),
                        "lap_diff": float(lap_diff),
                        "grad_diff": float(grad_diff)
                    })
            
            if feature_consistency:
                consistency_mean = np.mean([f["std_diff"] for f in feature_consistency])
                consistency_std = np.std([f["std_diff"] for f in feature_consistency])
                
                inconsistent_pairs = sum(1 for f in feature_consistency 
                                        if f["std_diff"] > consistency_mean + 2.5 * consistency_std or 
                                           f["lap_diff"] > 0.01 or 
                                           f["grad_diff"] > 0.01)
                
                if inconsistent_pairs > len(feature_consistency) * 0.20:
                    blending_anomalies.append({
                        "region": (0, 0, w, h),
                        "edge_density": 0.0,
                        "lap_mean": 0.0,
                        "gray_std": 0.0,
                        "anomaly_score": 0.35,
                        "reasons": ["inter_region_blending_inconsistency"]
                    })
        
        detected = len(blending_anomalies) >= 1
        total_anomaly_score = sum(a.get("anomaly_score", 0.1) for a in blending_anomalies)
        confidence = min(total_anomaly_score / max(len(blending_anomalies), 1), 1.0) if detected else 0.0
        
        return {
            "detected": detected,
            "confidence": float(confidence),
            "anomaly_count": len(blending_anomalies)
        }
    except Exception:
        return {"detected": False, "confidence": 0.0}


def perform_statistical_forensics(image: np.ndarray) -> Dict:
    try:
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
        else:
            gray = image.astype(np.float32)
        
        h, w = gray.shape
        if h < 50 or w < 50:
            return {"detected": False, "confidence": 0.0}
        
        max_dim = 512
        if h > max_dim or w > max_dim:
            scale_factor = max_dim / max(h, w)
            gray = cv2.resize(gray, (int(w * scale_factor), int(h * scale_factor)), interpolation=cv2.INTER_AREA)
            h, w = gray.shape
        
        grid_rows, grid_cols = 3, 3
        region_h, region_w = h // grid_rows, w // grid_cols
        
        statistical_anomalies = []
        
        for row in range(grid_rows):
            for col in range(grid_cols):
                y = row * region_h
                x = col * region_w
                region = gray[y:y+region_h, x:x+region_w]
                
                if region.size < 100:
                    continue
                
                mean_val = np.mean(region)
                std_val = np.std(region)
                skewness = 0.0
                kurtosis = 0.0
                
                try:
                    from scipy import stats
                    skewness = float(stats.skew(region.flatten()))
                    kurtosis = float(stats.kurtosis(region.flatten()))
                except:
                    centered = region.flatten() - mean_val
                    if std_val > 0:
                        normalized = centered / std_val
                        skewness = float(np.mean(normalized ** 3))
                        kurtosis = float(np.mean(normalized ** 4) - 3)
                
                hist, _ = np.histogram(region.flatten(), bins=32, range=(0, 256))
                hist_norm = hist / (region.size + 1e-6)
                
                hist_entropy = -np.sum(hist_norm * np.log(hist_norm + 1e-10))
                hist_peaks = len([i for i in range(1, len(hist)-1) if hist[i] > hist[i-1] and hist[i] > hist[i+1] and hist[i] > np.max(hist) * 0.3])
                
                is_anomalous = False
                anomaly_reasons = []
                
                if abs(skewness) > 1.5:
                    is_anomalous = True
                    anomaly_reasons.append("high_skewness")
                if abs(kurtosis) > 3.0:
                    is_anomalous = True
                    anomaly_reasons.append("high_kurtosis")
                if hist_entropy < 3.0 or hist_entropy > 5.5:
                    is_anomalous = True
                    anomaly_reasons.append("unusual_entropy")
                if hist_peaks > 3:
                    is_anomalous = True
                    anomaly_reasons.append("bimodal_distribution")
                
                if is_anomalous:
                    statistical_anomalies.append({
                        "region": (int(x), int(y), int(region_w), int(region_h)),
                        "mean": float(mean_val),
                        "std": float(std_val),
                        "skewness": float(skewness),
                        "kurtosis": float(kurtosis),
                        "entropy": float(hist_entropy),
                        "reasons": anomaly_reasons
                    })
        
        detected = len(statistical_anomalies) >= 4
        confidence = min(len(statistical_anomalies) / 12.0, 1.0) if detected else 0.0
        
        return {
            "detected": detected,
            "confidence": float(confidence)
        }
    except Exception:
        return {"detected": False, "confidence": 0.0}


def test_error_level_analysis(file_path: str, image: np.ndarray) -> Dict:
    # =====================================
    # Initialize Evidence Dictionary
    # =====================================
    evidence = {
        "file_path": file_path,
        "ela_stats": {}
    }

    try:
        # =====================================
        # Re-compress Image at 95% JPEG Quality
        # =====================================
        max_dim = 1024
        h, w = image.shape[:2]
        if h > max_dim or w > max_dim:
            scale = max_dim / max(h, w)
            resized = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        else:
            resized = image
        
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 95]
        result, encimg = cv2.imencode('.jpg', resized, encode_param)
        if not result:
            return {"status": "PASS", "evidence": evidence, "reason": "Could not perform ELA", "tampering_score": 0}
        
        re_saved = cv2.imdecode(encimg, cv2.IMREAD_COLOR)
        if re_saved is None:
            return {"status": "PASS", "evidence": evidence, "reason": "Could not perform ELA", "tampering_score": 0}

        if resized.shape != image.shape:
            re_saved = cv2.resize(re_saved, (w, h), interpolation=cv2.INTER_LINEAR)

        # =====================================
        # Generate ELA Difference Map
        # =====================================
        gray_original = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
        gray_resaved = cv2.cvtColor(re_saved, cv2.COLOR_BGR2GRAY).astype(np.float32)

        ela_map = np.abs(gray_original - gray_resaved)

        h, w = ela_map.shape
        grid_rows, grid_cols = 4, 4
        region_h = h // grid_rows
        region_w = w // grid_cols

        region_results = []
        ela_values = []

        # =====================================
        # Divide into Grid Regions and Extract Stats
        # =====================================
        for r in range(grid_rows):
            for c in range(grid_cols):
                y1 = r * region_h
                x1 = c * region_w
                y2 = (r + 1) * region_h if r < grid_rows - 1 else h
                x2 = (c + 1) * region_w if c < grid_cols - 1 else w

                region = ela_map[y1:y2, x1:x2]

                if region.size < ELA_MIN_SIZE:
                    continue

                r_mean = float(np.mean(region))

                ela_values.append(r_mean)
                region_results.append({
                    "pos": (x1, y1, x2 - x1, y2 - y1),
                    "mean": r_mean
                })

        if len(ela_values) < ELA_MIN_REGIONS:
            return {"status": "PASS", "evidence": evidence, "reason": "Document too small for ELA", "tampering_score": 0}

        ela_values = np.array(ela_values)

        # =====================================
        # Calculate Document-Wide Statistics
        # =====================================
        doc_mean = float(np.mean(ela_values))
        doc_std = float(np.std(ela_values))
        cv = doc_std / (doc_mean + 1e-6)
        ela_range = float(np.max(ela_values) - np.min(ela_values))

        q1 = np.percentile(ela_values, 25)
        q3 = np.percentile(ela_values, 75)
        iqr = q3 - q1
        lower_bound = q1 - IQR_MULT * iqr
        upper_bound = q3 + IQR_MULT * iqr

        outliers = []
        inconsistent_regions = []

        for idx, mean_val in enumerate(ela_values):
            is_outlier = mean_val < lower_bound or mean_val > upper_bound
            z_score = abs(mean_val - doc_mean) / (doc_std + 1e-6)
            z_thresh = Z_SCORE_BASE + cv
            is_inconsistent = is_outlier or (z_score > z_thresh)

            if is_inconsistent:
                inconsistent_regions.append(idx)
                if is_outlier:
                    outliers.append(idx)

            region_results[idx]["status"] = "FAIL" if is_inconsistent else "PASS"

        evidence["document_analysis"] = {
            "total_regions": len(region_results),
            "mean_ela": doc_mean,
            "std_ela": doc_std,
            "cv": cv,
            "inconsistent_regions": inconsistent_regions,
            "outliers": outliers,
            "regions": region_results
        }

        total_regions = len(region_results)

        # =====================================
        # Pattern-Based Tampering Detection
        # =====================================
        ext = os.path.splitext(file_path)[1].lower()
        is_pdf = ext == '.pdf'
        is_png = ext == '.png'
        is_jpeg = ext in ['.jpg', '.jpeg']
        
        uniform_mean_threshold = max(0.20, min(0.35, doc_mean * 0.8))
        uniform_std_threshold = max(0.20, min(0.35, doc_std * 0.8))
        adaptive_inconsistent_min = max(1, int(total_regions * 0.10))
        
        suspicious_uniform = (doc_mean < uniform_mean_threshold and doc_std < uniform_std_threshold and len(inconsistent_regions) >= adaptive_inconsistent_min)
        too_many_inconsistent = len(inconsistent_regions) >= max(2, int(total_regions * 0.15))
        
        clustered_edit = False
        idx_set = set(inconsistent_regions)
        for idx in inconsistent_regions:
            r = idx // 4
            c = idx % 4
            neighbors = []
            for dr, dc in [(1,0), (-1,0), (0,1), (0,-1)]:
                nr, nc = r + dr, c + dc
                n_idx = nr * 4 + nc
                if 0 <= nr < 4 and 0 <= nc < 4 and n_idx in idx_set:
                    neighbors.append(n_idx)
            if len(neighbors) >= 2:
                clustered_edit = True
                break
        
        adaptive_high_severity_threshold = max(0.40, min(0.55, 0.45 + (cv * 0.15)))
        adaptive_moderate_severity_threshold = max(0.30, min(0.45, 0.35 + (cv * 0.12)))
        
        high_severity_count = 0
        moderate_severity_count = 0
        outlier_inconsistent = 0
        outliers_set = set(outliers)
        for idx in inconsistent_regions:
            rel_diff = abs(ela_values[idx] - doc_mean) / (doc_mean + 1e-6)
            if rel_diff > adaptive_high_severity_threshold:
                high_severity_count += 1
            elif rel_diff > adaptive_moderate_severity_threshold:
                moderate_severity_count += 1
            if idx in outliers_set:
                outlier_inconsistent += 1
        multiple_high_severity = high_severity_count >= 2
        mixed_severity = (len(inconsistent_regions) >= 2 and 
                         ((high_severity_count >= 1 and moderate_severity_count >= 1) or 
                          (moderate_severity_count >= 2)))
        multiple_outlier_inconsistent = outlier_inconsistent >= 2
        
        # Calculate inconsistent_ratio for all file types
        inconsistent_ratio = len(inconsistent_regions) / len(ela_values) if len(ela_values) > 0 else 0
        
        if is_pdf:
            pdf_mean_thresh = max(PDF_MEAN_BASE, min(PDF_MEAN_MAX, doc_mean * 0.7))
            pdf_std_thresh = max(PDF_STD_BASE, min(PDF_STD_MAX, doc_std * 0.7))
            pdf_high_mean = max(PDF_HIGH_MEAN_BASE, min(PDF_HIGH_MEAN_MAX, doc_mean * 0.9))
            pdf_high_std = max(PDF_HIGH_STD_BASE, min(PDF_HIGH_STD_MAX, doc_std * 1.0))
            pdf_vhigh_mean = max(PDF_VHIGH_MEAN_BASE, min(PDF_VHIGH_MEAN_MAX, doc_mean * 1.1))
            pdf_vhigh_std = max(PDF_VHIGH_STD_BASE, min(PDF_VHIGH_STD_MAX, doc_std * 1.2))
            
            high_ela_mean = doc_mean > pdf_mean_thresh
            high_ela_variance = doc_std > pdf_std_thresh
            high_ela_regions = sum(1 for val in ela_values if val > pdf_high_mean)
            has_high_ela_pattern = high_ela_regions >= max(3, int(total_regions * 0.25))
            very_high_ela = doc_mean > pdf_vhigh_mean and doc_std > pdf_vhigh_std
            moderate_ela = doc_mean > pdf_mean_thresh and doc_std > pdf_std_thresh
            
            has_outlier_inconsistent = outlier_inconsistent >= 2
            has_single_severe_anomaly = len(inconsistent_regions) >= 3 and high_severity_count >= 2
            
            has_extreme_outlier = False
            if len(inconsistent_regions) >= 1:
                for idx in inconsistent_regions:
                    if idx < len(ela_values):
                        region_ela = ela_values[idx]
                        if region_ela > PDF_EXTREME_HIGH or (region_ela < PDF_EXTREME_LOW and doc_mean > PDF_MEAN_EXTREME):
                            has_extreme_outlier = True
                            break
            
            min_regions = 8
            min_mean = 10.0
            min_std = 4.0
            min_outlier = 7
            is_tampered = (very_high_ela and len(inconsistent_regions) >= min_regions) or \
                         (high_ela_mean and doc_mean > min_mean and len(inconsistent_regions) >= min_regions) or \
                         ((high_ela_mean and high_ela_variance) and len(inconsistent_regions) >= min_regions) or \
                         ((high_ela_mean and has_high_ela_pattern) and len(inconsistent_regions) >= min_regions) or \
                         (clustered_edit and len(inconsistent_regions) >= min_regions) or \
                         (multiple_high_severity and len(inconsistent_regions) >= min_regions) or \
                         (too_many_inconsistent and len(inconsistent_regions) >= min_regions + 1) or \
                         (has_high_ela_pattern and len(inconsistent_regions) >= min_regions) or \
                         (has_outlier_inconsistent and len(inconsistent_regions) >= min_regions and outlier_inconsistent >= min_outlier) or \
                         (has_single_severe_anomaly and len(inconsistent_regions) >= min_regions + 1) or \
                         (moderate_ela and len(inconsistent_regions) >= min_regions and outlier_inconsistent >= min_outlier and high_severity_count >= min_outlier) or \
                         (doc_mean > min_mean + 0.5 and doc_std > min_std and len(inconsistent_regions) >= min_regions) or \
                         (doc_mean > min_mean and inconsistent_ratio > 0.50 and len(inconsistent_regions) >= min_regions) or \
                         (doc_mean > min_mean + 1.5 and doc_std > min_std) or \
                         (has_extreme_outlier and len(inconsistent_regions) >= min_regions - 1 and outlier_inconsistent >= min_outlier and doc_mean > min_mean)
        else:
            moderate_ela = doc_mean > 0.4 and doc_std > 0.08
            high_ela_for_image = doc_mean > 0.5
            
            if is_png:
                very_high_ela_png = doc_mean > PNG_MEAN_VHIGH and doc_std > PNG_STD_VHIGH and len(inconsistent_regions) >= 6
                high_ela_png = doc_mean > PNG_MEAN_HIGH and doc_std > PNG_STD_HIGH and len(inconsistent_regions) >= 7
                is_tampered = very_high_ela_png or high_ela_png or \
                             (len(inconsistent_regions) >= 8 and doc_mean > PNG_MEAN_MOD) or \
                             (clustered_edit and len(inconsistent_regions) >= 7 and doc_mean > PNG_MEAN_CLUSTER) or \
                             (multiple_high_severity and len(inconsistent_regions) >= 8)
            else:
                jpeg_mean_thresh = max(JPEG_MEAN_BASE, min(JPEG_MEAN_MAX, doc_mean * 0.75 + (cv * 0.08)))
                jpeg_std_thresh = max(JPEG_STD_BASE, min(JPEG_STD_MAX, doc_std * 0.75 + (cv * 0.06)))
                jpeg_high_thresh = max(JPEG_HIGH_BASE, min(JPEG_HIGH_MAX, doc_mean * 1.05 + (ela_range * 0.30)))
                
                borderline_moderate = (doc_mean > jpeg_mean_thresh and doc_mean <= jpeg_high_thresh and 
                                       doc_std >= jpeg_std_thresh and len(inconsistent_regions) >= adaptive_inconsistent_min)
                
                single_region_high_severity = False
                if len(inconsistent_regions) == 1:
                    idx = inconsistent_regions[0]
                    rel_diff = abs(ela_values[idx] - doc_mean) / (doc_mean + 1e-6)
                    severity_thresh = max(0.45, min(0.60, 0.5 + (cv * 0.1)))
                    single_region_high_severity = rel_diff > severity_thresh and ela_values[idx] > doc_mean
                
                moderate_ela = doc_mean > jpeg_mean_thresh and doc_std > jpeg_std_thresh
                high_ela_for_image = doc_mean > jpeg_high_thresh
                low_moderate_ela = doc_mean > jpeg_mean_thresh * 0.8 and doc_std > jpeg_std_thresh * 0.8
                
                is_tampered = suspicious_uniform or \
                         too_many_inconsistent or \
                         (clustered_edit and len(inconsistent_regions) >= max(2, adaptive_inconsistent_min)) or \
                         (multiple_high_severity and len(inconsistent_regions) >= max(2, adaptive_inconsistent_min)) or \
                         (len(inconsistent_regions) >= max(2, adaptive_inconsistent_min) and mixed_severity) or \
                         (multiple_outlier_inconsistent and len(inconsistent_regions) >= max(2, adaptive_inconsistent_min)) or \
                         (len(inconsistent_regions) >= max(2, adaptive_inconsistent_min) and moderate_ela) or \
                         (len(inconsistent_regions) >= 2 and high_ela_for_image) or \
                         (borderline_moderate and len(inconsistent_regions) >= max(2, adaptive_inconsistent_min)) or \
                         (single_region_high_severity and moderate_ela) or \
                         (moderate_ela and len(inconsistent_regions) >= 3) or \
                         (low_moderate_ela and len(inconsistent_regions) >= 4) or \
                         (len(inconsistent_regions) >= 3 and doc_std > jpeg_std_thresh * 0.8) or \
                         (len(inconsistent_regions) >= 1 and doc_mean > 0.4 and doc_mean < 0.7)
            

        noise_analysis = detect_noise_inconsistency(image)
        evidence["noise_analysis"] = noise_analysis
        
        # =====================================
        # Lighting Direction Analysis (Detect Physically Impossible Lighting)
        # =====================================
        lighting_analysis = detect_lighting_direction_inconsistency(image)
        evidence["lighting_analysis"] = lighting_analysis
        
        # =====================================
        # Multi-Scale Analysis (Detect Geometric Transformations)
        # =====================================
        multi_scale_analysis = detect_geometric_transformations(image)
        evidence["multi_scale_analysis"] = multi_scale_analysis
        
        # =====================================
        # Statistical Forensics (Enhanced Pixel Distribution Analysis)
        # =====================================
        statistical_analysis = perform_statistical_forensics(image)
        evidence["statistical_forensics"] = statistical_analysis
        
        # =====================================
        # Adaptive Threshold Calculation for Re-save Detection
        # =====================================
        adaptive_ela_mean_threshold = max(0.55, min(0.80, doc_mean * 1.15 + (ela_range * 0.4)))
        adaptive_ela_std_threshold = max(0.20, min(0.35, doc_std * 1.3 + (cv * 0.25)))
        adaptive_inconsistency_threshold = max(6, min(10, int(total_regions * 0.35)))
        
        # =====================================
        # Adaptive Re-save Detection
        # =====================================
        is_re_save = False
        ela_uniformity_score = 0.0
        consistency_score = 0.0
        re_save_probability = 0.0
        
        if not is_pdf and not is_png:
            ela_uniformity_score = 1.0 - min(1.0, doc_std / (doc_mean + 1e-6))
            consistency_score = 1.0 - min(1.0, inconsistent_ratio)
            noise_detected_pre = noise_analysis.get("detected", False)
            
            if doc_mean > 3.0:
                ela_factor = 1.0 - min(1.0, (doc_mean - 3.0) / 5.0)
            else:
                ela_factor = 1.0 - min(1.0, doc_mean / 0.6)
            
            re_save_probability = (ela_uniformity_score * 0.4) + (consistency_score * 0.4) + (ela_factor * 0.2)
            re_save_mean_threshold = max(0.50, min(10.0, doc_mean * 1.3))
            re_save_std_threshold = max(0.18, min(2.0, doc_std * 1.5))
            re_save_threshold = RE_SAVE_PROB if doc_mean < 0.55 else (RE_SAVE_PROB_ELA if doc_mean < 3.0 else RE_SAVE_PROB_HIGH)
            
            if doc_mean > 4.0:
                is_re_save = (re_save_probability >= RE_SAVE_PROB_HIGH and 
                             doc_std < re_save_std_threshold and 
                             len(inconsistent_regions) <= 1 and
                             inconsistent_ratio < 0.10 and
                             not noise_detected_pre and
                             ela_uniformity_score > RE_SAVE_UNIFORM and
                             consistency_score > RE_SAVE_CONSIST)
            else:
                is_re_save = (re_save_probability >= re_save_threshold and 
                             doc_std < re_save_std_threshold and 
                             len(inconsistent_regions) <= 1 and
                             inconsistent_ratio < 0.10 and
                             not noise_detected_pre and
                             ela_uniformity_score > RE_SAVE_UNIFORM_LOW and
                             consistency_score > RE_SAVE_CONSIST_LOW)
        
        if is_re_save:
            is_tampered = False
        
        # =====================================
        # Calculate Adaptive Tampering Score
        # =====================================
        tampering_score = 0
        noise_detected = noise_analysis.get("detected", False)
        lighting_detected = lighting_analysis.get("detected", False)
        
        
        lighting_confirmed = lighting_detected and (is_tampered or noise_detected)
        
        geometric_detected = multi_scale_analysis.get("detected", False)
        statistical_detected = statistical_analysis.get("detected", False)
        geometric_confidence = multi_scale_analysis.get("confidence", 0.0)
        statistical_confidence = statistical_analysis.get("confidence", 0.0)
        
        geometric_threshold = GEOMETRIC + (doc_mean * 0.1)
        statistical_threshold = STATISTICAL + (doc_std * 0.1)
        
        geometric_confirmed = geometric_detected and geometric_confidence > geometric_threshold and (is_tampered or noise_detected)
        statistical_confirmed = statistical_detected and statistical_confidence > statistical_threshold and (is_tampered or noise_detected)
        
        color_analysis = detect_color_matched_edits(image)
        template_analysis = detect_template_replacement(image)
        color_detected = color_analysis.get("detected", False)
        template_detected = template_analysis.get("detected", False)
        color_confidence = color_analysis.get("confidence", 0.0)
        template_confidence = template_analysis.get("confidence", 0.0)
        evidence["color_analysis"] = color_analysis
        evidence["template_analysis"] = template_analysis
        
        color_threshold = COLOR
        template_threshold = TEMPLATE
        color_confirmed = color_detected and color_confidence > color_threshold
        template_confirmed = template_detected and template_confidence > template_threshold
        
        if is_re_save:
            base_re_save_score = 20 + int(ela_uniformity_score * 40)
            tampering_score = min(60, max(20, base_re_save_score))
        elif is_tampered or noise_detected or lighting_confirmed or geometric_confirmed or statistical_confirmed or color_confirmed or template_confirmed:
            if not is_pdf and not is_png and len(inconsistent_regions) >= 3 and doc_mean > 0.5 and doc_mean < 0.65:
                pass
            base_score = 60 if is_tampered else 55
            
            region_base = min(15, len(inconsistent_regions) * 2)
            inconsistent_ratio_factor = min(10, int(inconsistent_ratio * 30))
            
            ela_mean_factor = min(5, int((doc_mean - 4.0) * 1.5)) if doc_mean > 4.0 else min(3, int((doc_mean - 3.0) * 1)) if doc_mean > 3.0 else 0
            ela_std_factor = min(3, int((doc_std - 1.0) * 2)) if doc_std > 1.0 else 0
            cv_factor = min(2, int((cv - 0.2) * 5)) if cv > 0.2 else 0
            
            noise_penalty = int(3) if noise_detected else 0
            lighting_penalty = int(2) if lighting_confirmed else 0
            geometric_penalty = min(3, int(geometric_confidence * 5)) if geometric_confirmed else 0
            statistical_penalty = min(3, int(statistical_confidence * 5)) if statistical_confirmed else 0
            color_penalty = min(4, int(color_confidence * 6)) if color_confirmed else 0
            template_penalty = min(3, int(template_confidence * 5)) if template_confirmed else 0
            
            tampering_score = base_score + region_base + inconsistent_ratio_factor + ela_mean_factor + ela_std_factor + cv_factor
            tampering_score += noise_penalty + lighting_penalty + geometric_penalty + statistical_penalty + color_penalty + template_penalty
            tampering_score = min(100, max(60, tampering_score))
        else:
            if len(inconsistent_regions) > 0:
                baseline_score = min(5, len(inconsistent_regions) * 1)
            else:
                baseline_score = 0
            tampering_score = baseline_score

        
        final_tampered = (is_tampered or noise_detected or lighting_confirmed or 
                         geometric_confirmed or statistical_confirmed or color_confirmed or template_confirmed)
        
        if is_re_save:
            return {
                "status": "ESCALATE",
                "evidence": evidence,
                "reason": f"Re-save pattern detected (uniformity: {ela_uniformity_score:.2f}, consistency: {consistency_score:.2f} - document may have been re-saved)",
                "tampering_score": tampering_score
            }
        
        if not is_pdf and not is_png and not is_re_save:
            borderline_re_save_prob = (ela_uniformity_score * 0.4) + (consistency_score * 0.4) + ((1.0 - min(1.0, tampering_score / 100.0)) * 0.2)
            borderline_threshold = RE_SAVE_PROB_ELA if doc_mean < 0.65 else 0.65
            
            if (borderline_re_save_prob >= borderline_threshold and 
                doc_mean < adaptive_ela_mean_threshold * 1.2 and 
                doc_std < adaptive_ela_std_threshold * 1.2 and 
                len(inconsistent_regions) <= adaptive_inconsistency_threshold + 2 and 
                tampering_score <= 90 and 
                not noise_detected):
                return {
                    "status": "ESCALATE",
                    "evidence": evidence,
                    "reason": f"Re-save pattern detected (moderate indicators - uniformity: {ela_uniformity_score:.2f}, score: {tampering_score})",
                    "tampering_score": tampering_score
                }
        
        camera_recapture_boost = 30
        min_camera_mean_ela = 0.5
        max_camera_mean_ela = 0.65
        if not is_pdf and not is_png and not final_tampered and not is_re_save:
            if len(inconsistent_regions) >= 3 and min_camera_mean_ela < doc_mean < max_camera_mean_ela:
                return {
                    "status": "ESCALATE",
                    "evidence": evidence,
                    "reason": "Camera recapture/scan pattern detected - document may be scanned (legitimate) or tampered - requires review",
                    "tampering_score": min(100, tampering_score + camera_recapture_boost)
                }
        
        if not is_pdf and not is_png and is_re_save and len(inconsistent_regions) >= 3 and min_camera_mean_ela < doc_mean < max_camera_mean_ela:
            return {
                "status": "ESCALATE",
                "evidence": evidence,
                "reason": "Camera recapture/scan pattern with re-save characteristics - requires review",
                "tampering_score": min(100, tampering_score + camera_recapture_boost)
            }
        
        if final_tampered:
            reasons = []
            if is_tampered:
                reasons.append("ELA detected inconsistent compression patterns")
            if noise_detected:
                reasons.append("Noise variance analysis detected pasted/spliced regions")
            if lighting_confirmed:
                reasons.append("Lighting direction analysis detected physically impossible lighting")
            if geometric_confirmed:
                reasons.append("Multi-scale analysis detected geometric transformations")
            if statistical_confirmed:
                reasons.append("Statistical forensics detected distribution anomalies")
            if color_confirmed:
                reasons.append("Advanced color analysis detected color-matched edits")
            if template_confirmed:
                reasons.append("Template replacement and blending artifacts detected")
            reason = " | ".join(reasons) + " (possible tampering)"
            
            return {
                "status": "FAIL",
                "evidence": evidence,
                "reason": reason,
                "tampering_score": tampering_score
            }

        # =====================================
        # Overall Map Statistics
        # =====================================
        evidence["ela_stats"]["overall"] = {
            "mean": float(np.mean(ela_map)),
            "std": float(np.std(ela_map)),
            "max": float(np.max(ela_map))
        }

        return {
            "status": "PASS",
            "evidence": evidence,
            "reason": "ELA shows consistent compression",
            "tampering_score": tampering_score
        }

    except Exception as e:
        return {
            "status": "PASS",
            "evidence": evidence,
            "reason": f"ELA error: {e}",
            "tampering_score": 5
        }
