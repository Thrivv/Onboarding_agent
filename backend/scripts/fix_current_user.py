#!/usr/bin/env python3
"""
Quick fix script for 1812srini@gmail.com's documents
Run this to fix the is_current flags for the existing uploads
"""

import json
from pathlib import Path
from datetime import datetime, timezone

def fix_user_documents():
    """Fix the document flags for the test user"""
    
    # Path to user's documents
    user_email = "1812srini@gmail.com"
    base_path = Path(r"D:\Thrivv.ai\Onboarding_Agent[OTP]\backend\documents\id") / user_email
    
    if not base_path.exists():
        print(f"❌ User directory not found: {base_path}")
        return
    
    print(f"\n{'='*80}")
    print(f"🔧 FIXING DOCUMENTS FOR: {user_email}")
    print(f"{'='*80}\n")
    
    # ============================================================================
    # Document 1: OLD REJECTED EJARI (Thrivv Ejari.pdf)
    # ============================================================================
    old_ejari_path = base_path / "Thrivv Ejari" / "output.json"
    
    if old_ejari_path.exists():
        print(f"[FIX] 📄 Old Ejari (Thrivv Ejari.pdf)")
        
        with open(old_ejari_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Mark as NOT current (superseded)
        data["is_current"] = False
        data["superseded_by"] = "TC_0120251223005017_1"
        data["superseded_at"] = datetime.now(timezone.utc).isoformat()
        data["_manually_fixed"] = True
        
        with open(old_ejari_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print(f"  ✅ Marked as NOT current (superseded)")
    else:
        print(f"  ⚠️ File not found: {old_ejari_path}")
    
    # ============================================================================
    # Document 2: NEW APPROVED EJARI (TC_0120251223005017_1.pdf)
    # ============================================================================
    new_ejari_path = base_path / "TC_0120251223005017_1" / "output.json"
    
    if new_ejari_path.exists():
        print(f"\n[FIX] 📄 New Ejari (TC_0120251223005017_1.pdf)")
        
        with open(new_ejari_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Mark as CURRENT
        data["is_current"] = True
        data["version"] = 2
        data["supersedes"] = "Thrivv Ejari"
        data["_manually_fixed"] = True
        
        with open(new_ejari_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print(f"  ✅ Marked as CURRENT (v2)")
    else:
        print(f"  ⚠️ File not found: {new_ejari_path}")
    
    # ============================================================================
    # Document 3: OLD REJECTED COMMERCIAL (Thrivv Growth License 2025 (2).pdf)
    # ============================================================================
    old_commercial_path = base_path / "Thrivv Growth License 2025 (2)" / "output.json"
    
    if old_commercial_path.exists():
        print(f"\n[FIX] 📄 Old Commercial (Thrivv Growth License 2025 (2).pdf)")
        
        with open(old_commercial_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Mark as NOT current (superseded)
        data["is_current"] = False
        data["superseded_by"] = "SecureCertificate201803.aspx"
        data["superseded_at"] = datetime.now(timezone.utc).isoformat()
        data["_manually_fixed"] = True
        
        with open(old_commercial_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print(f"  ✅ Marked as NOT current (superseded)")
    else:
        print(f"  ⚠️ File not found: {old_commercial_path}")
    
    # ============================================================================
    # Document 4: CURRENT COMMERCIAL (SecureCertificate201803.aspx.pdf)
    # ============================================================================
    current_commercial_path = base_path / "SecureCertificate201803.aspx" / "output.json"
    
    if current_commercial_path.exists():
        print(f"\n[FIX] 📄 Current Commercial (SecureCertificate201803.aspx.pdf)")
        
        with open(current_commercial_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Ensure marked as current
        data["is_current"] = True
        data["version"] = data.get("version", 1)
        data["_manually_fixed"] = True
        
        with open(current_commercial_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print(f"  ✅ Confirmed as CURRENT")
    else:
        print(f"  ⚠️ File not found: {current_commercial_path}")
    
    # ============================================================================
    # Document 5: EID (eid.png)
    # ============================================================================
    eid_path = base_path / "eid" / "output.json"
    
    if eid_path.exists():
        print(f"\n[FIX] 📄 EID (eid.png)")
        
        with open(eid_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Ensure marked as current
        data["is_current"] = True
        data["version"] = data.get("version", 1)
        data["_manually_fixed"] = True
        
        with open(eid_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print(f"  ✅ Confirmed as CURRENT")
    else:
        print(f"  ⚠️ File not found: {eid_path}")
    
    print(f"\n{'='*80}")
    print(f"✅ FIX COMPLETE!")
    print(f"{'='*80}\n")
    print(f"Next steps:")
    print(f"1. Restart your FastAPI backend")
    print(f"2. Refresh the frontend")
    print(f"3. Check if 'Rejected: 1' is now 'Rejected: 0'")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    fix_user_documents()