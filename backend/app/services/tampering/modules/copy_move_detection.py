import cv2
import numpy as np
from typing import Dict, List, Tuple

# =====================================
# Constants
# =====================================
MAX_DIM = 512
BLOCK_SIZE = 8
SIMILARITY = 0.95
MIN_DISTANCE = 50
MIN_CLUSTER = 3
SPATIAL = 30
MAX_MATCHES = 100
SAMPLE_DIV = 50
MIN_BLOCKS = 10
CLUSTER_MULT = 4
MATCH_COUNT = 200
CONF_HIGH = 75
CONF_MOD = 50
CLUSTER_HIGH = 3
CLUSTER_MOD = 2
AFFECTED_HIGH = 0.03
AFFECTED_MOD = 0.02
SIM_HIGH = 0.95
TEST_BLOCK = 16
TEST_CLUSTER = 4
CONF_MULT = 20
SIM_MULT = 30
AFFECTED_MULT = 50
DIVISOR = 10.0
ESCALATE_MULT = 0.6
PASS_MULT = 0.2


def extract_block_features(image: np.ndarray, block_size: int = BLOCK_SIZE) -> Tuple[np.ndarray, List[Tuple[int, int]]]:
    h, w = image.shape[:2]
    
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image
    
    if max(h, w) > MAX_DIM:
        scale = MAX_DIM / max(h, w)
        new_w = int(w * scale)
        new_h = int(h * scale)
        gray = cv2.resize(gray, (new_w, new_h), interpolation=cv2.INTER_AREA)
        h, w = new_h, new_w
    
    gray = gray.astype(np.float32)
    features = []
    positions = []
    step = block_size
    
    for y in range(0, h - block_size + 1, step):
        for x in range(0, w - block_size + 1, step):
            block = gray[y:y+block_size, x:x+block_size]
            dct_block = cv2.dct(block)
            feature = dct_block[:block_size//2, :block_size//2].flatten()
            features.append(feature)
            positions.append((x, y))
    
    return np.array(features), positions


def find_similar_blocks(features: np.ndarray, positions: List[Tuple[int, int]], 
                       similarity_threshold: float = SIMILARITY, min_distance: int = MIN_DISTANCE) -> List[Dict]:
    if len(features) < 2:
        return []
    
    matches = []
    n_blocks = len(features)
    sample_rate = max(1, n_blocks // SAMPLE_DIV)
    
    for i in range(0, n_blocks, sample_rate):
        if len(matches) >= MAX_MATCHES:
            break
            
        for j in range(i + sample_rate, n_blocks, sample_rate):
            if len(matches) >= MAX_MATCHES:
                break
                
            pos1 = positions[i]
            pos2 = positions[j]
            distance = np.sqrt((pos1[0] - pos2[0])**2 + (pos1[1] - pos2[1])**2)
            
            if distance < min_distance:
                continue
            
            feature1 = features[i]
            feature2 = features[j]
            norm1 = np.linalg.norm(feature1)
            norm2 = np.linalg.norm(feature2)
            
            if norm1 == 0 or norm2 == 0:
                continue
            
            similarity = np.dot(feature1, feature2) / (norm1 * norm2)
            
            if similarity >= similarity_threshold:
                matches.append({
                    "block1_pos": pos1,
                    "block2_pos": pos2,
                    "similarity": float(similarity),
                    "distance": float(distance)
                })
    
    return matches


def cluster_matches(matches: List[Dict], spatial_threshold: int = SPATIAL) -> List[Dict]:
    if not matches:
        return []
    
    clusters = []
    used = set()
    
    for i, match in enumerate(matches):
        if i in used:
            continue
        
        cluster = [match]
        used.add(i)
        pos1 = match["block1_pos"]
        pos2 = match["block2_pos"]
        
        for j, other_match in enumerate(matches[i+1:], start=i+1):
            if j in used:
                continue
            
            other_pos1 = other_match["block1_pos"]
            other_pos2 = other_match["block2_pos"]
            dist1 = np.sqrt((pos1[0] - other_pos1[0])**2 + (pos1[1] - other_pos1[1])**2)
            dist2 = np.sqrt((pos2[0] - other_pos2[0])**2 + (pos2[1] - other_pos2[1])**2)
            
            if dist1 < spatial_threshold or dist2 < spatial_threshold:
                cluster.append(other_match)
                used.add(j)
        
        if len(cluster) >= 2:
            clusters.append({
                "matches": cluster,
                "match_count": len(cluster),
                "avg_similarity": np.mean([m["similarity"] for m in cluster]),
                "region_size": len(cluster) * BLOCK_SIZE
            })
    
    return clusters


def detect_copy_move_regions(image: np.ndarray, block_size: int = BLOCK_SIZE, 
                            similarity_threshold: float = SIMILARITY,
                            min_distance: int = MIN_DISTANCE,
                            min_cluster_size: int = MIN_CLUSTER) -> Dict:
    try:
        if len(image.shape) == 3:
            h, w = image.shape[:2]
        else:
            h, w = image.shape
        
        if h < block_size * 2 or w < block_size * 2:
            return {
                "detected": False,
                "reason": "Image too small for copy-move detection",
                "clusters": [],
                "total_matches": 0,
                "confidence": 0.0
            }
        
        features, positions = extract_block_features(image, block_size)
        
        if len(features) < MIN_BLOCKS:
            return {
                "detected": False,
                "reason": "Insufficient blocks for analysis",
                "clusters": [],
                "total_matches": 0,
                "confidence": 0.0
            }
        
        matches = find_similar_blocks(features, positions, similarity_threshold, min_distance)
        
        if not matches:
            return {
                "detected": False,
                "reason": "No duplicate regions detected",
                "clusters": [],
                "total_matches": 0,
                "confidence": 0.0
            }
        
        clusters = cluster_matches(matches, spatial_threshold=block_size * CLUSTER_MULT)
        significant_clusters = [c for c in clusters if c["match_count"] >= min_cluster_size]
        
        if not significant_clusters:
            return {
                "detected": False,
                "reason": "Duplicate regions too small to indicate tampering",
                "clusters": [],
                "total_matches": len(matches),
                "confidence": 0.0
            }
        
        total_match_count = sum(c["match_count"] for c in significant_clusters)
        avg_similarity = np.mean([c["avg_similarity"] for c in significant_clusters])
        image_area = h * w
        affected_area = sum(c["region_size"] for c in significant_clusters)
        affected_ratio = affected_area / image_area if image_area > 0 else 0
        confidence = min(100, (total_match_count / DIVISOR) * CONF_MULT + (avg_similarity * SIM_MULT) + (affected_ratio * AFFECTED_MULT))
        
        return {
            "detected": True,
            "reason": f"Found {len(significant_clusters)} copy-move region(s) with {total_match_count} duplicate block(s)",
            "clusters": significant_clusters,
            "total_matches": total_match_count,
            "avg_similarity": float(avg_similarity),
            "affected_ratio": float(affected_ratio),
            "confidence": float(confidence)
        }
    
    except Exception as e:
        return {
            "detected": False,
            "reason": f"Error in copy-move detection: {str(e)}",
            "clusters": [],
            "total_matches": 0,
            "confidence": 0.0
        }


def test_copy_move_detection(file_path: str, image: np.ndarray) -> Dict:
    evidence = {
        "file_path": file_path,
        "analysis_type": "copy_move_detection"
    }
    
    try:
        result = detect_copy_move_regions(
            image,
            block_size=TEST_BLOCK,
            similarity_threshold=SIMILARITY,
            min_distance=MIN_DISTANCE,
            min_cluster_size=TEST_CLUSTER
        )
        
        evidence["detection_result"] = result
        
        if result["detected"]:
            confidence = result.get("confidence", 0.0)
            total_matches = result.get("total_matches", 0)
            affected_ratio = result.get("affected_ratio", 0.0)
            cluster_count = len(result.get("clusters", []))
            avg_similarity = result.get("avg_similarity", 0.0)
            
            is_pdf = file_path.lower().endswith('.pdf')
            
            if total_matches >= MATCH_COUNT:
                status = "PASS"
                tampering_score = 0
                reason = "Too many matches detected (likely false positive from uniform regions)"
            elif confidence >= CONF_HIGH and cluster_count >= CLUSTER_HIGH and affected_ratio > AFFECTED_HIGH and avg_similarity > SIM_HIGH:
                status = "FAIL"
                tampering_score = min(100, max(60, int(60 + (confidence * 0.4))))
                reason = f"Copy-move tampering detected: {result['reason']}"
            elif confidence >= CONF_MOD and cluster_count >= CLUSTER_MOD and affected_ratio > AFFECTED_MOD:
                if is_pdf:
                    status = "PASS"
                    tampering_score = 5
                    reason = "PDF with repeated elements (likely legitimate)"
                else:
                    status = "ESCALATE"
                    tampering_score = min(60, max(20, int(20 + (confidence * 0.4))))
                    reason = f"Possible copy-move tampering: {result['reason']}"
            else:
                status = "PASS"
                tampering_score = min(10, int(confidence * 0.1))
                reason = "Minor duplicate patterns detected (likely natural repetition)"
        else:
            status = "PASS"
            tampering_score = 0
            reason = result.get("reason", "No copy-move tampering detected")
        
        return {
            "status": status,
            "reason": reason,
            "evidence": evidence,
            "tampering_score": tampering_score
        }
    
    except Exception as e:
        return {
            "status": "ERROR",
            "reason": f"Error in copy-move detection: {str(e)}",
            "evidence": evidence,
            "tampering_score": 0
        }

