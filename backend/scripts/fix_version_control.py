"""
Migration script to fix version control issues in existing data.
Run this once to clean up any inconsistent states.
"""

from sqlalchemy import and_
from app.database import SessionLocal
from app.models import Document
from datetime import datetime

def fix_version_control():
    db = SessionLocal()
    
    try:
        print("Starting version control migration...")
        
        # Get all users with documents
        users = db.query(Document.user_id).distinct().all()
        
        for (user_id,) in users:
            print(f"\nProcessing user: {user_id}")
            
            # Get all document types for this user
            doc_types = db.query(Document.document_type, Document.member_id).filter(
                Document.user_id == user_id
            ).distinct().all()
            
            for doc_type, member_id in doc_types:
                # Get all documents of this type
                if doc_type == 'member_eid' and member_id:
                    docs = db.query(Document).filter(
                        and_(
                            Document.user_id == user_id,
                            Document.document_type == doc_type,
                            Document.member_id == member_id
                        )
                    ).order_by(Document.upload_date.desc()).all()
                else:
                    docs = db.query(Document).filter(
                        and_(
                            Document.user_id == user_id,
                            Document.document_type == doc_type
                        )
                    ).order_by(Document.upload_date.desc()).all()
                
                if not docs:
                    continue
                
                print(f"  {doc_type}" + (f" (member {member_id})" if member_id else "") + f": {len(docs)} versions")
                
                # Find the most recent approved document
                most_recent_approved = None
                for doc in docs:
                    if doc.status == 'approved':
                        most_recent_approved = doc
                        break
                
                # Set is_current appropriately
                if most_recent_approved:
                    # If we have an approved document, only it should be current
                    for doc in docs:
                        if doc.id == most_recent_approved.id:
                            doc.is_current = True
                            print(f"    ✓ Set approved document (v{doc.version}) as current")
                        else:
                            doc.is_current = False
                            print(f"    • Marked older document (v{doc.version}) as historical")
                else:
                    # No approved document - keep most recent as current
                    most_recent = docs[0]
                    for doc in docs:
                        if doc.id == most_recent.id:
                            doc.is_current = True
                            print(f"    ⚠ No approved version - keeping most recent (v{doc.version}, {doc.status}) as current")
                        else:
                            doc.is_current = False
        
        db.commit()
        print("\n✓ Migration completed successfully")
        
    except Exception as e:
        db.rollback()
        print(f"\n✗ Migration failed: {str(e)}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    fix_version_control()