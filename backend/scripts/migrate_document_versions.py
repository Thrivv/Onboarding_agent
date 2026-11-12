#!/usr/bin/env python3
"""
Data Migration Script: Fix documents without is_current field
Run this ONCE to fix all existing documents in the system
"""

import os
import json
from pathlib import Path
from datetime import datetime, timezone


def migrate_user_documents(user_email: str, documents_base_path: Path):
    """Migrate documents for a single user"""
    user_path = documents_base_path / user_email
    
    if not user_path.exists():
        print(f"[SKIP] No documents for {user_email}")
        return 0, 0
    
    print(f"\n{'='*80}")
    print(f"[MIGRATE] Processing user: {user_email}")
    print(f"{'='*80}\n")
    
    migrated_count = 0
    error_count = 0
    
    # Group documents by type
    document_versions = {}
    
    for item in user_path.iterdir():
        if not item.is_dir() or item.name == "members":
            continue
        
        output_file = item / "output.json"
        if not output_file.exists():
            continue
        
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            doc_type = data.get("document_type", "unknown")
            version = data.get("version", 1)
            is_current = data.get("is_current", None)
            
            if doc_type not in document_versions:
                document_versions[doc_type] = []
            
            document_versions[doc_type].append({
                "version": version,
                "is_current": is_current,
                "document_id": item.name,
                "output_file": output_file,
                "data": data
            })
            
        except Exception as e:
            print(f"[ERROR] Failed to read {output_file}: {e}")
            error_count += 1
    
    # Process each document type
    for doc_type, versions in document_versions.items():
        print(f"[PROCESS] {doc_type}: {len(versions)} version(s)")
        
        # Sort by version (highest first)
        versions.sort(key=lambda x: x["version"], reverse=True)
        
        # Find documents without is_current field
        needs_migration = [v for v in versions if v["is_current"] is None]
        
        if not needs_migration:
            print(f"  ✅ All versions have is_current field - skipping")
            continue
        
        print(f"  ⚠️  {len(needs_migration)} version(s) need migration")
        
        # The highest version should be current
        highest_version = versions[0]
        
        # Mark highest as current
        if highest_version["is_current"] is None:
            try:
                data = highest_version["data"]
                data["is_current"] = True
                data["_migrated_at"] = datetime.now(timezone.utc).isoformat()
                data["_migration_reason"] = "Highest version marked as current"
                
                with open(highest_version["output_file"], 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                
                print(f"  ✅ Marked v{highest_version['version']} as current")
                migrated_count += 1
            except Exception as e:
                print(f"  ❌ Failed to migrate v{highest_version['version']}: {e}")
                error_count += 1
        
        # Mark all others as superseded
        for v in versions[1:]:
            if v["is_current"] is None:
                try:
                    data = v["data"]
                    data["is_current"] = False
                    data["superseded_by"] = highest_version["document_id"]
                    data["_migrated_at"] = datetime.now(timezone.utc).isoformat()
                    data["_migration_reason"] = "Older version marked as superseded"
                    
                    with open(v["output_file"], 'w', encoding='utf-8') as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                    
                    print(f"  ✅ Marked v{v['version']} as superseded")
                    migrated_count += 1
                except Exception as e:
                    print(f"  ❌ Failed to migrate v{v['version']}: {e}")
                    error_count += 1
    
    return migrated_count, error_count


def main():
    """Main migration function"""
    # Determine documents path
    possible_paths = [
        Path("backend/documents/id"),
        Path("documents/id"),
        Path("app/backend/documents/id"),
    ]
    
    documents_path = None
    for path in possible_paths:
        if path.exists():
            documents_path = path
            break
    
    if not documents_path:
        print("❌ Could not find documents directory!")
        return
    
    print(f"\n{'='*80}")
    print(f"🔧 DOCUMENT VERSION MIGRATION")
    print(f"{'='*80}")
    print(f"Documents path: {documents_path.absolute()}")
    print(f"\n")
    
    # Get all user directories
    user_dirs = [d for d in documents_path.iterdir() if d.is_dir()]
    
    print(f"Found {len(user_dirs)} user(s) to process\n")
    
    total_migrated = 0
    total_errors = 0
    
    for user_dir in user_dirs:
        user_email = user_dir.name
        migrated, errors = migrate_user_documents(user_email, documents_path)
        total_migrated += migrated
        total_errors += errors
    
    print(f"\n{'='*80}")
    print(f"✅ MIGRATION COMPLETE")
    print(f"{'='*80}")
    print(f"Total documents migrated: {total_migrated}")
    print(f"Total errors: {total_errors}")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    main()