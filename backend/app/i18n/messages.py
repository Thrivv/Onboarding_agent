"""
app/i18n/messages.py — EN / AR / ES templates for deterministic system messages.

Rendered with app.i18n.render_message(key, language, **params). Placeholders
use str.format syntax. Params carry data only (names, counts, share %, doc
names already localized via doc_name()) — data is never translated.

NOTE: the Arabic and Spanish copy here should get a native-speaker +
compliance review before production (FATCA / PEP / KYC wording in
particular); it is written to be accurate and neutral-formal, not reviewed.
"""

MESSAGES = {
    # ── Authorised Signatory selection saved (MOA / Partnership) ──────────
    # Replaces the old "Let me know if there's anyone else, outside this
    # list, who should be added as a Key Individual" ask: that question is
    # asked (with buttons) by the KiLoopCard once IDs are verified, so asking
    # it here as free text was a redundant dead end.
    "as_saved.upload_ids": {
        "english": "Your Authorised Signatory selections have been saved. Next, please upload the Emirates ID or Passport for the following {count} individual(s):\n\n{names}",
        "arabic": "تم حفظ اختيارات المفوّضين بالتوقيع. الخطوة التالية: يُرجى تحميل الهوية الإماراتية أو جواز السفر للأفراد التالية أسماؤهم ({count}):\n\n{names}",
        "spanish": "Se han guardado sus selecciones de Firmantes Autorizados. A continuación, cargue el Emirates ID o el pasaporte de las siguientes {count} persona(s):\n\n{names}",
    },
    "as_saved.partially_verified": {
        "english": "Your Authorised Signatory selections have been saved. {already} member(s) already have a verified identity document on file and won't be asked again. Next, please upload the Emirates ID or Passport for:\n\n{names}",
        "arabic": "تم حفظ اختيارات المفوّضين بالتوقيع. لدى {already} من الأعضاء مستند هوية موثّق مسبقاً ولن يُطلب منهم مرة أخرى. الخطوة التالية: يُرجى تحميل الهوية الإماراتية أو جواز السفر لكلٍّ من:\n\n{names}",
        "spanish": "Se han guardado sus selecciones de Firmantes Autorizados. {already} miembro(s) ya tienen un documento de identidad verificado y no se les volverá a solicitar. A continuación, cargue el Emirates ID o el pasaporte de:\n\n{names}",
    },
    "as_saved.all_verified": {
        "english": "Your Authorised Signatory selections have been saved, and every member already has a verified identity document on file.",
        "arabic": "تم حفظ اختيارات المفوّضين بالتوقيع، ولدى جميع الأعضاء مستند هوية موثّق مسبقاً.",
        "spanish": "Se han guardado sus selecciones de Firmantes Autorizados y todos los miembros ya tienen un documento de identidad verificado.",
    },

    # ── Single Owner AS selection ──────────────────────────────────────────
    "so_as.owner_verified_pending": {
        "english": "Got it — I've recorded **{owner}** as the owner and Authorised Signatory. Their identity document is already on file, so next I'll need the Emirates ID or Passport for:\n{names}",
        "arabic": "تم — سجّلتُ **{owner}** بصفته المالك والمفوّض بالتوقيع. مستند هويته موجود مسبقاً، لذا أحتاج بعد ذلك إلى الهوية الإماراتية أو جواز السفر لكلٍّ من:\n{names}",
        "spanish": "Entendido: he registrado a **{owner}** como propietario y Firmante Autorizado. Su documento de identidad ya consta en el expediente, así que a continuación necesitaré el Emirates ID o el pasaporte de:\n{names}",
    },
    "so_as.owner_verified_done": {
        "english": "Got it — I've recorded **{owner}** as the owner and Authorised Signatory. Their identity document is already on file, so there's nothing further needed here — moving on to the next step.",
        "arabic": "تم — سجّلتُ **{owner}** بصفته المالك والمفوّض بالتوقيع. مستند هويته موجود مسبقاً، فلا حاجة لأي إجراء إضافي هنا — ننتقل إلى الخطوة التالية.",
        "spanish": "Entendido: he registrado a **{owner}** como propietario y Firmante Autorizado. Su documento de identidad ya consta en el expediente, así que no se necesita nada más aquí; pasamos al siguiente paso.",
    },
    "so_as.owner_upload": {
        "english": "Got it — I've recorded **{owner}** as the owner and Authorised Signatory. Next, please upload their Emirates ID or Passport so I can verify their identity.",
        "arabic": "تم — سجّلتُ **{owner}** بصفته المالك والمفوّض بالتوقيع. الخطوة التالية: يُرجى تحميل الهوية الإماراتية أو جواز السفر الخاص به للتحقق من هويته.",
        "spanish": "Entendido: he registrado a **{owner}** como propietario y Firmante Autorizado. A continuación, cargue su Emirates ID o pasaporte para verificar su identidad.",
    },
    "so_as.then_also": {
        "english": "\n\nAfter that, the following will also be required:\n{names}",
        "arabic": "\n\nبعد ذلك، سيُطلب أيضاً ما يلي:\n{names}",
        "spanish": "\n\nDespués, también se requerirá lo siguiente:\n{names}",
    },

    # ── Key Individual add / contact / verify ─────────────────────────────
    "ki.ai_added": {
        "english": "{name} has been added and verified as {role}.\n\nWould you like to add another individual?",
        "arabic": "تمت إضافة {name} والتحقق منه بصفة {role}.\n\nهل ترغب في إضافة فرد آخر؟",
        "spanish": "{name} ha sido añadido y verificado como {role}.\n\n¿Desea añadir a otra persona?",
    },
    "ki.contact_saved": {
        "english": "Details for **{name}** have been saved.{share_line}\n\nWould you like to add another Authorised Signatory or Key Individual to this account?",
        "arabic": "تم حفظ بيانات **{name}**.{share_line}\n\nهل ترغب في إضافة مفوّض بالتوقيع أو فرد رئيسي آخر إلى هذا الحساب؟",
        "spanish": "Se han guardado los datos de **{name}**.{share_line}\n\n¿Desea añadir otro Firmante Autorizado o Persona Clave a esta cuenta?",
    },
    "ki.share_line": {"english": " | Share: {share}", "arabic": " | الحصة: {share}", "spanish": " | Participación: {share}"},
    "ki.added_fallback": {
        "english": "Key Individual {name} has been saved. Please upload their {id_type} for identity verification.",
        "arabic": "تم حفظ الفرد الرئيسي {name}. يُرجى تحميل {id_type} الخاص به للتحقق من الهوية.",
        "spanish": "Se ha guardado a la Persona Clave {name}. Cargue su {id_type} para la verificación de identidad.",
    },
    "ki.verified_fallback": {
        "english": "Identity verification complete. Would you like to add another Key Individual, or shall we proceed?",
        "arabic": "اكتمل التحقق من الهوية. هل ترغب في إضافة فرد رئيسي آخر، أم نتابع؟",
        "spanish": "Verificación de identidad completada. ¿Desea añadir otra Persona Clave o continuamos?",
    },

    # ── KI loop finalized ("No, Proceed") ──────────────────────────────────
    "ki_loop.so_fatca": {
        "english": "All identity documents are verified.{summary}\n\nOne more thing before we move on — please complete your **FATCA Declaration** below.",
        "arabic": "تم التحقق من جميع مستندات الهوية.{summary}\n\nأمر أخير قبل المتابعة — يُرجى استكمال **إقرار فاتكا (FATCA)** أدناه.",
        "spanish": "Todos los documentos de identidad están verificados.{summary}\n\nUna cosa más antes de continuar: complete su **Declaración FATCA** a continuación.",
    },
    "ki_loop.mo_fatca": {
        "english": "All {total} individuals are confirmed.{summary}\n\nOne more thing before we move on — please complete your **FATCA Declaration** below.",
        "arabic": "تم تأكيد جميع الأفراد ({total}).{summary}\n\nأمر أخير قبل المتابعة — يُرجى استكمال **إقرار فاتكا (FATCA)** أدناه.",
        "spanish": "Las {total} personas están confirmadas.{summary}\n\nUna cosa más antes de continuar: complete su **Declaración FATCA** a continuación.",
    },
    "ki_loop.pep": {
        "english": "FATCA declaration saved.{summary}\n\nPlease complete your **PEP (Politically Exposed Person) Declaration** below.",
        "arabic": "تم حفظ إقرار فاتكا.{summary}\n\nيُرجى استكمال **إقرار الأشخاص المعرّضين سياسياً (PEP)** أدناه.",
        "spanish": "Declaración FATCA guardada.{summary}\n\nComplete su **Declaración PEP (Persona Expuesta Políticamente)** a continuación.",
    },
    "ki_loop.package": {
        "english": "FATCA and PEP declarations are complete.{summary}\n\nPlease select your **Product Package** below. Review the available packages and choose the one that best suits your business needs.",
        "arabic": "اكتمل إقرارا فاتكا والأشخاص المعرّضين سياسياً.{summary}\n\nيُرجى اختيار **باقة المنتجات** أدناه. راجع الباقات المتاحة واختر الأنسب لاحتياجات عملك.",
        "spanish": "Las declaraciones FATCA y PEP están completas.{summary}\n\nSeleccione su **Paquete de Productos** a continuación. Revise los paquetes disponibles y elija el que mejor se adapte a su negocio.",
    },
    "ki_loop.so_selfdecl": {
        "english": "Product Package selected.{summary}\n\nPlease complete your **Self-Declaration** below.",
        "arabic": "تم اختيار باقة المنتجات.{summary}\n\nيُرجى استكمال **الإقرار الذاتي** أدناه.",
        "spanish": "Paquete de Productos seleccionado.{summary}\n\nComplete su **Autodeclaración** a continuación.",
    },
    "ki_loop.mo_selfdecl": {
        "english": "All {total} identity documents verified.{summary}\n\nThe final step is the **Self-Declaration**.",
        "arabic": "تم التحقق من جميع مستندات الهوية ({total}).{summary}\n\nالخطوة الأخيرة هي **الإقرار الذاتي**.",
        "spanish": "Los {total} documentos de identidad están verificados.{summary}\n\nEl último paso es la **Autodeclaración**.",
    },
    "summary.header_registered": {"english": "Registered Individuals:", "arabic": "الأفراد المسجّلون:", "spanish": "Personas registradas:"},
    "summary.header_final": {"english": "Final Members List:", "arabic": "القائمة النهائية للأعضاء:", "spanish": "Lista final de miembros:"},
    "summary.row": {
        "english": "{idx}. **{name}** — {role} | Share: {share} | {status}",
        "arabic": "{idx}. **{name}** — {role} | الحصة: {share} | {status}",
        "spanish": "{idx}. **{name}** — {role} | Participación: {share} | {status}",
    },
    "role.as": {"english": "Authorised Signatory", "arabic": "مفوّض بالتوقيع", "spanish": "Firmante Autorizado"},
    "role.member": {"english": "Member", "arabic": "عضو", "spanish": "Miembro"},
    "role.ubo_suffix": {"english": " (UBO)", "arabic": " (مستفيد نهائي)", "spanish": " (UBO)"},
    "status.verified": {"english": "Verified", "arabic": "تم التحقق", "spanish": "Verificado"},
    "status.pending": {"english": "⏳ Pending", "arabic": "⏳ قيد الانتظار", "spanish": "⏳ Pendiente"},

    # ── Summary self-declaration (legal wording — needs compliance review) ─
    "declaration.text": {
        "english": "I confirm that all information and documents submitted during this onboarding process are accurate, complete, and truthful to the best of my knowledge. I understand that providing false information may result in rejection of my application.",
        "arabic": "أؤكد أن جميع المعلومات والمستندات المقدَّمة خلال عملية التسجيل هذه دقيقة وكاملة وصحيحة على حد علمي. وأدرك أن تقديم معلومات غير صحيحة قد يؤدي إلى رفض طلبي.",
        "spanish": "Confirmo que toda la información y los documentos presentados durante este proceso de incorporación son exactos, completos y veraces a mi leal saber y entender. Entiendo que proporcionar información falsa puede dar lugar al rechazo de mi solicitud.",
    },

    # ── Bulk upload per-file acknowledgments ───────────────────────────────
    "bulk.moa_done": {
        "english": "Your Memorandum of Association has been successfully validated and accepted. Next, once you have approved these documents, we will move to the member verification stage where Emirates ID or Passport for all partners will be required to proceed further.",
        "arabic": "تم التحقق من عقد التأسيس وقبوله بنجاح. بعد اعتمادك لهذه المستندات، سننتقل إلى مرحلة التحقق من الأعضاء حيث ستكون الهوية الإماراتية أو جواز السفر لجميع الشركاء مطلوبة للمتابعة.",
        "spanish": "Su Memorando de Asociación ha sido validado y aceptado correctamente. A continuación, una vez que apruebe estos documentos, pasaremos a la etapa de verificación de miembros, donde se requerirá el Emirates ID o el pasaporte de todos los socios.",
    },
    "bulk.received": {
        "english": "Your {doc} has been received and validated successfully{member}. Document details are currently being processed.{next}",
        "arabic": "تم استلام {doc} والتحقق منه بنجاح{member}. تتم حالياً معالجة تفاصيل المستند.{next}",
        "spanish": "Su {doc} ha sido recibido y validado correctamente{member}. Los detalles del documento se están procesando.{next}",
    },
    "bulk.member_ctx": {"english": " for {name}", "arabic": " لـ {name}", "spanish": " para {name}"},
    "bulk.next": {"english": " Next, please upload your {doc}.", "arabic": " الخطوة التالية: يُرجى تحميل {doc}.", "spanish": " A continuación, cargue su {doc}."},
    "bulk.duplicate": {
        "english": "Another file in this batch was already accepted as {doc}. This one was skipped.",
        "arabic": "تم قبول ملف آخر في هذه الدفعة بصفته {doc}. تم تخطي هذا الملف.",
        "spanish": "Otro archivo de este lote ya fue aceptado como {doc}. Este se omitió.",
    },
}

# Localized document display names, keyed by the English display name that
# chatupload_helpers.get_display_document_name() / get_remaining_required_
# documents() already return. Unknown names pass through unchanged.
DOC_NAMES = {
    "Identity Document (Emirates ID or Passport)": {"arabic": "مستند الهوية (الهوية الإماراتية أو جواز السفر)", "spanish": "Documento de identidad (Emirates ID o pasaporte)"},
    "Emirates ID (EID)": {"arabic": "الهوية الإماراتية", "spanish": "Emirates ID (EID)"},
    "Emirates ID or Passport": {"arabic": "الهوية الإماراتية أو جواز السفر", "spanish": "Emirates ID o pasaporte"},
    "Emirates ID": {"arabic": "الهوية الإماراتية", "spanish": "Emirates ID"},
    "Passport": {"arabic": "جواز السفر", "spanish": "Pasaporte"},
    "Commercial License": {"arabic": "الرخصة التجارية", "spanish": "Licencia Comercial"},
    "Trade License": {"arabic": "الرخصة التجارية", "spanish": "Licencia Comercial"},
    "Ejari (Tenancy Contract)": {"arabic": "إيجاري (عقد الإيجار)", "spanish": "Ejari (Contrato de Arrendamiento)"},
    "Memorandum of Association (MOA)": {"arabic": "عقد التأسيس (MOA)", "spanish": "Memorando de Asociación (MOA)"},
    "Certificate of Incorporation (CoI)": {"arabic": "شهادة التأسيس (CoI)", "spanish": "Certificado de Constitución (CoI)"},
}


def doc_name(english_display: str, language: str) -> str:
    if language == "english" or not english_display:
        return english_display
    return DOC_NAMES.get(english_display, {}).get(language, english_display)
