#!/usr/bin/env python3
"""
Migration script to repair existing documents with version conflicts
Run this once to fix all existing broken documents in the system

✅ UPDATED: Now uses type-based conflict detection
"""

import sys
import os
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.supabase_client import supabase
from app.services.document_helpers import (
    detect_and_repair_version_conflicts,
    get_document_version_info
)


def repair_all_users():
    """
    Scan all users and repair version conflicts
    """
    try:
        print("="*80)
        print("🔧 DOCUMENT VERSION REPAIR SCRIPT")
        print("="*80)
        print()
        
        # Get all users from database
        response = supabase.table("users").select("email, name, account_type").execute()
        
        if not response.data:
            print("❌ No users found")
            return
        
        users = response.data
        print(f"📊 Found {len(users)} users to check\n")
        
        total_conflicts = 0
        total_repaired = 0
        users_with_conflicts = []
        
        for idx, user in enumerate(users, 1):
            email = user['email']
            name = user.get('name', 'Unknown')
            account_type = user.get('account_type', 'Unknown')
            
            print(f"[{idx}/{len(users)}] Checking {name} ({email})...")
            
            # Check and repair conflicts
            result = detect_and_repair_version_conflicts(
                user_email=email,
                member_name=None,
                auto_repair=True
            )
            
            conflicts_found = result.get("conflicts_found", 0)
            conflicts_repaired = result.get("conflicts_repaired", 0)
            
            if conflicts_found > 0:
                total_conflicts += conflicts_found
                total_repaired += conflicts_repaired
                users_with_conflicts.append({
                    "email": email,
                    "name": name,
                    "conflicts_found": conflicts_found,
                    "conflicts_repaired": conflicts_repaired,
                    "conflicts": result.get("conflicts", [])
                })
                
                if conflicts_repaired == conflicts_found:
                    print(f"  ✅ Found and repaired {conflicts_repaired} conflicts")
                else:
                    print(f"  ⚠️ Found {conflicts_found} conflicts, repaired {conflicts_repaired}")
                
                # Show details of what was repaired
                for conflict in result.get("conflicts", []):
                    doc_type = conflict.get("document_type")
                    count = conflict.get("current_count")
                    print(f"    📄 {doc_type}: {count} current versions found")
            else:
                print(f"  ✓ No conflicts")
        
        print()
        print("="*80)
        print("📊 SUMMARY")
        print("="*80)
        print(f"Total users scanned: {len(users)}")
        print(f"Users with conflicts: {len(users_with_conflicts)}")
        print(f"Total conflicts found: {total_conflicts}")
        print(f"Total conflicts repaired: {total_repaired}")
        print()
        
        if users_with_conflicts:
            print("Users with repaired conflicts:")
            for user_info in users_with_conflicts:
                status = "✅" if user_info["conflicts_found"] == user_info["conflicts_repaired"] else "⚠️"
                print(f"  {status} {user_info['name']} ({user_info['email']}): {user_info['conflicts_repaired']}/{user_info['conflicts_found']} repaired")
                
                # Show document types affected
                for conflict in user_info["conflicts"]:
                    doc_type = conflict.get("document_type")
                    count = conflict.get("current_count")
                    print(f"      - {doc_type}: {count} versions → 1 version")
        
        print()
        print("="*80)
        print("✅ REPAIR COMPLETE")
        print("="*80)
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


def repair_specific_user(email: str):
    """
    Repair conflicts for a specific user (useful for testing)
    """
    print(f"🔧 Repairing conflicts for: {email}")
    
    result = detect_and_repair_version_conflicts(
        user_email=email,
        member_name=None,
        auto_repair=True
    )
    
    print(f"\nResult:")
    print(f"  Conflicts found: {result.get('conflicts_found', 0)}")
    print(f"  Conflicts repaired: {result.get('conflicts_repaired', 0)}")
    
    if result.get("conflicts"):
        print(f"\nDetails:")
        for conflict in result["conflicts"]:
            print(f"  Document type: {conflict['document_type']}")
            print(f"  Current versions: {conflict['current_count']}")
            for doc in conflict['documents']:
                print(f"    - {doc['document_id']} (v{doc['version']})")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        # Repair specific user
        user_email = sys.argv[1]
        repair_specific_user(user_email)
    else:
        # Repair all users
        repair_all_users()