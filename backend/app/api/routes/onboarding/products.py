"""
Product package selection and recommendation.

Three endpoints over `product_package_service`. The recommendation scores on
nature of business, annual turnover and ownership type.
"""
from app.i18n import localized

import logging
from fastapi import APIRouter, HTTPException
from app.services.chatupload_helpers import (
    user_docs_path,
    member_progress_path,
    get_display_document_name,
    get_allowed_document_types,
    check_documents_status,
    should_request_document,
    load_member_progress,
    get_remaining_required_documents,
    insert_conversation_log,
    
)
from app.services.product_package_service import (
    is_package_done, save_package_selection, get_package_selection,
    get_package_status, recommend_package_from_nob,
)
from app.schemas.products import ProductPackageSaveRequest
from app.domain.exceptions import (
    DomainError,
    ValidationError,
)

logger = logging.getLogger(__name__)

# Sub-router. The `/chatupload` prefix and tags are applied once in
# app/api/routes/onboarding/__init__.py, so every path below is unchanged.
router = APIRouter()

@router.post("/product-package/save")
async def save_product_package(req: ProductPackageSaveRequest):
    """
    Persist the user's product package selection (disk + Supabase).
    Returns package definitions so the frontend can display the full catalogue.
    """
    try:
        valid_packages = ("Essential", "Plus", "Advanced")
        if req.selected_package not in valid_packages:
            raise ValidationError(f"selected_package must be one of: {', '.join(valid_packages)}")
        if not req.availed_products:
            raise ValidationError("availed_products cannot be empty")

        logger.info(f"[PENDING-ACTIONS] Product Package submitted for {req.email}: {req.selected_package}")

        result = save_package_selection(
            email=req.email,
            selected_package=req.selected_package,
            availed_products=req.availed_products,
        )
        logger.info(f"[PENDING-ACTIONS] Product Package cleared for {req.email} — product_package_pending will read False on next status check")

        # ── Updated flow: FATCA → PEP → Product Package → Self-Declaration ──
        # Product Package is now the LAST step before Self-Declaration,
        # so after saving the package we trigger Self-Declaration (not FATCA).
        msg = localized(None,
            en=f"**{req.selected_package} Package** selected successfully.\n\nYour chosen services: {', '.join(req.availed_products)}.\n\nPlease complete your **Self-Declaration** below to finalise your onboarding.",
            es=f"**Paquete {req.selected_package}** seleccionado correctamente.\n\nServicios elegidos: {', '.join(req.availed_products)}.\n\nComplete su **Autodeclaración** a continuación para finalizar la incorporación.",
            ar=f"تم اختيار **باقة {req.selected_package}** بنجاح.\n\nالخدمات المختارة: {'، '.join(req.availed_products)}.\n\nيُرجى استكمال **الإقرار الذاتي** أدناه لإنهاء التسجيل.")

        insert_conversation_log(
            user_email=req.email,
            role="agent",
            message=msg,
            channel="chat",
            metadata={
                "message_type":              "product_package_saved",
                "selected_package":          req.selected_package,
                "availed_products":          req.availed_products,
                "self_declaration_trigger":  True,
            }
        )

        logger.info(f"[PKG] Package saved — user={req.email}, package={req.selected_package}")
        return {
            "success":                   True,
            "selected_package":          req.selected_package,
            "availed_products":          req.availed_products,
            "message":                   msg,
            "self_declaration_trigger":  True,
        }

    except (HTTPException, DomainError):
        raise
    except Exception as e:
        logger.error(f"[PKG] save_product_package error: {e}")
        raise DomainError(context=str(e))


@router.get("/product-package/status/{user_email}")
async def get_product_package_status(user_email: str):
    """Return the product package selection status for sidebar display."""
    try:
        status = get_package_status(user_email)
        selection = get_package_selection(user_email)
        return {
            "status":           status,
            "selected_package": selection.get("selected_package") if selection else None,
            "availed_products": selection.get("availed_products") if selection else [],
        }
    except Exception as e:
        logger.error(f"[PKG] get_product_package_status error: {e}")
        return {"status": "not_started", "selected_package": None, "availed_products": []}


@router.get("/product-package/recommend")
async def get_product_package_recommendation(email: str):
    """
    AI-driven package recommendation based on the user's nature of business.
    Returns: { recommended_package, confidence, reasoning, key_matches,
               nature_of_business, source }
    """
    try:
        logger.info(f"[PKG-RECOMMEND] Generating recommendation for: {email}")
        result = recommend_package_from_nob(email)
        logger.info(
            f"[PKG-RECOMMEND] Recommendation for {email}: "
            f"{result['recommended_package']} (confidence={result['confidence']}, source={result['source']})"
        )
        return result
    except Exception as e:
        logger.error(f"[PKG-RECOMMEND] Error: {e}")
        # Always return a safe fallback — never break the UI
        return {
            "recommended_package": "Plus",
            "confidence":          "low",
            "reasoning":           "We were unable to analyse your profile at this time. Plus is a solid default for most corporate accounts.",
            "key_matches":         ["Core account management", "Request to pay & EIPP support"],
            "nature_of_business":  [],
            "source":              "error_fallback",
        }
