// frontend/src/features/onboarding/OnboardingPage.jsx
/**
 * The onboarding screen.
 *
 * Was `pages/AIAssistant.jsx` — 8,536 lines holding 49 top-level declarations.
 * Stage B7 moved 48 of them into `components/`, `utils/` and `config/` beside
 * this file, plus two shared primitives (`InfoRow`, `FormSection`) into
 * `components/ui/`. Every component moved **verbatim**; none were merged,
 * renamed or rewritten.
 *
 * What is still outstanding, deliberately
 * ---------------------------------------
 * This component still holds ~111 `useState` and ~26 `useEffect` declarations,
 * so every state change still re-renders the whole screen. Collapsing those
 * into `useReducer` slices is Stage B8. It is separated from B7 because it is
 * the one frontend change that alters *timing* rather than structure — effect
 * ordering and render counts can shift — and that needs to be migrated one
 * slice at a time against a running UI, not in a bulk move.
 *
 * `FatcaInlineCard` and `FatcaModal` remain separate files despite being near
 * duplicates (~540 lines between them). Merging them behind a `variant` prop
 * is a real change, not a move, so it is flagged for sign-off rather than done
 * quietly here.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import api from '../../api/client';
import { getFatcaStatus, getPepStatus, getSelfDeclarationStatus } from '../../api/compliance';
import { getDocumentStatus } from '../../api/documents';
import { finalizeKeyIndividualLoop, selectSingleOwnerAuthorisedSignatory } from '../../api/keyIndividuals';
import { assignMismatchRole, getConversationLogs, getOnboardingStatus, sendChatMessage, startConversation, uploadDocument, uploadDocumentsBulk } from '../../api/onboarding';
import { getPackageStatus } from '../../api/products';
import Sidebar from '../../components/layout/Sidebar';
import LanguageToggle from '../../components/common/LanguageToggle';
import { useAuth } from '../../context/AuthContext';
import { useLanguage } from '../../context/LanguageContext';
import { AnimatePresence, motion } from 'framer-motion';
import { AlertCircle, Building, CheckCircle, ChevronRight, Clock, Eye, File, FileText, History, Home, Package, Paperclip, Phone, RefreshCw, Send, ShieldCheck, Upload, User, Users, X } from 'lucide-react';
import toast from 'react-hot-toast';
import { AsKiManagementCard } from './components/cards/AsKiManagementCard';
import { KiDetailsCard } from './components/cards/KiDetailsCard';
import { KiLoopCard } from './components/cards/KiLoopCard';
import { KiRoleAssignCard } from './components/cards/KiRoleAssignCard';
import { OnboardingSuccessCard } from './components/cards/OnboardingSuccessCard';
import { OwnershipTypeCard } from './components/cards/OwnershipTypeCard';
import { ProductPackageCard } from './components/cards/ProductPackageCard';
import { SelfDeclarationCard } from './components/cards/SelfDeclarationCard';
import { MessageContent } from './components/chat/MessageContent';
import { OnboardingErrorBoundary } from './components/OnboardingErrorBoundary';
import { FatcaInlineCard } from './components/compliance/FatcaInlineCard';
import { PepInlineCard } from './components/compliance/PepInlineCard';
import { ComplianceHistoryToggle, FATCAReportBlock, PEPReportBlock, ProductPackageReportBlock, RegisteredIndividualsReportBlock, SummaryDeclarationReportBlock } from './components/compliance/ReportBlocks';
import { ExtractedDataDisplay } from './components/extracted/ExtractedDataDisplay';
import { DocumentPreviewModal } from './components/modals/DocumentPreviewModal';
import { FatcaModal } from './components/modals/FatcaModal';
import { FinalSuccessModal } from './components/modals/FinalSuccessModal';
import { RoleMismatchSelector } from './components/modals/RoleMismatchSelector';
import { SuccessConfetti } from './components/status/SuccessDisplay';
import { getUserInitials, stripFormatting } from './utils/formatters';
import { logicText, stripMemberLists } from './utils/i18nText';
import { deriveCardState } from './utils/cardState';
import { translateDocName } from './utils/reportI18n';
import logger from '../../utils/logger';

// Unified Report section ids (English, used for colours/logic) -> translation keys.
const REPORT_SECTION_KEYS = {
  'Business Details': 'business',
  'User Details': 'user',
  'Additional Details': 'additional',
  'Declaration': 'declaration',
};

// Module-level so the reference is stable across every render. See the note at
// its use site.
const EMPTY_COMPLIANCE_HISTORY = Object.freeze([]);

// Display names for the "Translated from X" caption — Phase 1 of
// docs/language-mirroring-verdict.html. Backend language values are always
// the lowercase "english" | "arabic" | "spanish" strings (see
// app/utils/language.py::SUPPORTED_LANGUAGES); "unknown" covers the rare
// case detect_and_translate_input() couldn't confidently name the language.
const TRANSLATED_FROM_KEY = Object.freeze({
  english: 'langEnglish',
  arabic: 'langArabic',
  spanish: 'langSpanish',
  unknown: 'langUnknown',
});

// DocumentPreviewModal picks its PDF/image render branch off document.type,
// which needs to be an actual MIME type ("application/pdf") — not a semantic
// document type ("commercial"). Neither the single-file upload's own
// conversation-log metadata nor the bulk one ever stored a real MIME type
// (see document_info in upload.py), so document_info.document_type used to
// leak straight into documentMetadata.type on both live bulk results and any
// reload/relogin history replay, and the modal always fell through to
// "Preview not available" even though previewUrl was valid. Used at both the
// live bulk-result site and the conversation-log restore site below so a fix
// here covers a reload of either upload path, not just bulk.
const inferMimeTypeFromFilename = (filename) => {
  const ext = (filename || '').split('.').pop()?.toLowerCase();
  if (ext === 'pdf') return 'application/pdf';
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'].includes(ext)) return `image/${ext === 'jpg' ? 'jpeg' : ext}`;
  return null;
};

const AIAssistant = () => {
  const { user } = useAuth();
  const { language: globalLanguage, t: tContext, syncFromAccount } = useLanguage();
  // Stable-identity t() that always reads the CURRENT language. Many handlers
  // below are useCallback'd with deps that don't include t; with the context
  // t they'd keep translating into the language active when they were
  // created (e.g. a toast in English right after switching to Arabic).
  const tRef = useRef(tContext);
  tRef.current = tContext;
  const t = useCallback((key, vars) => tRef.current(key, vars), []);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [uploadedFile, setUploadedFile] = useState(null);
  // Bulk sibling of uploadedFile — the paperclip's file input now allows
  // selecting more than one file. uploadedFile always mirrors
  // uploadedFiles[0] so every pre-existing single-file check
  // (`uploadedFile && ...`, `disabled={!uploadedFile}`, etc.) keeps
  // working unchanged when exactly one file is picked. Bulk mode is
  // triggered purely by uploadedFiles.length > 1 — there is no separate
  // toggle or card asking the user to choose a mode.
  const [uploadedFiles, setUploadedFiles] = useState([]);
  const [memberName, setMemberName] = useState('');

  // B8: frozen. Declared with useState but no setter was ever declared, so it
  // has been `false` for the entire life of the component. A useState whose
  // value never changes is a constant that costs a render slot; making that
  // explicit is behaviour-identical.
  //
  // It still gates two branches — `if (showMemberInput && !memberName.trim())`
  // and `if (showMemberInput)` — which are therefore unreachable. They are left
  // in place on purpose: deleting live-looking logic is a design decision, not
  // a cleanup, and it belongs with the Layout.jsx / UboConfirmCard question
  // already waiting for Srini.
  const showMemberInput = false;

  // LANGUAGE — read straight from LanguageContext (single source of truth).
  // This used to be a separate useState mirrored from globalLanguage via a
  // useEffect, which lagged one render behind every toggle: a chat/upload
  // request fired in that window went out in the OLD language. The name
  // `selectedLanguage` is kept so its ~15 existing call sites don't change.
  // (api/client.js also stamps every request with the current language.)
  const selectedLanguage = globalLanguage;
  // Phase 2 (docs/language-mirroring-verdict.html): true while already-sent
  // chat history is being re-fetched/re-translated after a toggle switch.
  // Drives the small "Translating conversation..." banner above the message
  // list — see the re-fetch effect further down, right after the
  // preferredLanguage localStorage effect.
  const [isTranslatingHistory, setIsTranslatingHistory] = useState(false);
  // Dynamic Required Documents Tracking
  const [requiredDocKeys, setRequiredDocKeys] = useState(['commercial_license', 'moa', 'coi', 'emirates_id', 'ejari']);

  // Document preview — note this is the SIDEBAR preview. openPreview() sets
  // previewDocument and switches sidebarMode to 'preview'.
  const [previewDocument, setPreviewDocument] = useState(null);

  // B8: frozen, and it says something. `setShowPreview` was never called, so
  // <DocumentPreviewModal isOpen={showPreview}> has never opened. Preview is
  // not broken — it was moved into the sidebar and the modal was left behind.
  // Superseded design, same category as UboConfirmCard: whether to delete the
  // modal or restore it as the preview surface is Srini's call, so the value
  // is made explicit here and the modal left mounted.
  const showPreview = false;

  // Re-upload state
  const [pendingReuploadType, setPendingReuploadType] = useState(null);

  // ── v3 modals ────────────────────────────────────────────────────────────
  // Helper: true for any corporate ownership type regardless of casing
  const isCorporateAccount =
    (user?.account_type || '').toLowerCase() === 'corporate' ||
    ['single owner', 'multiple owners', 'partnership'].includes(
      (user?.ownership_type || '').toLowerCase()
    );
  const [showFatcaModal, setShowFatcaModal] = useState(false);
  // KI conversational loop — true while AI is waiting for the user to upload an EID/Passport
  const [awaitingAiAddEid, setAwaitingAiAddEid] = useState(false);
  const [showFinalSuccess, setShowFinalSuccess] = useState(false);
  const [finalRefNumber, setFinalRefNumber] = useState(() => sessionStorage.getItem('final_ref_number') || '');
  const [activeDocData, setActiveDocData] = useState(null);
  const [sidebarDismissed, setSidebarDismissed] = useState(false);
  const sidebarScrollRef = useRef(null);
  const [sidebarMode, setSidebarMode] = useState('library'); // 'data' | 'preview' | 'library'
  const [isDeclarationEnabled, setIsDeclarationEnabled] = useState(false);
  const [isOnboardingComplete, setIsOnboardingComplete] = useState(false);

  const [fatcaData, setFatcaData] = useState(null);

  // Sync right-sidebar open state to document.body for CSS targeting
  useEffect(() => {
    if (activeDocData) {
      document.body.classList.add('right-sidebar-open');
    } else {
      document.body.classList.remove('right-sidebar-open');
    }
    return () => document.body.classList.remove('right-sidebar-open');
  }, [activeDocData]);
  const [pepData, setPepData] = useState(null);
  const [productPackageData, setProductPackageData] = useState(null);

  // Validated Documents Library
  // eslint-disable-next-line no-unused-vars
  const [validatedDocs, setValidatedDocs] = useState([]);
  const [currentStepId, setCurrentStepId] = useState(null);

  // Sync state from backend responses
  const [backendStage, setBackendStage] = useState('corporate');
  const [backendSubmittedDocs, setBackendSubmittedDocs] = useState([]);
  // B8: frozen. No setter was ever declared, so the ComplianceHistoryCard has
  // always rendered against an empty list. Whether that card should be fed
  // from the backend or removed is a product question, not a refactor.
  // Hoisted out of the component so the identity is stable across renders —
  // as `useState([])` it was already stable, but a fresh `[]` literal in the
  // body would not have been, and that is a real trap for anything that
  // later puts it in a dependency array.
  const complianceHistory = EMPTY_COMPLIANCE_HISTORY;
  const [persistentRoleMap, setPersistentRoleMap] = useState({}); // 🔒 Session-persistent role vault

  // Ref-based bridge: AsKiManagementCard registers its addIndividual fn here,
  // so handleKISaved can push each saved KI into the card's list.
  const moaCardResetRef = useRef(null);
  const kiSavedCallbackBridge = useRef({
    register: (ref) => { moaCardResetRef.current = ref; },
  });

  const [membersInfo, setMembersInfo] = useState(null);
  const messagesEndRef = useRef(null);
  const fileInputRef = useRef(null);
  const [activeChatFilter, setActiveChatFilter] = useState(null);

  const lastLiveSectionRef = useRef(null);

  // eslint-disable-next-line no-unused-vars
  const { status, totalVerifiedCount, isCorporateDocsComplete } = useMemo(() => {
    const status = {};
    requiredDocKeys.forEach(key => status[key] = 'pending');

    // 1. Determine current stage from the latest transition or backend sync
    const latestStageMsg = [...messages].reverse().find(m => m.toStage || m.newStage || m.stage);
    const effectiveStage = latestStageMsg?.toStage || latestStageMsg?.newStage || latestStageMsg?.stage || backendStage || 'identification';

    // 2. Pre-fill status from backend submitted documents
    if (Array.isArray(backendSubmittedDocs)) {
      backendSubmittedDocs.forEach(doc => {
        const type = (doc.document_type || doc.type || '').toLowerCase();
        const isValid = doc.is_valid !== false; // Assume valid unless explicitly false

        if (isValid) {
          if (type.includes('coi') || type.includes('incorporation')) status.coi = 'success';
          else if (type.includes('commercial') || type.includes('license')) status.commercial_license = 'success';
          else if (type.includes('moa') || type.includes('memorandum')) status.moa = 'success';
          else if (type.includes('eid') || type.includes('passport') || type.includes('identity')) status.emirates_id = 'success';
          else if (type.includes('ejari') || type.includes('tenancy')) status.ejari = 'success';
        } else if (status[type] !== 'success') {
          status[type] = 'progress';
        }
      });
    }

    messages.forEach(msg => {
      if (msg.extractedData && msg.tamperingStatus !== 'REJECT') {
        const type = msg.documentType?.toLowerCase() || '';

        // If the stage has already moved beyond corporate docs, 
        // then Commercial, COI, MOA, and Ejari are implicitly complete 
        // (unless the backend keeps them in progress, but usually stage move means they are accepted)
        const isPostCorporate = ['member_eids', 'fatca', 'pep', 'self_declaration'].includes(effectiveStage);

        const stageComplete = msg.isComplete !== false || isPostCorporate;

        // Match Certificate of Incorporation
        if (type.includes('coi') || type.includes('incorporation')) {
          if (stageComplete) status.coi = 'success';
          else if (status.coi !== 'success') status.coi = 'progress';
        }
        // Match Commercial License
        else if (type.includes('commercial') || type.includes('license')) {
          if (stageComplete) status.commercial_license = 'success';
          else if (status.commercial_license !== 'success') status.commercial_license = 'progress';
        }

        // Match MOA
        if (type.includes('moa') || type.includes('memorandum')) {
          if (stageComplete) status.moa = 'success';
          else if (status.moa !== 'success') status.moa = 'progress';
        }

        const isPostIdentity = messages.some(m => m.fatcaTrigger || m.pepTrigger || m.selfDeclTrigger);

        // Match Identity
        if (type.includes('emirates_id') || type.includes('passport') || type.includes('eid')) {
          // IDENTITY only turns 'success' (green) if verification is complete AND Product Package is finalized
          const docsVerified = stageComplete || isPostIdentity;
          const packageFinalized = !!productPackageData;

          if (docsVerified && packageFinalized) status.emirates_id = 'success';
          else if (docsVerified && !packageFinalized) status.emirates_id = 'progress';
          else if (status.emirates_id !== 'success') status.emirates_id = 'progress';
        }

        // Match Ejari
        if (type.includes('ejari') || type.includes('tenancy')) {
          if (stageComplete) status.ejari = 'success';
          else if (status.ejari !== 'success') status.ejari = 'progress';
        }
      }
    });

    const items = [
      { key: 'commercial_license' },
      { key: 'coi' },
      { key: 'moa' },
      { key: 'emirates_id' },
      { key: 'ejari' }
    ].filter(item => requiredDocKeys.includes(item.key));

    const count = items.filter(i => status[i.key] === 'success').length;

    // ✅ FIXED: Determine if all corporate-category documents are complete
    // We map backend-style keys to our internal status keys for the completion check
    const corporateStatusKeys = ['commercial_license', 'moa', 'ejari', 'coi'];
    const corpKeys = corporateStatusKeys.filter(k => {
      // Check if this internal key or its backend counterpart is in requiredDocKeys
      if (requiredDocKeys.includes(k)) return true;
      if (k === 'commercial_license' && (requiredDocKeys.includes('commercial') || requiredDocKeys.includes('license'))) return true;
      if (k === 'ejari' && (requiredDocKeys.includes('tenancy') || requiredDocKeys.includes('address_proof'))) return true;
      if (k === 'moa' && requiredDocKeys.includes('memorandum')) return true;
      if (k === 'coi' && requiredDocKeys.includes('incorporation')) return true;
      return false;
    });

    // Check if we have at least one success for each identified corporate key
    // ✅ FIX: Avoid "fake" success if corpKeys is empty (initial load)
    const isCorporateDocsComplete = corpKeys.length > 0 && corpKeys.every(k => status[k] === 'success');

    if (corpKeys.length > 0) {
      logger.log('[COMPLETION] Corporate Check:', {
        requiredKeys: corpKeys,
        status: corpKeys.reduce((acc, k) => ({ ...acc, [k]: status[k] }), {}),
        isComplete: isCorporateDocsComplete
      });
    }

    return { status, totalVerifiedCount: count, isCorporateDocsComplete };
  }, [messages, requiredDocKeys, productPackageData, backendSubmittedDocs, backendStage]);

  // Helper to categorize messages into sidebar sections
  const getMessageSection = (msg) => {
    // 1. Welcome Section
    if (msg.isWelcome || msg.isWelcomeMessage) return 'welcome';

    // 1a. Explicit override — set only on bulk-upload result messages for a
    // document that OCR'd as an identity type (eid/passport) but was part of
    // a batch submitted while the account was still in the Corporate stage
    // (see handleBulkUpload's isPrematureIdentityDoc). Normal messages never
    // carry this field, so it only ever short-circuits that one case — it
    // deliberately does NOT apply to the Authorised Signatory/Member card
    // itself (asKiTrigger/moaAsTrigger, handled in block 3 below), which
    // stays in the Identity tab regardless of when its underlying documents
    // were uploaded.
    if (msg.sectionOverride) return msg.sectionOverride;

    const type = (msg.documentType || msg.stage || '').toLowerCase();
    // logicText: English rendering when known + EN aliases for AR/ES keywords,
    // so the keyword fallbacks below work in every language (utils/i18nText.js).
    const content = logicText(msg);

    // 1b. Self-Declaration takes priority — check BEFORE product package
    // A message that has both productPackageTrigger and selfDeclTrigger (from onConfirmed)
    // must be treated as declaration, not additional.
    if (msg.selfDeclTrigger || msg.isSelfDeclConfirmed || msg.onboardingComplete || msg.isCrossValidResult) return 'declaration';

    // 2. High Priority Compliance Triggers (CHECK FIRST to ensure progression)
    // Structural flags only here — these are set explicitly by the backend
    // for the message that actually IS the FATCA/PEP/package step, so they're
    // reliable. The content.includes('fatca')/('pep') text-keyword fallback
    // used to live in this same block, which misfired on messages that only
    // MENTION what's coming next: the last member-EID confirmation message
    // ("...that's everyone. Please complete your FATCA Declaration below to
    // continue.") is itself still an Identity-stage message (it can carry
    // kiLoopPrompt and show the "Add More Individuals?" card), but the word
    // "FATCA" in its own forward-referencing text used to win here, before
    // block 3 ever got a chance to see kiLoopPrompt/asKiTrigger/etc., and
    // send the whole message — card included — to the Additional tab a step
    // early. The keyword fallback now runs after block 3 (see below), so it
    // only ever catches messages with no structural signal at all.
    if (
      msg.fatcaTrigger ||
      msg.stage === 'fatca' ||
      msg.pepTrigger ||
      msg.stage === 'pep' ||
      msg.productPackageTrigger ||
      msg.product_package_trigger ||
      msg.package_trigger ||
      msg.stage === 'product_package' ||
      msg.isFatcaConfirmed ||
      msg.isPepConfirmed ||
      msg.isProductPackageConfirmed
    ) return 'additional';

    // 3. Identity & Signatories
    if (
      msg.toStage === 'member_eids' ||
      msg.stage === 'member_eids' ||
      type.includes('eid') ||
      type.includes('passport') ||
      type.includes('identity') ||
      type.includes('member_eid') ||
      type.includes('identification') ||
      type === 'user' ||
      type === 'identity' ||
      msg.moaAsTrigger ||
      msg.asKiTrigger ||
      msg.memberRoleTrigger ||
      msg.member_role_map ||
      msg.isAiKiEidCapture ||
      msg.kiLoopPrompt ||
      msg.ki_loop_prompt ||
      content.includes('signatory') ||
      content.includes('signatories')
    ) {
      return 'user';
    }

    // 3a. Compliance content-keyword fallback — only reached once neither the
    // structural compliance flags (2, above) nor the structural/keyword
    // Identity checks (3, above) matched. See the comment on block 2 for why
    // this can't run before block 3.
    if (
      content.includes('fatca') ||
      content.includes('pep') ||
      content.includes('product package') ||
      content.includes('package selection')
    ) return 'additional';

    // 3b. Explicit document type — checked before the completion override
    // below so restored history (which carries a real documentType, e.g.
    // "commercial"/"moa"/"ejari", reconstructed from stored metadata) keeps
    // its real tab even once the account is near completion. Only the
    // strict type match runs here; the loose content-keyword match stays
    // below, after the override — that one's meant to catch incidental
    // phrase-mentions in freeform text, which is a different problem.
    if (
      type.includes('moa') ||
      type.includes('license') ||
      type.includes('commercial') ||
      type.includes('ejari') ||
      type.includes('tenancy') ||
      type.includes('coi') ||
      type.includes('incorporation') ||
      type.includes('tc_')
    ) return 'corporate';

    // 4. Final Stages (selfDeclTrigger already handled at top — kept for safety)
    if (msg.isSelfDeclConfirmed || msg.onboardingComplete || msg.isCrossValidResult) return 'declaration';

    // 4b. Once onboarding is truly complete, generic/freeform messages belong in
    // Declaration — even if their text happens to mention "corporate", "license",
    // etc. (the LLM's own replies routinely say "your Corporate Single Owner
    // account" in passing). Messages with an explicit document type were
    // already routed above (3b), so this only ever catches messages with no
    // type at all — genuine freeform text, which is what it was meant for.
    // Applies to every ownership type — the check is purely on completion
    // state, not account type.
    if (isOnboardingComplete || isDeclarationEnabled) return 'declaration';

    // 5. Corporate (content-keyword fallback, for messages with no explicit type)
    if (
      content.includes('license') ||
      content.includes('commercial') ||
      content.includes('corporate')
    ) return 'corporate';

    // 6. Keyword Fallbacks
    if (content.includes('self-declaration') || content.includes('summary')) return 'declaration';
    if (content.includes('declaration')) return 'additional';

    // User messages - stay in current tab if keywords match
    if (msg.role === 'user') {
      if (content.includes('identity') || content.includes('passport') || content.includes('eid') ||
        content.includes('pillai') || content.includes('whitmore') || content.includes('mazrouei') ||
        content.includes('rashidi') || content.includes('james') || content.includes('balaji') ||
        content.includes('meera') || content.includes('naida') || content.includes('nadia') ||
        content.includes('faisal') || content.includes('edward') || content.includes('suresh') ||
        content.includes('hamdan') || content.includes('saeed') || content.includes('mario') ||
        content.includes('mascitti') || content.includes('abdullah') || content.includes('satilmis') ||
        content.includes('mavis')) return 'user';
      if (content.includes('fatca') || content.includes('pep') || content.includes('tax')) return 'additional';
      if (content.includes('license') || content.includes('commercial') || content.includes('moa') || content.includes('ejari')) return 'corporate';
    }


    // Final fallback: a generic message with no stage/keyword match (e.g. a
    // freeform Q&A answer typed after onboarding is done) should land wherever
    // the user actually is right now, not always 'corporate'. isOnboardingComplete
    // / isDeclarationEnabled are ground-truth completion flags (same ones
    // getCurrentLiveSection checks first below) — trust them over backendStage,
    // which only reflects document_stage and is never updated by the backend
    // once the account moves past document collection into FATCA/PEP/declaration.
    if (isOnboardingComplete || isDeclarationEnabled) return 'declaration';
    return msg.stage || msg.toStage || backendStage || 'corporate';
  };


  // Determine the current "live" section based on progress
  const getCurrentLiveSection = () => {
    if (isOnboardingComplete) return 'declaration';
    if (isDeclarationEnabled) return 'declaration';

    // ✅ NEW: If no messages yet OR nothing verified yet, always stay on corporate
    if (!messages || messages.length === 0 || totalVerifiedCount === 0) return 'corporate';

    // ✅ GROUND TRUTH PRIORITY: Use backend stage as a baseline, but allow chat to advance faster
    const bStage = (backendStage || '').toLowerCase();
    let currentBestSection = 'corporate';

    // Backend document_stage only ever takes one of 4 values (see
    // stage_table.py): 'identification' and 'corporate_shareholder_docs'
    // both mean corporate-document collection is still in progress —
    // unconditionally, not gated on isCorporateDocsComplete. That flag is
    // computed client-side from requiredDocKeys, a separately-synced list
    // that can lag a beat behind the backend detecting a Type-2 account
    // needs a CoI — during that gap this used to read "corporate docs
    // complete" and advance the live section (and, via the auto-jump
    // effect below, the actual selected tab) to Identity while the chat
    // was still asking for the Certificate of Incorporation. The backend
    // stage itself is definitive: it does not leave corporate_shareholder_docs
    // until every corporate document, CoI included, is actually verified
    // (see member_expansion.check_and_expand_members), so trust it
    // directly instead of re-deriving the same fact from frontend state.
    // 'so_member_eids' / 'member_eids' are exactly the reverse case: the
    // backend has already confirmed corporate docs are done, so identity
    // collection is genuinely live.
    if (['identification', 'corporate_shareholder_docs'].includes(bStage)) {
      currentBestSection = 'corporate';
    } else if (['so_member_eids', 'member_eids', 'identity', 'user'].includes(bStage)) {
      currentBestSection = 'user';
    } else if (['additional', 'compliance', 'fatca', 'pep', 'product_package'].includes(bStage)) {
      currentBestSection = 'additional';
    } else if (['declaration', 'summary', 'self_declaration'].includes(bStage)) {
      currentBestSection = 'declaration';
    }

    // Scan messages to see if the AI has pushed us even further ahead than the backend thinks
    let chatBestSection = 'corporate';
    for (let i = messages.length - 1; i >= 0; i--) {
      const msg = messages[i];
      const section = getMessageSection(msg);
      if (section && section !== 'welcome' && section !== 'unknown') {
        chatBestSection = section;
        break;
      }
    }

    // Use the further of the two stages
    const sectionOrder = { 'welcome': 0, 'corporate': 1, 'user': 2, 'additional': 3, 'declaration': 4 };
    const bRank = sectionOrder[currentBestSection] || 0;
    const cRank = sectionOrder[chatBestSection] || 0;

    let finalSection = bRank >= cRank ? currentBestSection : chatBestSection;

    logger.log('[FLOW] Section Calculation:', {
      backendStage,
      currentBestSection,
      chatBestSection,
      finalSection,
      isCorporateDocsComplete
    });

    // Final Completion Guards — checked against the backend stage directly,
    // not isCorporateDocsComplete. That flag is client-side (built from
    // requiredDocKeys, synced from a separate status call) and can say
    // "complete" a beat before it actually is, e.g. right after a Type-2
    // account is detected but before "coi" has been added to the required
    // list. The backend stage can't make that mistake: it only leaves
    // identification/corporate_shareholder_docs once every corporate
    // document, CoI included, is actually verified.
    //
    // Inverted the same way as the auto-tab-switching effect below: default
    // to "still collecting" for any bStage that isn't a KNOWN post-corporate
    // stage, rather than defaulting to "done" for anything that isn't one of
    // the two known corporate-collection names. Keeps this guard in sync
    // with the auto-jump effect so they can't disagree during the same
    // unknown/placeholder-stage window on initial load.
    const _KNOWN_POST_CORPORATE_STAGES = [
      'so_member_eids', 'member_eids', 'identity', 'user',
      'additional', 'compliance', 'fatca', 'pep', 'product_package',
      'declaration', 'summary', 'self_declaration', 'complete',
    ];
    // 'identification' is ambiguous on the backend: it covers both "still
    // collecting corporate docs" AND "corporate docs done, AS/KI card
    // pending" (see key_individuals.py so-as-selection). Only treat it as
    // post-corporate once a message has actually carried the AS/KI trigger
    // flag — otherwise fall back to the plain whitelist check.
    const _hasAsKiTrigger = messages.some(m => m.asKiTrigger || m.moaAsTrigger);
    const _stillCollectingCorporateDocs = bStage === 'identification'
      ? !_hasAsKiTrigger
      : !_KNOWN_POST_CORPORATE_STAGES.includes(bStage);
    if (finalSection === 'user' && _stillCollectingCorporateDocs) {
      logger.log('[FLOW] Guard: Reverting to corporate — backend stage says corporate docs not complete');
      return 'corporate';
    }
    if (finalSection === 'additional' && _stillCollectingCorporateDocs) {
      logger.log('[FLOW] Guard: Reverting to corporate — backend stage says corporate docs not complete');
      return 'corporate';
    }

    return finalSection;
  };

  const effectiveFilter = activeChatFilter || getCurrentLiveSection();

  const { isAdditionalTab, isCorporateTab, isIdentityTab, isDeclarationTab } = useMemo(() => {
    const filter = (effectiveFilter || '').toLowerCase();
    return {
      isAdditionalTab: filter === 'additional' || filter === 'additional_details' || filter === 'additional details' || filter === 'fatca' || filter === 'pep' || filter === 'product package' || filter === 'product_package',
      isCorporateTab: filter === 'corporate' || filter === 'corporate_details' || filter === 'corporate details' || filter === 'license' || filter === 'moa',
      isIdentityTab: filter === 'user' || filter === 'identity' || filter === 'user_details' || filter === 'user details' || filter === 'identification',
      isDeclarationTab: filter === 'declaration' || filter === 'summary' || filter === 'declaration details'
    };
  }, [effectiveFilter]);

  const processedMessages = useMemo(() => {
    if (!backendSubmittedDocs || backendSubmittedDocs.length === 0) return messages;

    return messages.map(msg => {
      // ✅ HEALING: If extractedData is missing but we have backend ground truth, inject it
      if (msg.role === 'assistant' && msg.documentType && !msg.extractedData) {
        const found = backendSubmittedDocs.find(d => {
          const dType = (d.document_type || d.type || '').toLowerCase();
          const mType = msg.documentType.toLowerCase();

          // Identity matching (Match by member name in message content)
          if (mType.includes('eid') || mType.includes('passport') || mType.includes('identity')) {
            const name = d.member_name || d.name || '';
            return name && msg.content?.toLowerCase().includes(name.toLowerCase());
          }

          // Corporate matching
          return dType.includes(mType) || mType.includes(dType);
        });

        if (found) {
          logger.log(`[HEAL] Restored extractedData for message: ${msg.id} (${msg.documentType})`);
          return {
            ...msg,
            extractedData: found.extracted_fields || found.extracted_data || found.data,
            tamperingStatus: found.is_valid === false ? 'REJECT' : (found.decision || 'ACCEPT'),
            tamperingScore: found.tampering_score
          };
        }
      }
      return msg;
    });
  }, [messages, backendSubmittedDocs]);

  // Index of the "onboarding complete" card. Anything AFTER it is a live
  // conversation the user started once they were already done, and must not be
  // filtered out as declaration noise. -1 when onboarding is not complete.
  const completionIdx = useMemo(
    () => processedMessages.findIndex(
      m => m.id === 'onboarding-complete-final' || m.onboardingComplete
    ),
    [processedMessages]
  );

  const filteredMessages = processedMessages.filter((msg, idx) => {

    // If onboarding is complete AND we are in the Declaration tab,
    // ONLY show the initial Welcome message and the Final Success message.
    if (isOnboardingComplete && isDeclarationTab) {
      if (msg.id === 'onboarding-complete-final' || msg.onboardingComplete) return true;

      // ...but not messages sent AFTER completion. This branch used to return
      // false for everything else, which meant a user typing into the box on
      // the finished Declaration screen saw nothing at all: the message was
      // appended to state and POSTed to the backend, then dropped here before
      // render. It looked like the input was dead.
      //
      // The rule was written to hide the noisy intermediate declaration
      // messages that precede the final card, and for those it is still right
      // — so it now applies only to messages BEFORE that card.
      if (completionIdx !== -1 && idx > completionIdx) return true;

      return false; // Hide intermediate declaration noise (before completion)
    }

    if ((msg.isWelcome || msg.isWelcomeMessage) && isCorporateTab) return true;

    const msgSection = getMessageSection(msg);
    const filter = (effectiveFilter || '').toLowerCase();

    // Normalizing msgSection to check against normalized filter
    if (msgSection === 'additional' && isAdditionalTab) return true;
    if (msgSection === 'corporate' && isCorporateTab) return true;
    if (msgSection === 'user' && isIdentityTab) return true;
    if (msgSection === 'declaration' && isDeclarationTab) return true;

    // User messages should be visible if they immediately follow an assistant message that is visible
    if (msg.role === 'user') {
      const prevMsg = idx > 0 ? processedMessages[idx - 1] : null;

      if (prevMsg) {
        const prevSection = getMessageSection(prevMsg);
        if (prevSection === 'additional' && isAdditionalTab) return true;
        if (prevSection === 'corporate' && isCorporateTab) return true;
        if (prevSection === 'user' && isIdentityTab) return true;
        if (prevSection === 'declaration' && isDeclarationTab) return true;
      }
    }

    if (msg.selfDeclTrigger && isDeclarationTab) return true;

    // Direct match fallback
    return msgSection === filter;
  });

  // ✅ STRICT SORTING LOGIC FOR "ADDITIONAL" SECTION
  // Mandatory order: Welcome (0) -> Intro (0.5) -> FATCA (1) -> PEP (2) -> Package (3)
  const sortedFilteredMessages = useMemo(() => {
    // Apply sorting whenever we are in the "Additional" section (Live or Tab view)
    if (!isAdditionalTab) return filteredMessages;

    let currentTopicIdx = 0.5; // Starts with intro messages
    const prioritized = filteredMessages.map((m, idx) => {
      const type = (m.documentType || m.stage || '').toLowerCase();
      const content = logicText(m);
      let p = -1;

      // Determine the topic priority for this message (Hardcoded Sequence: FATCA -> PEP -> Package)
      if (m.isWelcome || m.isWelcomeMessage) {
        p = 0;
      }
      // 1. Check Card Triggers (highest specificity)
      else if (m.fatcaTrigger || type === 'fatca') p = 1;
      else if (m.pepTrigger || type === 'pep') p = 2;
      else if (m.productPackageTrigger || type === 'product_package') p = 3;
      // 2. Check Confirmation states
      else if (m.isFatcaConfirmed) p = 1;
      else if (m.isPepConfirmed) p = 2;
      else if (m.isProductPackageConfirmed) p = 3;
      // 3. Check keywords in history logs
      else if (content.includes('fatca')) p = 1;
      else if (content.includes('pep')) p = 2;
      else if (content.includes('package')) p = 3;

      // Carry-over priority for follow-up messages within the same section
      if (p !== -1) currentTopicIdx = p;
      else p = currentTopicIdx;

      return { msg: m, p, originalIdx: idx };
    });

    return [...prioritized]
      .sort((a, b) => {
        if (a.p !== b.p) return a.p - b.p;
        return a.originalIdx - b.originalIdx;
      })
      .map(item => item.msg);
  }, [filteredMessages, isAdditionalTab]);

  const hasInitialized = useRef(false);

  // ── Diagnostic: confirm whether repeated request bundles in the docker logs
  // come from this component genuinely re-mounting (e.g. parent re-rendering,
  // route re-entry) vs. separate tabs/page loads, which look identical once
  // merged into one log stream. mountId is generated fresh every time this
  // component instance is created; hasInitialized (above) is also reset on
  // every fresh mount, so if the SAME browser tab shows more than one mountId
  // for what should be a single page view, that confirms a real remount bug
  // here rather than multi-tab/refresh usage. Safe to remove once confirmed.
  const mountIdRef = useRef(Math.random().toString(36).slice(2, 8));
  useEffect(() => {
    logger.log(`[INIT-DIAG] AIAssistant mounted — mountId=${mountIdRef.current} at ${new Date().toISOString()}`);
    return () => {
      logger.log(`[INIT-DIAG] AIAssistant unmounted — mountId=${mountIdRef.current}`);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const fetchGroundTruth = useCallback(async () => {
    if (!user?.email) return;
    try {
      const statusRes = await getDocumentStatus(user.email);

      logger.log('[BACKEND-DEBUG] /document-status/ response:', statusRes.data);

      if (statusRes.data?.members_info) {
        setMembersInfo(statusRes.data.members_info);
        if (statusRes.data.members_info.member_role_map) {
          setPersistentRoleMap(prev => ({
            ...prev,
            ...statusRes.data.members_info.member_role_map
          }));
        }
      } else if (statusRes.data?.member_eid_counts) {
        // Fallback: If members_info is null but counts exist, 
        // we should at least update the counts if we have a partial membersInfo
        setMembersInfo(prev => ({ ...(prev || {}), ...statusRes.data.member_eid_counts }));
      }

      if (statusRes.data?.stage || statusRes.data?.document_stage) {
        const newStage = statusRes.data.stage || statusRes.data.document_stage;
        logger.log('[GROUND_TRUTH] Backend Stage:', newStage);
        setBackendStage(newStage);
      }

      const docs = Array.isArray(statusRes.data) ? statusRes.data : (statusRes.data?.documents || []);
      logger.log('[DEBUG-SYNC] Ground Truth MembersInfo:', statusRes.data?.members_info);
      logger.log('[DEBUG-SYNC] Ground Truth Docs Count:', docs.length);
      if (docs.length > 0) {
        logger.log('[GROUND_TRUTH] Documents Sync:', docs.length, 'files');
        logger.log('[GROUND_TRUTH-DEBUG] First Doc Sample:', JSON.stringify(docs[0]).substring(0, 200));
        setBackendSubmittedDocs(docs);
      }


      // ✅ SYNC REQUIRED KEYS: Prioritize the list from the status API if available
      const statusRequiredKeys = statusRes.data?.required_document_types || statusRes.data?.status_details?.required_documents || [];

      if (statusRequiredKeys.length > 0) {
        logger.log('[REQUIREMENTS] Syncing from Status API:', statusRequiredKeys);
        setRequiredDocKeys(prev => {
          const nextArr = [...statusRequiredKeys].sort();
          const currentArr = [...prev].sort();
          if (JSON.stringify(nextArr) === JSON.stringify(currentArr)) return prev;
          return nextArr;
        });
      }
    } catch (e) {
      logger.warn('[GROUND_TRUTH] Failed to fetch member status:', e);
    }
  }, [user?.email]);

  useEffect(() => {
    fetchGroundTruth();
  }, [fetchGroundTruth, messages]);

  // ✅ UNIFIED AUTO-TAB SWITCHING
  useEffect(() => {
    const liveSection = getCurrentLiveSection();
    if (isLoading) return;

    // Ground truth for "is corporate document collection actually finished":
    // the backend document_stage, not isCorporateDocsComplete. That flag is
    // built from requiredDocKeys, a separately-synced list that can lag
    // behind the backend detecting a Type-2 account needs a CoI — during
    // that gap it used to read "complete" with Commercial/MOA/Ejari all
    // green and CoI simply not in the checklist yet, which auto-jumped the
    // active tab to Identity while the chat was still asking for the CoI.
    // document_stage can't make that mistake: it only leaves identification
    // /corporate_shareholder_docs once every corporate document is verified
    // (see member_expansion.check_and_expand_members on the backend).
    //
    // ✅ FIX: this used to be a POSITIVE check — "is bStage one of the two
    // known corporate-collection names" — which defaults to FALSE (= "docs
    // are done") whenever backendStage hasn't loaded yet. On mount, before
    // the async status call resolves, backendStage sits at its placeholder
    // default ('corporate'), which isn't literally 'identification' or
    // 'corporate_shareholder_docs' either — so the old check read that as
    // "corporate is done" and force-jumped straight to Identity on a blank,
    // freshly-logged-in page (0/1 verified everywhere). Inverted to a
    // NEGATIVE check against the stages that are definitely PAST corporate
    // collection — unknown/placeholder values now default to "still
    // collecting", which is the safe assumption, instead of "already done".
    const _KNOWN_POST_CORPORATE_STAGES = [
      'so_member_eids', 'member_eids', 'identity', 'user',
      'additional', 'compliance', 'fatca', 'pep', 'product_package',
      'declaration', 'summary', 'self_declaration', 'complete',
    ];
    // 'identification' is ambiguous on the backend: it covers both "still
    // collecting corporate docs" AND "corporate docs done, AS/KI card
    // pending" (see key_individuals.py so-as-selection). Only treat it as
    // post-corporate once a message has actually carried the AS/KI trigger
    // flag — otherwise fall back to the plain whitelist check.
    const _bStageForCorporateCheck = (backendStage || '').toLowerCase();
    const _hasAsKiTrigger = messages.some(m => m.asKiTrigger || m.moaAsTrigger);
    const _stillCollectingCorporateDocs = _bStageForCorporateCheck === 'identification'
      ? !_hasAsKiTrigger
      : !_KNOWN_POST_CORPORATE_STAGES.includes(_bStageForCorporateCheck);

    // ⚡️ AUTO-JUMP CORPORATE -> IDENTITY
    // Trigger automatically if the section is complete and we are currently following the live flow
    if (activeChatFilter === null && liveSection === 'corporate' && !_stillCollectingCorporateDocs) {
      logger.log('[FLOW] Corporate complete (backend-confirmed). Auto-advancing to Identity tab.');
      setActiveChatFilter('user');
      lastLiveSectionRef.current = 'user';
      return;
    }

    // ⚡️ JUMP IDENTITY -> ADDITIONAL
    // If identity is done (1/1) and we are currently on identity, move to additional
    const isIdentityVerified = (membersInfo && membersInfo.verified >= membersInfo.total && membersInfo.total > 0) ||
      (backendStage === 'additional' || backendStage === 'compliance');

    // We only auto-jump if the user is currently "following" (activeChatFilter is null)
    // Manual navigation is handled by the "Standard follow logic" below which only triggers once.
    if (activeChatFilter === null && (liveSection === 'additional' || backendStage === 'additional') && isIdentityVerified && !_stillCollectingCorporateDocs) {
      logger.log('[FLOW] Identity complete. Advancing to Additional tab.');
      setActiveChatFilter('additional');
      lastLiveSectionRef.current = 'additional';
      return;
    }

    // Standard follow logic (ONLY JUMP FORWARD)
    if (lastLiveSectionRef.current && liveSection !== lastLiveSectionRef.current) {
      const sectionOrder = { 'welcome': 0, 'corporate': 1, 'user': 2, 'additional': 3, 'declaration': 4 };
      const currentRank = sectionOrder[liveSection] || 0;
      const prevRank = sectionOrder[lastLiveSectionRef.current] || 0;

      // Only auto-switch if we are moving FORWARD in the process
      if (currentRank > prevRank) {
        // ✅ NEW: Only reset filter if the user is currently "following" (activeChatFilter is null)
        // OR if they are currently looking at the section that just finished.
        const userIsLookingAtOldSection = activeChatFilter === lastLiveSectionRef.current;
        const userIsFollowing = activeChatFilter === null;

        if (userIsFollowing || userIsLookingAtOldSection) {
          logger.log(`[FLOW] Advancing: ${lastLiveSectionRef.current} -> ${liveSection}. Resetting filter.`);
          setActiveChatFilter(null);
        } else {
          logger.log(`[FLOW] Advanced to ${liveSection}, but keeping user's manual filter: ${activeChatFilter}`);
        }
      } else {
        logger.log(`[FLOW] Suppressing backward jump: ${lastLiveSectionRef.current} -> ${liveSection}`);
      }
    }

    lastLiveSectionRef.current = liveSection;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages, isCorporateDocsComplete, activeChatFilter, isOnboardingComplete, isDeclarationEnabled, isLoading, membersInfo, backendStage]);

  // ⚡️ CATCH-UP POLL: Corporate -> Identity auto-jump above is gated on
  // backendStage (the DB's document_stage field) having already flipped to
  // so_member_eids/member_eids. That write only happens after a separate
  // backend expansion step runs post-verification, which can lag a beat
  // behind the frontend's own "all required corporate docs approved"
  // detection (isCorporateDocsComplete). backendStage is normally only
  // re-fetched when a new chat message arrives (see fetchGroundTruth's
  // effect above) — so if the user's last action WAS the final corporate
  // document, nothing re-triggers that fetch and the gate can stay shut
  // indefinitely, leaving the tab stuck on Corporate until the user clicks
  // Identity manually. Poll ground truth for a short window whenever the
  // frontend thinks corporate is done but the gate hasn't opened yet, so
  // the existing (safe) auto-jump still fires on its own once the backend
  // catches up, instead of requiring a manual click.
  useEffect(() => {
    const bStage = (backendStage || '').toLowerCase();
    const _KNOWN_POST_CORPORATE_STAGES = [
      'so_member_eids', 'member_eids', 'identity', 'user',
      'additional', 'compliance', 'fatca', 'pep', 'product_package',
      'declaration', 'summary', 'self_declaration', 'complete',
    ];
    // 'identification' is ambiguous on the backend: it covers both "still
    // collecting corporate docs" AND "corporate docs done, AS/KI card
    // pending" (see key_individuals.py so-as-selection). Only treat it as
    // post-corporate once a message has actually carried the AS/KI trigger
    // flag — otherwise fall back to the plain whitelist check.
    const _hasAsKiTrigger = messages.some(m => m.asKiTrigger || m.moaAsTrigger);
    const _stillCollectingCorporateDocs = bStage === 'identification'
      ? !_hasAsKiTrigger
      : !_KNOWN_POST_CORPORATE_STAGES.includes(bStage);
    const waitingOnBackend = activeChatFilter === null &&
      isCorporateDocsComplete &&
      _stillCollectingCorporateDocs;

    if (!waitingOnBackend) return undefined;

    let attempts = 0;
    const id = setInterval(() => {
      attempts += 1;
      fetchGroundTruth();
      if (attempts >= 10) clearInterval(id); // give up after ~20s
    }, 2000);

    return () => clearInterval(id);
  }, [isCorporateDocsComplete, backendStage, activeChatFilter, fetchGroundTruth, messages]);



  const handleOnboardingComplete = useCallback(() => {
    // 🛡️ GUARD: Do NOT fire final "Success" message if members are still pending verification
    // OR if the product package selection is not yet complete.
    const isIdentityVerified = membersInfo && membersInfo.verified >= membersInfo.total;
    const isPackageFinalized = !!productPackageData;

    if (!isIdentityVerified || !isPackageFinalized) {
      logger.log('[COMPLETE] Suppressed: Verification or package pending', { isIdentityVerified, isPackageFinalized });
      return;
    }

    // Check if state is already complete, just make sure we aren't appending duplicates
    setIsOnboardingComplete(true);

    const currentRef = finalRefNumber || sessionStorage.getItem('final_ref_number');

    const completionMsg = {
      id: 'onboarding-complete-final', // Use a stable ID to help preventing duplicates
      role: 'assistant',
      content: t('chat.submittedWithRef', { ref: currentRef || 'XXXX' }),
      type: 'text',
      timestamp: new Date().toISOString(),
      isSuccess: true,
      onboardingComplete: true
    };

    setMessages(prev => {
      const existingIdx = prev.findIndex(m => m.onboardingComplete || m.id === 'onboarding-complete-final');
      if (existingIdx !== -1) {
        // Update existing message if reference number changed
        if (prev[existingIdx].content !== completionMsg.content) {
          const updated = [...prev];
          updated[existingIdx] = completionMsg;
          return updated;
        }
        return prev;
      }
      return [...prev, completionMsg];
    });
    setActiveChatFilter(null);
  }, [membersInfo, productPackageData, finalRefNumber]);

  // Fetch Compliance States (FATCA/PEP/Self-Declaration/Product Package)
  useEffect(() => {
    if (user?.email) {
      // Fetch FATCA
      getFatcaStatus(user.email)
        .then(res => {
          if (res.data?.status === 'completed' && res.data.data) {
            setFatcaData(res.data.data);
          }
        })
        .catch(() => { });

      // Fetch PEP
      getPepStatus(user.email)
        .then(res => {
          if (res.data?.status === 'completed' && res.data.data) {
            setPepData(res.data.data);
          }
        })
        .catch(() => { });

      // Fetch Self-Declaration status
      getSelfDeclarationStatus(user.email)
        .then(res => {
          if (res.data?.confirmed) {
            setIsOnboardingComplete(true);
            setIsDeclarationEnabled(true);
            const ref = res.data.reference_number;
            if (ref) setFinalRefNumber(ref);
          }
        })
        .catch(() => { });

      // Fetch Product Package
      getPackageStatus(user.email)
        .then(res => {
          if (res.data?.status === 'completed' && res.data.selected_package) {
            setProductPackageData(res.data);
          }
        })
        .catch(() => { });
    }
  }, [user?.email]);

  const isFinalDeclarationStep = (effectiveFilter === 'declaration');

  // Auto-scroll sidebar to bottom when declaration is shown
  useEffect(() => {
    if ((isDeclarationEnabled || activeChatFilter === 'declaration') && activeDocData?.documentType === 'summary_declaration' && sidebarScrollRef.current) {
      setTimeout(() => {
        if (sidebarScrollRef.current) {
          sidebarScrollRef.current.scrollTo({
            top: sidebarScrollRef.current.scrollHeight,
            behavior: 'smooth'
          });
        }
      }, 800);
    }
  }, [activeDocData, isDeclarationEnabled, activeChatFilter]);

  useEffect(() => {
    if (finalRefNumber) {
      sessionStorage.setItem('final_ref_number', finalRefNumber);
    }
  }, [finalRefNumber]);

  useEffect(() => {
    if (effectiveFilter === 'declaration' && !sidebarDismissed && (!activeDocData || activeDocData.documentType !== 'summary_declaration')) {
      setActiveDocData({ isVirtual: true, documentType: 'summary_declaration', name: 'Summary Declaration' });
      setSidebarMode('data');
    }
    // If we switch away from declaration tab, reset dismissal
    if (effectiveFilter !== 'declaration' && sidebarDismissed) {
      setSidebarDismissed(false);
    }
  }, [effectiveFilter, activeDocData, sidebarDismissed]);

  // Automatically enable declaration when pre-declaration steps are complete.
  // FATCA+PEP are always confirmed before the product package step for every
  // ownership type, so by the time productPackageData is set, all prerequisites
  // are already done.
  // We avoid checking ownership_type because it may be stale/empty ("") in localStorage
  // for users who logged in before that field was populated in the DB.
  useEffect(() => {
    const prereqsMet = !!productPackageData;
    if (!isDeclarationEnabled && !isOnboardingComplete && prereqsMet) {
      logger.log('[FLOW] Auto-enabling Self Declaration phase (productPackage confirmed)');
      setIsDeclarationEnabled(true);
      setActiveChatFilter('declaration');
      // Automatically open sidebar for declaration
      setActiveDocData({ isVirtual: true, documentType: 'summary_declaration', name: 'Summary Declaration' });
      setSidebarMode('data');
    }
  }, [productPackageData, isDeclarationEnabled, isOnboardingComplete]);

  // Handle final completion state logic
  useEffect(() => {
    if (isOnboardingComplete) {
      handleOnboardingComplete();
    }
  }, [isOnboardingComplete, handleOnboardingComplete]);

  // ── v4: Mismatch modal state ─────────────────────────────────────────────
  //
  // B8: four useState calls collapsed into one object.
  //
  // They were never independent — opening the modal set three of them in a row
  // and closing it set two. Four separate slots for one modal's state meant the
  // open path issued three sequential updates, and nothing in the type system
  // or the code stopped a future edit from setting the name without opening the
  // modal, or opening it with a stale name still in place. One object makes the
  // invalid combinations unrepresentable and the open path a single update.
  //
  // Chosen over useReducer deliberately: there are two transitions, open and
  // close. A reducer with two actions would be more ceremony than the thing it
  // models.
  const [mismatch, setMismatch] = useState({
    open: false,
    extractedName: null,
    extractedBiz: null,
    roleConfirmed: false,
  });

  // PERSIST LANGUAGE SELECTION TO LOCALSTORAGE
  // ── Pending-action sync ───────────────────────────────────────────────────
  // Extracted from the ~1,160-line init effect, whose dependency array is
  // [user?.email, selectedLanguage] — so it ran ONCE at login and never again.
  // Every backend action after that (upload, ownership save, KI selection,
  // package save, declaration submit) changes these ground-truth flags, and the
  // UI never re-read them. That is why cards only appeared after a manual
  // refresh: refreshing remounts the component and re-runs the effect.
  //
  // Safe to call repeatedly: every back-fill below already guards with
  // `if (prev.some(m => m.xTrigger)) return prev`, so re-running inserts
  // nothing twice. That idempotency is what makes this extraction possible
  // without redesigning the trigger model.
  // Returns true once the backend has surfaced a pending action (or a completed
  // compliance step) — see the return at the bottom. The polling effect below
  // stops on that signal, so every exit path must return a boolean.
  const syncPendingActions = useCallback(async () => {
    if (!user?.email) return false;
    try {
      const [fatcaRes, pepRes, pkgRes, pendingRes] = await Promise.allSettled([
        getFatcaStatus(user.email),
        getPepStatus(user.email),
        getPackageStatus(user.email),
        getOnboardingStatus(user.email)
      ]);

      const fatcaData_ = fatcaRes.status === 'fulfilled' ? fatcaRes.value.data : null;
      const pepData_ = pepRes.status === 'fulfilled' ? pepRes.value.data : null;
      const pkgData_ = pkgRes.status === 'fulfilled' ? pkgRes.value.data : null;
      // ✅ Ground-truth pending-action flags (see backend get_onboarding_status()).
      // These are recomputed from persisted disk state on every load/refresh —
      // unlike asKiTrigger/productPackageTrigger on a chat message, they can't be
      // lost to a page refresh or a document-upload timeout, so we use them here
      // to force the AS/KI card and Product Package card back onto the screen
      // whenever the underlying action still hasn't been completed.
      const pendingData_ = pendingRes.status === 'fulfilled' ? pendingRes.value.data : null;

      const hasFatca = fatcaData_?.status === 'completed' || fatcaData_?.status === 'success';
      const hasPep = pepData_?.status === 'completed' || pepData_?.status === 'success';
      const hasPkg = pkgData_?.status === 'completed' || pkgData_?.status === 'success' || !!pkgData_?.selected_package;

      if (hasFatca) setFatcaData(fatcaData_?.data || { status: 'completed' });
      if (hasPep) setPepData(pepData_?.data || { status: 'completed' });
      if (hasPkg) setProductPackageData(pkgData_);

      // Re-backfill triggers into messages so users see their 'Secured' status/edit buttons
      // only if they weren't already captured in message metadata.
      if (hasFatca || hasPep || hasPkg) {
        setMessages(prev => {
          if (prev.length === 0) return prev;
          const newMsgs = [...prev];
          const fatcaFound = newMsgs.some(m => m.fatcaTrigger);
          const pepFound = newMsgs.some(m => m.pepTrigger);
          const pkgFound = newMsgs.some(m => m.productPackageTrigger || m.product_package_trigger);

          // Find the best assistant message to host these buttons if they are missing
          // Now including messages that might have nextDocument set (e.g. success messages)
          let targetIdx = newMsgs.findLastIndex(m => m.role === 'assistant' && (getMessageSection(m) === 'additional' || m.stage === 'fatca' || m.stage === 'pep' || m.stage === 'product_package'));

          // Fallback to any assistant message if no specific compliance intro found
          if (targetIdx === -1) {
            targetIdx = newMsgs.findLastIndex(m => m.role === 'assistant');
          }

          if (targetIdx !== -1) {
            if (hasFatca && !fatcaFound) newMsgs[targetIdx].fatcaTrigger = true;
            if (hasPep && !pepFound) newMsgs[targetIdx].pepTrigger = true;
            if (hasPkg && !pkgFound) newMsgs[targetIdx].productPackageTrigger = true;
          } else if (newMsgs.length > 0) {
            // Fallback to latest message
            const lastIdx = newMsgs.length - 1;
            if (hasFatca && !fatcaFound) newMsgs[lastIdx].fatcaTrigger = true;
            if (hasPep && !pepFound) newMsgs[lastIdx].pepTrigger = true;
            if (hasPkg && !pkgFound) newMsgs[lastIdx].productPackageTrigger = true;
          }
          return newMsgs;
        });
      }

      // ── Ground-truth back-fill: AS/KI role card & Product Package card ──
      // Unlike the block above (which mirrors a trigger already found in the
      // response of a specific request), these two flags come from disk state
      // recomputed on every load, so they cover the case where the triggering
      // message was NEVER received at all (upload timed out) or was received
      // but never persisted to chat history metadata. If the flag says the
      // step is still outstanding, force the card onto the screen — if it
      // was already inserted from history/metadata, skip to avoid duplicates.

      // ── OwnershipTypeCard (fallback only) ──────────────────────────────
      // Ownership Type is no longer asked upfront — the AI infers it
      // automatically from the Commercial License's extracted partner
      // list as soon as it's verified (backend auto-classification).
      // This card now only appears as a FALLBACK, when that couldn't be
      // determined confidently — gated by the backend's
      // ownership_selection_pending flag (true only while an
      // ownership_ambiguous.json breadcrumb exists, i.e. after the
      // Commercial License was uploaded but couldn't be classified).
      if (pendingData_?.ownership_selection_pending) {
        setMessages(prev => {
          if (prev.length === 0) return prev;
          if (prev.some(m => m.ownershipTypeTrigger)) return prev;

          const newMsgs = [...prev];
          const targetIdx = newMsgs.findLastIndex(m => m.role === 'assistant');
          if (targetIdx === -1) return prev;

          newMsgs[targetIdx] = { ...newMsgs[targetIdx], ownershipTypeTrigger: true };
          logger.log('[INIT] Restored pending OwnershipTypeCard from ground-truth status');
          return newMsgs;
        });
      }

      if (pendingData_?.as_ki_selection_pending) {
        setMessages(prev => {
          if (prev.length === 0) return prev;
          const alreadyShown = prev.some(m => m.asKiTrigger || m.moaAsTrigger);
          if (alreadyShown) return prev;

          const newMsgs = [...prev];
          const targetIdx = newMsgs.findLastIndex(m => m.role === 'assistant');
          if (targetIdx === -1) return prev;

          const source = pendingData_.as_ki_pending_source;
          const members = pendingData_.as_ki_pending_members || [];
          const patch = { ...newMsgs[targetIdx] };

          if (source === 'SO_OWNER') {
            patch.asKiTrigger = true;
            patch.soOwner = members[0] || null;
          } else {
            patch.moaAsTrigger = true;
            patch.moaMembers = members;
            // Ground-truth UBO/share data — was previously only ever set from
            // a live single-file response's response.data.ubo_names, so any
            // restore through this path (page reload, or bulk upload, which
            // never returns those trigger fields) rendered the AS/KI card
            // with every member's UBO badge missing even when the backend
            // had correctly computed it and saved it to member_progress.json.
            patch.uboNames = pendingData_.as_ki_pending_ubo_names || [];
            if (pendingData_.as_ki_pending_ownership_map) {
              patch.ownershipMap = {
                ...(patch.ownershipMap || {}),
                ...pendingData_.as_ki_pending_ownership_map,
              };
            }
          }
          newMsgs[targetIdx] = patch;
          logger.log('[INIT] Restored pending AS/KI role card from ground-truth status:', source, members);
          return newMsgs;
        });
      }

      if (pendingData_?.product_package_pending && !hasPkg) {
        setMessages(prev => {
          if (prev.length === 0) return prev;
          if (prev.some(m => m.productPackageTrigger || m.product_package_trigger)) return prev;

          const newMsgs = [...prev];
          const targetIdx = newMsgs.findLastIndex(m => m.role === 'assistant');
          if (targetIdx === -1) return prev;

          newMsgs[targetIdx] = { ...newMsgs[targetIdx], productPackageTrigger: true };
          logger.log('[INIT] Restored pending Product Package card from ground-truth status');
          return newMsgs;
        });
      }

      // ── KiLoopCard ("Add another AS/KI?") ────────────────────────────
      // Same ground-truth pattern: pending once every currently-known
      // member is verified but ki_loop_done.json hasn't been written.
      if (pendingData_?.ki_loop_prompt_pending) {
        setMessages(prev => {
          if (prev.length === 0) return prev;
          if (prev.some(m => m.kiLoopPrompt || m.ki_loop_prompt)) return prev;

          const newMsgs = [...prev];
          const targetIdx = newMsgs.findLastIndex(m => m.role === 'assistant');
          if (targetIdx === -1) return prev;

          newMsgs[targetIdx] = { ...newMsgs[targetIdx], kiLoopPrompt: true };
          logger.log('[INIT] Restored pending KiLoopCard from ground-truth status');
          return newMsgs;
        });
      }

      // ── KiRoleAssignCard (assign AS/Member to a newly-added individual) ──
      // Pending if an EID/Passport was captured via "Yes, add another" but
      // no role has been saved for it yet (backend breadcrumb-driven).
      if (pendingData_?.ki_role_assignment_pending && pendingData_?.ki_role_assignment_data) {
        setMessages(prev => {
          if (prev.length === 0) return prev;
          if (prev.some(m => m.isAiKiEidCapture && !m.aiKiCaptured)) return prev;

          const newMsgs = [...prev];
          const targetIdx = newMsgs.findLastIndex(m => m.role === 'assistant');
          if (targetIdx === -1) return prev;

          const rd = pendingData_.ki_role_assignment_data;
          newMsgs[targetIdx] = {
            ...newMsgs[targetIdx],
            isAiKiEidCapture: true,
            aiKiExtractedData: rd.extracted_fields || {},
            aiKiDocumentId: rd.document_id,
            aiKiCaptured: false,
          };
          logger.log('[INIT] Restored pending KiRoleAssignCard from ground-truth status');
          return newMsgs;
        });
      }

      // ── KiDetailsCard (contact info for a newly-added individual) ────────
      // Pending if a KI with source=AI_ADDED exists but has no phone_number
      // saved yet (role already assigned, contact info step not done).
      if (pendingData_?.ki_details_pending && pendingData_?.ki_details_pending_data) {
        setMessages(prev => {
          if (prev.length === 0) return prev;
          if (prev.some(m => m.kiDetailsTrigger && !m.kiDetailsCaptured)) return prev;

          const newMsgs = [...prev];
          const targetIdx = newMsgs.findLastIndex(m => m.role === 'assistant');
          if (targetIdx === -1) return prev;

          const dd = pendingData_.ki_details_pending_data;
          newMsgs[targetIdx] = {
            ...newMsgs[targetIdx],
            kiDetailsTrigger: true,
            kiDetailsName: dd.ki_name,
            kiDetailsRole: dd.role,
            kiDetailsCaptured: false,
          };
          logger.log('[INIT] Restored pending KiDetailsCard from ground-truth status');
          return newMsgs;
        });
      }

      // ── Deferred Mismatch Modal ────────────────────────────────────────
      // A Commercial License name/business mismatch is recorded by the
      // backend as soon as it's detected, but only surfaces here — right
      // before member verification (Ejari/MOA verified) — instead of
      // interrupting the flow immediately after upload. Ground-truth
      // driven so it also survives refresh until actually answered.
      if (pendingData_?.mismatch_role_pending && pendingData_?.mismatch_role_data && !mismatch.roleConfirmed) {
        const md = pendingData_.mismatch_role_data;
        if (md.extracted_name || md.extracted_business) {
          // One update, not three. The modal cannot now be shown with a name
          // from a previous document still in state.
          setMismatch(m => ({
            ...m,
            extractedName: md.extracted_name || null,
            extractedBiz: md.extracted_business || null,
            open: true,
          }));
          logger.log('[INIT] Restored pending mismatch role modal from ground-truth status');
        }
      }

      // CHECK FOR ONBOARDING COMPLETION
      const selfDeclRes = await getSelfDeclarationStatus(user.email);
      if (selfDeclRes.data?.confirmed) {
        // Also back-fill self-declaration trigger if not found
        setMessages(prev => {
          if (prev.some(m => m.selfDeclTrigger)) return prev;
          const newMsgs = [...prev];
          if (newMsgs.length > 0) {
            newMsgs[newMsgs.length - 1].selfDeclTrigger = true;
          }
          return newMsgs;
        });
        handleOnboardingComplete();
      } else if (hasPkg || pendingData_?.self_declaration_pending) {
        // Product Package done but Self-Declaration not yet confirmed.
        // Inject selfDeclTrigger so the SelfDeclarationCard renders on reload.
        // hasPkg (from /product-package/status) already made this ground-truth
        // rather than trigger-based; self_declaration_pending is an additional
        // single-source-of-truth check (same underlying condition, computed
        // once in get_onboarding_status) kept as a safety net.
        setMessages(prev => {
          if (prev.length === 0 || prev.some(m => m.selfDeclTrigger)) return prev;
          const newMsgs = [...prev];
          // Find the last assistant message to attach the trigger to
          const lastAssistantIdx = newMsgs.findLastIndex(m => m.role === 'assistant');
          if (lastAssistantIdx !== -1) {
            newMsgs[lastAssistantIdx] = { ...newMsgs[lastAssistantIdx], selfDeclTrigger: true };
          } else {
            newMsgs[newMsgs.length - 1] = { ...newMsgs[newMsgs.length - 1], selfDeclTrigger: true };
          }
          return newMsgs;
        });
      }

      // B8: report whether the backend has surfaced anything to act on yet.
      //
      // The polling effect uses this to decide when to stop. It is computed
      // from the RESPONSES, not from whether a setMessages updater mutated
      // anything — those updaters run later, and reading a side effect out of
      // a state updater would be both a React anti-pattern and wrong under
      // StrictMode's double invocation.
      //
      // The question this answers is "has the backend finished the work that
      // sets the next flag?", which is exactly the 39-second window that made
      // the FATCA card need a manual refresh.
      return Boolean(
        hasFatca ||
        hasPep ||
        hasPkg ||
        selfDeclRes.data?.confirmed ||
        pendingData_?.ownership_selection_pending ||
        pendingData_?.as_ki_selection_pending ||
        pendingData_?.product_package_pending ||
        pendingData_?.ki_loop_prompt_pending ||
        pendingData_?.ki_role_assignment_pending ||
        pendingData_?.ki_details_pending ||
        pendingData_?.mismatch_role_pending ||
        pendingData_?.self_declaration_pending
      );
    } catch (e) {
      logger.error('[INIT] Failed to restore compliance state', e);
      // Not "nothing pending" — "we do not know". Returning false keeps the
      // poll alive so a transient network failure does not end it early.
      return false;
    }
    // B8 — `mismatch.roleConfirmed` added to the dependency array, and this is
    // a real behaviour change rather than a tidy.
    //
    // The array was `[user?.email]`, so the `!mismatchRoleConfirmed` guard
    // above closed over the value from the render that created this callback:
    // always `false`. The guard exists to stop the mismatch modal reappearing
    // after the user has answered it, and it could not do that — if the
    // backend still reported `mismatch_role_pending`, a later sync would
    // reopen the modal on a question already answered.
    //
    // Depending on the boolean (not the object) keeps the identity stable
    // except when the answer actually changes, so this does not re-trigger the
    // polling effect on every render.
  }, [user?.email, mismatch.roleConfirmed]);

  // (preferredLanguage persistence now lives in LanguageContext.setLanguage)

  // ── Phase 2 (docs/language-mirroring-verdict.html): re-translate history
  // on an actual toggle switch ─────────────────────────────────────────────
  // Phase 0/1 only cover messages from this point forward (the user's next
  // send, and every new AI reply); this is what makes switching mid-
  // conversation flip everything already on screen too. Guarded so it never
  // fires on mount or before the initial history has loaded — only on a
  // real change to globalLanguage after that.
  //
  // Re-fetches conversation-logs with `?language=` and rebuilds `messages`
  // via transformLogToMessage() — the same function initializeChat() uses to
  // build the message list on resume/reload — rather than patching messages
  // in place, since that function already reconstructs every card/trigger
  // flag from each row's metadata and this keeps both paths in sync by
  // construction.
  //
  // BUGFIX (previously: "left untouched here"): the rebuilt array was
  // originally swapped in as-is, leaving currentStepId/validatedDocs/
  // isOnboardingComplete pointing at the discarded pre-switch message
  // objects, and dropping each message's UI-only completion flags
  // (asSelectionCompleted, kiLoopCompleted, kiLoopChoice, aiKiCaptured,
  // isFatcaConfirmed). That was the root cause of "KI cards break after
  // switching language mid-flow, including back in English" — the flow
  // wasn't actually broken, it was reading stale/incomplete state pointed
  // at message objects that no longer existed. Both are now carried
  // forward / re-derived below, by id, using the same rule initializeChat()
  // uses on first load.
  const previousGlobalLanguageRef = useRef(globalLanguage);
  // A request that was already in flight when the user switched language
  // (uploads take 20–40 s) answers in the language it was SENT in. The api
  // client flags that (event 'i18n:stale-response', see api/client.js); we
  // then re-run this same history re-sync once so the late reply is shown in
  // the current language too (catalog rows swap instantly).
  const [staleResyncNonce, setStaleResyncNonce] = useState(0);
  const lastStaleNonceRef = useRef(0);
  useEffect(() => {
    let timer = null;
    const onStale = () => {
      clearTimeout(timer);
      // debounce: a bulk upload can finish several calls back to back
      timer = setTimeout(() => setStaleResyncNonce((x) => x + 1), 600);
    };
    window.addEventListener('i18n:stale-response', onStale);
    return () => { clearTimeout(timer); window.removeEventListener('i18n:stale-response', onStale); };
  }, []);
  useEffect(() => {
    const previousLanguage = previousGlobalLanguageRef.current;
    previousGlobalLanguageRef.current = globalLanguage;
    const staleResync = staleResyncNonce !== lastStaleNonceRef.current;
    lastStaleNonceRef.current = staleResyncNonce;

    if (previousLanguage === globalLanguage && !staleResync) return; // mount, not a real switch
    if (!hasInitialized.current || !user?.email) return; // history not loaded yet
    if (messages.length === 0) return; // nothing to re-translate

    let cancelled = false;

    (async () => {
      setIsTranslatingHistory(true);
      try {
        logger.log('[LANGUAGE] History switch:', previousLanguage, '->', globalLanguage);
        const historyResp = await getConversationLogs(user.email, {
          limit: 100,
          channel: 'chat',
          language: globalLanguage,
        }, { skipAuthRedirect: true });
        if (cancelled) return;

        const logs = historyResp.data?.logs || [];
        if (logs.length > 0) {
          const rebuilt = logs.slice().reverse().map(log => transformLogToMessage(log));

          // BUGFIX (language-switch state desync): transformLogToMessage()
          // rebuilds each message fresh from its raw stored log/metadata —
          // it does not know about the UI-only completion flags
          // (asSelectionCompleted, kiLoopCompleted, kiLoopChoice,
          // aiKiCaptured, isFatcaConfirmed) that initializeChat's healing
          // pass or later interactions attached to the *previous* message
          // objects by id. Dropping them here is what made the KI/AS/FATCA
          // cards re-render as if incomplete right after a language switch,
          // even though nothing about onboarding progress actually changed —
          // only the display language did. Carry them forward by id.
          const prevById = new Map(messages.map(m => [m.id, m]));
          const mergedById = rebuilt.map((m) => {
            const prev = prevById.get(m.id);
            if (!prev) return m;
            return {
              ...m,
              // `||`: never let a missing in-memory flag erase one the rebuilt
              // message already restored from its stored metadata.
              asSelectionCompleted: prev.asSelectionCompleted || m.asSelectionCompleted,
              kiLoopCompleted: prev.kiLoopCompleted || m.kiLoopCompleted,
              kiLoopChoice: prev.kiLoopChoice || m.kiLoopChoice,
              aiKiCaptured: prev.aiKiCaptured || m.aiKiCaptured,
              isFatcaConfirmed: prev.isFatcaConfirmed || m.isFatcaConfirmed,
            };
          });
          // Id-merge alone misses cards completed moments ago: those were
          // live messages with client-side ids that never match their stored
          // rows. deriveCardState re-derives completion from the history.
          const merged = deriveCardState(mergedById);

          setMessages(merged);

          // Re-derive progression state from the merged (correctly-flagged)
          // messages, using the exact same rule initializeChat() uses on
          // first load (see RESTORE ONBOARDING PROGRESSION STATE above).
          // Without this, currentStepId/isOnboardingComplete/validatedDocs
          // kept pointing at the pre-switch message objects this effect just
          // replaced — the active card stopped matching currentStepId and
          // the flow silently froze on the current step until a full reload.
          const lastProgressionId = [...merged]
            .reverse()
            .find(m => m.nextDocument || m.remainingDocuments || m.onboardingComplete)?.id;
          if (lastProgressionId) {
            setCurrentStepId(lastProgressionId);
          }
          if (merged.length > 0 && merged[merged.length - 1].onboardingComplete) {
            setIsOnboardingComplete(true);
          }
          const historicalValidatedDocs = merged
            .filter(msg => msg.documentMetadata && msg.tamperingStatus === 'ACCEPT')
            .map(msg => ({
              id: msg.id,
              type: msg.documentType || 'unknown',
              name: msg.documentMetadata.name,
              timestamp: msg.timestamp,
              filePath: msg.documentMetadata.filePath,
              extractedData: msg.extractedData,
              previewUrl: msg.documentMetadata.previewUrl
            }));
          setValidatedDocs(historicalValidatedDocs);

          logger.log('[LANGUAGE] History re-rendered in', globalLanguage);
        }
      } catch (error) {
        // Fail open — leave the conversation exactly as it was rather than
        // clearing it over a translation hiccup. Same convention as the
        // backend's own detect_and_translate_input()/translate_stored_message().
        logger.error('[LANGUAGE] Failed to re-fetch history at', globalLanguage, error);
      } finally {
        if (!cancelled) setIsTranslatingHistory(false);
      }
    })();

    return () => {
      cancelled = true;
    };
    // Deliberately only watches globalLanguage — messages/user are read from
    // the closure at fire time, not depended on, or every new message would
    // re-trigger this.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [globalLanguage, staleResyncNonce]);

  const successDocs = useMemo(() => {
    // Collect all unique validated documents from messages, keeping only the latest of each type
    const docs = [];
    const seenFiles = new Set();
    const seenTypes = new Set();

    [...messages].reverse().forEach(msg => {
      // ✅ HEALING 1: If extractedData is missing, try to find it in backend ground truth
      let effectiveExtracted = msg.extractedData;
      if (!effectiveExtracted && msg.documentType && backendSubmittedDocs.length > 0) {
        const found = backendSubmittedDocs.find(d => {
          // 1. Try matching by filename (most reliable)
          const dName = (d.filename || d.name || d.document_name || '').toLowerCase();
          const mName = (msg.documentMetadata?.name || '').toLowerCase();
          if (mName && dName && (mName === dName || dName.includes(mName) || mName.includes(dName))) return true;

          // 2. Fallback to type + name matching
          const dType = (d.document_type || d.type || '').toLowerCase();
          const mType = msg.documentType.toLowerCase();

          if (mType.includes('eid') || mType.includes('passport')) {
            const ext = d.extracted_fields || d.extracted_data || {};
            const name = d.member_name || d.name || ext.full_name || ext.fullName || ext.Name || ext.name || '';
            return name && msg.content?.toLowerCase().includes(name.toLowerCase());
          }
          return dType.includes(mType) || mType.includes(dType);
        });
        if (found) {
          logger.log(`[DEBUG-SUCCESS-DOCS] Healed ${msg.documentType} using filename/type match`);
          effectiveExtracted = found.extracted_fields || found.extracted_data;
        }
      }

      // ✅ HEALING 2: If documentMetadata is missing, try to find it in backend docs
      let effectiveMetadata = msg.documentMetadata;
      if (!effectiveMetadata && msg.documentType && backendSubmittedDocs.length > 0) {
        const found = backendSubmittedDocs.find(d => {
          const dType = (d.document_type || d.type || '').toLowerCase();
          const mType = msg.documentType.toLowerCase();
          if (mType.includes('eid') || mType.includes('passport')) {
            const ext = d.extracted_fields || d.extracted_data || {};
            const name = d.member_name || d.name || ext.full_name || ext.fullName || ext.Name || ext.name || '';
            return name && msg.content?.toLowerCase().includes(name.toLowerCase());
          }
          return dType.includes(mType) || mType.includes(dType);
        });
        if (found) {
          logger.log(`[DEBUG-SUCCESS-DOCS] Healed Metadata for ${msg.documentType}`);
          effectiveMetadata = {
            name: found.filename || found.name || 'Document',
            type: found.document_type,
            size: found.size || 0,
            previewUrl: found.document_file_path || found.preview_url,
            base64: null
          };
        }
      }

      // Check for success condition: must have documentMetadata and not be REJECTed
      if (effectiveMetadata && msg.tamperingStatus !== 'REJECT' && effectiveExtracted) {
        const type = (msg.documentType || 'unknown').toLowerCase();

        // Match the same identity logic used in getMessageSection
        const isIdentity = type.includes('eid') ||
          type.includes('passport') ||
          type.includes('id') ||
          type.includes('identity') ||
          type.includes('member_eid') ||
          type.includes('identification');

        // For identity docs (EID/Passport/Identification), we allow multiple entries if they represent different people.
        // For corporate docs (License/MOA/Ejari), we only keep the latest one using the type as the key.
        const individualId = effectiveExtracted?.fullName || effectiveExtracted?.full_name || msg.id;
        const typeKey = isIdentity ? `${type}_${individualId}` : type;

        // Ensure overall message uniqueness AND type uniqueness (per person for identity)
        if (!seenFiles.has(msg.id) && !seenTypes.has(typeKey)) {
          docs.push({
            ...effectiveMetadata,
            id: msg.id,
            documentType: msg.documentType || 'unknown',
            extractedData: {
              ...(effectiveExtracted || {}),
              ownershipMap: msg.ownershipMap
            },
            timestamp: msg.timestamp,
            tamperingScore: msg.tamperingScore,
            isComplete: msg.isComplete
          });
          seenFiles.add(msg.id);
          seenTypes.add(typeKey);
        }
      }
    });

    return docs.reverse();
  }, [messages, backendSubmittedDocs]);



  const allReportItems = useMemo(() => {
    const items = [...successDocs];
    if (fatcaData) {
      items.push({
        id: 'fatca-report',
        documentType: 'FATCA_DECLARATION',
        name: 'FATCA Self-Certification',
        extractedData: fatcaData,
        isVirtual: true
      });
    }
    if (pepData) {
      items.push({
        id: 'pep-report',
        documentType: 'PEP_DECLARATION',
        name: 'PEP Self-Declaration',
        extractedData: pepData,
        isVirtual: true
      });
    }
    if (productPackageData) {
      items.push({
        id: 'product-package-report',
        documentType: 'PRODUCT_PACKAGE',
        name: 'Product Package Selection',
        extractedData: productPackageData,
        isVirtual: true
      });
    }
    // 🛡️ HEALING: Reconstruct members list from history if membersInfo is missing or incomplete
    let effectiveMembersInfo = membersInfo;
    if (!effectiveMembersInfo?.all_members || effectiveMembersInfo.all_members.length === 0) {
      logger.log('[DEBUG-HEAL] Scanning', messages.length, 'messages for historical member lists...');
      const historyMsg = [...messages].reverse().find(m => {
        const hasList = (m.moaMembers && m.moaMembers.length > 0) ||
          (m.membersList && m.membersList.length > 0) ||
          (m.individuals && m.individuals.length > 0) ||
          (m.metadata?.moa_members && m.metadata.moa_members.length > 0) ||
          (m.metadata?.members_list && m.metadata.members_list.length > 0) ||
          (m.metadata?.individuals && m.metadata.individuals.length > 0) ||
          (m.metadata?.members && m.metadata.members.length > 0) ||
          (m.metadata?.partners && m.metadata.partners.length > 0) ||
          (m.metadata?.shareholders && m.metadata.shareholders.length > 0) ||
          (m.metadata?.ubo_names && m.metadata.ubo_names.length > 0) ||
          (m.extractedData?.directors_and_shareholders && m.extractedData.directors_and_shareholders.length > 0) ||
          (m.extractedData?.partners && m.extractedData.partners.length > 0);
        return hasList;
      });
      if (historyMsg) {
        const healedList = historyMsg.moaMembers || historyMsg.membersList || historyMsg.individuals ||
          historyMsg.metadata?.moa_members || historyMsg.metadata?.members_list ||
          historyMsg.metadata?.individuals || historyMsg.metadata?.members ||
          historyMsg.metadata?.partners || historyMsg.metadata?.shareholders ||
          historyMsg.metadata?.ubo_names ||
          historyMsg.extractedData?.directors_and_shareholders ||
          historyMsg.extractedData?.partners || [];

        logger.log('[DEBUG-HEAL] FOUND LIST in message:', historyMsg.id, 'Count:', healedList.length);

        effectiveMembersInfo = {
          ...(effectiveMembersInfo || {}),
          all_members: healedList,
          total: Math.max(effectiveMembersInfo?.total || 0, healedList.length),
          verified: effectiveMembersInfo?.verified || 0,
          verified_members: effectiveMembersInfo?.verified_members || []
        };
      } else {
        // ⚡️ LAST RESORT: If no history message found, but we have EID documents in successDocs, use those names!
        const eidDocs = successDocs.filter(d =>
          (d.documentType || '').toLowerCase().includes('eid') ||
          (d.documentType || '').toLowerCase().includes('passport') ||
          (d.documentType || '').toLowerCase().includes('id')
        );

        if (eidDocs.length > 0) {
          const derivedList = eidDocs.map(d => {
            const ext = d.extractedData || {};
            return ext.full_name || ext.fullName || ext.Name || ext.name || 'Individual';
          });

          logger.log('[DEBUG-HEAL] DERIVED list from verified identity documents. Count:', derivedList.length);

          effectiveMembersInfo = {
            ...(effectiveMembersInfo || {}),
            all_members: derivedList,
            total: Math.max(effectiveMembersInfo?.total || 0, derivedList.length),
            verified: eidDocs.length,
            verified_members: derivedList
          };
        } else {
          logger.log('[DEBUG-HEAL] No historical member list OR identity documents found');
        }
      }
    }

    if (effectiveMembersInfo && effectiveMembersInfo.all_members && effectiveMembersInfo.all_members.length > 0) {
      logger.log('[SIDEBAR-DEBUG] Registered Individuals Healed Data:', effectiveMembersInfo);
      // ✅ ROBUST SYNC: Build a combined ownership map scanning message history (Multiple + Single Owner)

      const ownershipMap = {};

      // 1. Initialize from ground truth preloaded members
      const preloaded = membersInfo?.preloadedMembers || membersInfo?.preloaded_members;
      if (Array.isArray(preloaded)) {
        preloaded.forEach(m => {
          const name = (m.display_name || m.name || '').trim().toUpperCase();
          if (name) {
            ownershipMap[name] = m.ownershipText || m.share_percentage || m.share || m.percentage;
          }
        });
      }


      // 2. Merge from legacy ground truth fields
      Object.assign(ownershipMap, membersInfo?.ownershipMap || membersInfo?.ownership_map || {});

      // ✅ NEW: kiContactMap — aggregates email/phone from KiDetailsCard confirmations
      const kiContactMap = {};

      if (Array.isArray(messages)) {
        messages.forEach(m => {
          // Handle Multiple Owner flow (explicit ownershipMap field)
          if (m.ownershipMap) {
            Object.entries(m.ownershipMap).forEach(([k, v]) => {
              ownershipMap[k.trim().toUpperCase()] = v;
            });
          }
          // ✅ NEW: Collect kiContactMap entries pushed by KiDetailsCard onConfirmed
          if (m.kiContactMap) {
            Object.entries(m.kiContactMap).forEach(([k, v]) => {
              kiContactMap[k.trim().toUpperCase()] = v;
            });
          }
          // Handle Single Owner flow (extractedData/metadata fields)
          const extracted = m.extractedData || m.metadata?.extracted_fields;

          // ⚡️ NEW: Support for Partners array in extracted_fields
          if (Array.isArray(extracted?.partners)) {
            extracted.partners.forEach(p => {
              const name = (p.name_english || p.name || '').trim().toUpperCase();
              const share = p.share_percentage || p.share || p.percentage;
              if (name && share) {
                ownershipMap[name] = share;
              }
            });
          }

          if (extracted?.owner?.name_english && extracted?.owner?.share_percentage) {
            ownershipMap[extracted.owner.name_english.toUpperCase()] = extracted.owner.share_percentage;
          } else if (extracted?.owner?.name && extracted?.owner?.share) {
            // Additional fallback keys
            ownershipMap[extracted.owner.name.toUpperCase()] = extracted.owner.share;
          }
        });
      }

      // Aggregate role maps from ALL messages to ensure we don't miss any assignments
      // ✅ ROBUST SYNC: Prioritize persistentRoleMap (state) over history scanning
      const messageRoles = { ...persistentRoleMap };

      // Sync from preloadedMembers roles
      if (Array.isArray(preloaded)) {
        preloaded.forEach(m => {
          const name = (m.display_name || m.name || '').trim().toUpperCase();
          if (name && m.role) messageRoles[name] = m.role;
        });
      }


      [...messages].forEach(m => {
        // Check direct fields
        const map = m.member_role_map || m.metadata?.member_role_map;
        if (map) {
          Object.entries(map).forEach(([k, v]) => {
            messageRoles[k.trim().toUpperCase()] = v;
          });
        }

        // Check individuals lists
        const list = m.individuals || m.metadata?.individuals || m.moaMembers || m.selectedIndividuals || m.kiMembers || m.moaAsTrigger?.individuals;
        if (Array.isArray(list)) {
          list.forEach(ind => {
            const n = (ind.display_name || ind.name || '').trim().toUpperCase();
            if (n) {
              messageRoles[n] = ind.role || (ind.is_authorised_signatory ? 'AS' : 'MEMBER');
            }
          });
        }
      });

      logger.log('[DEBUG-HISTORY-ROLES] Aggregated roles:', messageRoles);
      logger.log('[DEBUG-KI-CONTACT-MAP] Aggregated contact map:', kiContactMap);

      items.push({
        id: 'registered-individuals-report',
        documentType: 'REGISTERED_INDIVIDUALS',
        name: 'Registered Individuals',
        extractedData: {
          ...effectiveMembersInfo,
          member_role_map: { ...messageRoles, ...(effectiveMembersInfo.member_role_map || {}) },
          ownershipMap: ownershipMap,
          kiContactMap: kiContactMap,  // ✅ NEW: email/phone per KI
        },
        isVirtual: true
      });

    }
    return items;
  }, [successDocs, fatcaData, pepData, productPackageData, membersInfo, messages, persistentRoleMap]);


  const categories = useMemo(() => {
    const corporateItems = allReportItems.filter(i => {
      const t = (i.documentType || '').toLowerCase();
      return t.includes('commercial') || t.includes('license') || t.includes('moa') || t.includes('coi') || t.includes('incorporation') || t.includes('ejari') || t.includes('tenancy');
    });
    const userItems = allReportItems.filter(i => {
      const t = (i.documentType || '').toLowerCase();
      return t.includes('eid') || t.includes('passport') || t.includes('id') || t === 'registered_individuals';
    });
    const additionalItems = allReportItems.filter(i => {
      const t = (i.documentType || '').toLowerCase();
      return t === 'fatca_declaration' || t === 'pep_declaration' || t === 'product_package';
    });
    // Declaration is virtual — show if explicitly enabled OR if the product package is already in the report.
    // By the time the package is confirmed, all prior steps (FATCA/PEP, required for every
    // Corporate ownership type) are necessarily complete. We avoid depending on
    // user.ownership_type here because it may be stale/empty in localStorage if the
    // user logged in before that field was populated.
    const hasPackageInReport = allReportItems.some(i => (i.documentType || '').toLowerCase() === 'product_package');
    const declarationItems = (isDeclarationEnabled || hasPackageInReport) ? [{ documentType: 'SUMMARY_DECLARATION', isVirtual: true }] : [];

    logger.log('[DEBUG-CATEGORIES] Corporate:', corporateItems.length, 'User:', userItems.length, 'Additional:', additionalItems.length);
    logger.log('[DEBUG-CATEGORIES] User Items DocumentTypes:', userItems.map(i => i.documentType));
    logger.log('[DEBUG-CATEGORIES] Declaration:', declarationItems.length, '(isDeclarationEnabled:', isDeclarationEnabled, ', hasPackageInReport:', hasPackageInReport, ')');

    return [
      { title: 'Business Details', items: corporateItems, icon: Building },
      { title: 'User Details', items: userItems, icon: User },
      { title: 'Additional Details', items: additionalItems, icon: ShieldCheck },
      { title: 'Declaration', items: declarationItems, icon: CheckCircle }
    ].filter(cat => cat.items.length > 0);
  }, [allReportItems, isDeclarationEnabled]);

  // eslint-disable-next-line no-unused-vars
  const DocumentStatusTracker = ({ status, successDocs }) => {
    const allItems = [
      { key: 'commercial_license', label: 'Commercial License', icon: Building },
      { key: 'coi', label: 'Certificate of Inc.', icon: ShieldCheck },
      { key: 'moa', label: 'Memorandum (MOA)', icon: FileText },
      { key: 'emirates_id', label: 'Emirates ID (EID) or Passport', icon: User },
      { key: 'ejari', label: 'Ejari', icon: Home }
    ];

    const items = allItems.filter(item => requiredDocKeys.includes(item.key));
    const totalVerifiedCount = items.filter(i => status[i.key] === 'success').length;

    // For multi-member counting
    const idCount = successDocs.filter(d =>
      (d.documentType || '').toLowerCase().includes('eid') ||
      (d.documentType || '').toLowerCase().includes('passport')
    ).length;

    return (
      <div className="mb-8 px-1">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-[11px] font-black text-slate-400 uppercase tracking-[0.2em]">{t('ui.verificationHub')}</h3>
          <span className="text-[11px] font-black text-brand-primary bg-blue-50 px-3 py-1 rounded-full border border-blue-100/50">
            {t('ui.categoriesComplete', { count: totalVerifiedCount, total: items.length })}
          </span>
        </div>
        <div className="grid grid-cols-1 gap-2.5">
          {items.map((item) => {
            const isDone = status[item.key] === 'success';
            const isIdentity = item.key === 'emirates_id';

            return (
              <div
                key={item.key}
                className={`group relative p-4 rounded-3xl border transition-all duration-300 ${isDone
                  ? 'bg-emerald-50/40 border-emerald-100 shadow-sm'
                  : 'bg-white border-slate-100 hover:border-blue-100 hover:shadow-lg hover:shadow-blue-50/50'
                  }`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-4">
                    <div className={`p-2.5 rounded-2xl transition-all ${isDone
                      ? 'bg-emerald-500 text-white shadow-lg shadow-emerald-200'
                      : 'bg-slate-50 text-slate-400 group-hover:bg-brand-primary group-hover:text-white'
                      }`}>
                      <item.icon className="h-4.5 w-4.5" />
                    </div>
                    <div>
                      <h4 className={`text-[13px] font-black tracking-tight mb-0.5 ${isDone ? 'text-slate-900' : 'text-slate-700'}`}>
                        {t(`report.checklist.${item.key}`) || item.label}
                      </h4>
                      <div className="flex items-center gap-2">
                        {isDone ? (
                          <span className="text-[10px] font-black text-emerald-600 flex items-center gap-1 uppercase tracking-widest">
                            <CheckCircle className="h-3 w-3" />
                            {isIdentity ? (() => {
                              if (membersInfo) {
                                return t('report.checklist.membersVerified', { count: isDone ? membersInfo.total : membersInfo.verified, total: membersInfo.total });
                              }
                              const moaMessage = [...messages].reverse().find(m => (m.moaMembers && m.moaMembers.length > 0) || (m.membersList && m.membersList.length > 0));
                              const total = moaMessage?.moaMembers?.length || moaMessage?.membersList?.length || 1;
                              const count = isDone ? total : Math.min(idCount, total);
                              return total > 1 ? t('report.checklist.membersVerified', { count, total }) : t('report.verified');
                            })() : t('report.verified')}
                          </span>
                        ) : status[item.key] === 'progress' ? (
                          <span className="text-[10px] font-black text-brand-primary uppercase tracking-widest flex items-center gap-1">
                            <Clock className="h-3 w-3 animate-pulse" />
                            {isIdentity ? (() => {
                              if (membersInfo) {
                                return t('report.checklist.members', { count: membersInfo.verified, total: membersInfo.total });
                              }
                              const moaMessage = [...messages].reverse().find(m => (m.moaMembers && m.moaMembers.length > 0) || (m.membersList && m.membersList.length > 0));
                              const total = moaMessage?.moaMembers?.length || moaMessage?.membersList?.length || 1;
                              return total > 1 ? t('report.checklist.members', { count: idCount, total }) : t('report.checklist.inProgress');
                            })() : t('report.checklist.inProgress')}
                          </span>
                        ) : (
                          <span className="text-[10px] font-black text-slate-400 uppercase tracking-widest">
                            {t('report.checklist.pendingSubmission')}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                  {isDone ? (
                    <div className="h-6 w-6 bg-emerald-500 text-white rounded-full flex items-center justify-center shadow-lg shadow-emerald-100">
                      <CheckCircle className="h-3.5 w-3.5" />
                    </div>
                  ) : (
                    <div className="h-2 w-2 rounded-full bg-slate-100 group-hover:bg-blue-500 transition-colors" />
                  )}
                </div>

                {/* Success Indicator Border */}
                {isDone && (
                  <div className="absolute top-0 left-0 h-full w-1 bg-emerald-500" />
                )}
              </div>
            );
          })}
        </div>
      </div>
    );
  };

  // Requirements sync is now handled in fetchGroundTruth ground-truth sync.



  // ============================================================================
  // METADATA TRANSFORMATION HELPER
  // ============================================================================

  const transformLogToMessage = (log) => {
    let metadata = {};
    try {
      metadata = typeof log.metadata === 'string'
        ? JSON.parse(log.metadata)
        : (log.metadata || {});
    } catch (e) {
      logger.error('[TRANSFORM] Metadata parse error:', e);
    }

    const message = {
      id: log.id, // Add log ID to message
      role: log.role === 'agent' ? 'assistant' : 'user',
      content: log.message,
      // Stable text for routing/parsing logic, independent of display language:
      // the catalog's English rendering, else the stored original (the backend
      // returns it next to a translated `message`), else the message itself.
      logicText: metadata.i18n?.english || log.original_message || log.message,
      timestamp: log.timestamp
    };

    if (log.role === 'agent') {
      // Parse ownership shares from the untranslated text (names/percentages
      // are data; an LLM translation could reshape the list lines).
      let rawMsg = log.original_message || log.message || '';
      let ownershipMap = {};

      const ownershipRegex = /\d+\.\s+(?:\*\*)?(.+?)(?:\*\*)?\s*[-—–]\s*([0-9.]+%)/gi;
      let match;
      while ((match = ownershipRegex.exec(rawMsg)) !== null) {
        const name = match[1].replace(/\(UBO\)/gi, '').trim().toUpperCase();
        ownershipMap[name] = match[2].trim();
      }

      if (Object.keys(ownershipMap).length > 0) {
        const listRegex = /\n?\s*\d+\.\s+(?:\*\*)?[^-]+?(?:\(UBO\))?(?:\*\*)?\s*[-—–]\s*[0-9.]+%.*?effective ownership(?: \([^)]+\))?\s*/gi;
        message.content = rawMsg.replace(listRegex, '\n').replace(/\n{3,}/g, '\n\n').trim();
        message.ownershipMap = ownershipMap;
      }

      // Strip the Registered Individuals / Final Members / beneficial-owner
      // lists (any language) — utils/i18nText.js. The lists are shown from
      // data by the cards.
      message.content = stripMemberLists(message.content, t('chat.membersListedBelow'));
    }

    const messageType = metadata.message_type;
    message.stage = metadata.stage || metadata.new_stage;

    // ========================================================================
    // ✅ NEW: Parse Reference ID from message content (tampering messages)
    // ========================================================================
    if (messageType === "tampering_warning") {
      const decision = metadata.decision;
      message.tamperingStatus = decision;
      message.tamperingScore = metadata.tampering_score;
      message.testReportId = metadata.test_report_id;
      message.isWarning = (decision === 'ESCALATE');
      message.isError = (decision === 'REJECT');

      if (metadata.failed_tests && metadata.failed_tests.length > 0) {
        message.failedTests = metadata.failed_tests;
      }

      // ✅ PARSE REFERENCE ID FROM MESSAGE AND CLEAN IT
      let cleanedContent = log.message;
      const refIdPattern = /Reference ID:\s*([a-f0-9-]+)\s*$/i;
      const match = cleanedContent.match(refIdPattern);

      if (match) {
        // Extract the reference ID
        const extractedRefId = match[1];

        // Use extracted ID if metadata ID is missing
        if (!message.testReportId) {
          message.testReportId = extractedRefId;
        }

        // Remove the reference ID line from message content
        cleanedContent = cleanedContent.replace(refIdPattern, '').trim();

        // Remove any trailing newlines or whitespace
        cleanedContent = cleanedContent.replace(/\n\s*$/, '').trim();

        logger.log('[TRANSFORM] ✅ Extracted and cleaned reference ID from message');
      }

      // Update message content with cleaned version
      message.content = cleanedContent;
    }

    logger.log(`[TRANSFORM] Message ID: ${log.id}, Role: ${log.role}, Type: ${messageType}, Metadata Keys: ${Object.keys(metadata).join(', ')}`);
    if (metadata.extracted_fields || metadata.extracted_data) {
      logger.log(`[TRANSFORM] ✅ Extracted data found in metadata for ID: ${log.id}`);
    }



    // Rest of the function remains the same...
    if (messageType === 'stage_transition') {
      message.isStageTransition = true;
      message.fromStage = metadata.from_stage;
      message.toStage = metadata.to_stage;

      if (metadata.members && Array.isArray(metadata.members)) {
        message.membersList = metadata.members;
      }

      // ── Task 3 fix: restore AsKiManagementCard on history replay ──────────
      // The live-response path sets moaAsTrigger + moaMembers when it receives
      // stage_transition → member_eids.  On page reload these must be rebuilt
      // from the stored metadata so the numbered member list renders correctly.
      if (metadata.to_stage === 'member_eids') {
        message.moaAsTrigger = true;
        const storedMembers = metadata.moa_members || metadata.members || [];
        message.moaMembers = Array.isArray(storedMembers) ? storedMembers : [];
        message.uboNames = Array.isArray(metadata.ubo_names) ? metadata.ubo_names : [];
      }
    }

    // ✅ ROBUST RESTORATION: Always pull document data if it exists in metadata
    // This fixes the "Missing Verification Insights button" after reload by ensuring
    // extractedData is restored even if messageType isn't "extraction_result"
    if (metadata.document_type || metadata.extracted_fields || metadata.extracted_data || metadata.next_document) {
      message.documentType = metadata.document_type;
      message.extractedData = metadata.extracted_fields || metadata.extracted_data || null;
      message.tamperingScore = metadata.tampering_score;
      message.tamperingStatus = metadata.decision || 'ACCEPT';

      if (metadata.next_document) {
        message.nextDocument = metadata.next_document;
      }
      if (metadata.remaining_documents) {
        message.remainingDocuments = metadata.remaining_documents;
      }

      if (metadata.document_info) {
        message.documentMetadata = {
          name: metadata.document_info.filename,
          type: metadata.document_info.file_type
            || inferMimeTypeFromFilename(metadata.document_info.filename)
            || metadata.document_info.document_type,
          size: metadata.document_info.file_size,
          previewUrl: metadata.document_info.preview_url,
          base64: null
        };
      }

      // ✅ v3/v4 Triggers from metadata
      if (metadata.fatca_trigger) message.fatcaTrigger = true;
      if (metadata.ki_trigger) message.kiTrigger = true;

      if (metadata.moa_as_trigger) message.moaAsTrigger = true;
      if (metadata.so_as_trigger) message.asKiTrigger = true;
      if (metadata.so_owner) message.soOwner = metadata.so_owner;
      if (metadata.pep_trigger) message.pepTrigger = true;
      if (metadata.self_declaration_trigger) message.selfDeclTrigger = true;
      if (metadata.product_package_trigger) message.productPackageTrigger = true;
      if (metadata.moa_members) message.moaMembers = metadata.moa_members;
      if (metadata.ki_loop_prompt) message.kiLoopPrompt = true;
      if (metadata.as_selection_completed) {
        message.asSelectionCompleted = true;
        message.selectedIndividuals = metadata.selected_individuals || [];
      }
      if (metadata.is_ai_ki_eid_capture) {
        message.isAiKiEidCapture = true;
        message.aiKiExtractedData = metadata.extracted_fields || metadata.extracted_data;
        message.aiKiDocumentId = metadata.document_id;
        message.aiKiCaptured = metadata.ai_ki_captured || false;
      }

      // ✅ Capture completion status from history
      if (metadata.is_complete !== undefined) {
        message.isComplete = metadata.is_complete;
      }
      if (metadata.is_valid !== undefined) {
        message.isValid = metadata.is_valid;
      }
      if (metadata.stage) {
        message.stage = metadata.stage;
      }

      // ✅ RESTORE MAPS: Ensure manual adjustments (shares, contacts, roles) persist after reload
      message.ownershipMap = metadata.ownershipMap || metadata.ownership_map || null;
      message.kiContactMap = metadata.kiContactMap || metadata.ki_contact_map || null;
      message.member_role_map = metadata.member_role_map || metadata.member_role_map || null;
    }


    // Capture triggers for generic agent messages too
    if (log.role === 'agent') {
      if (metadata.fatca_trigger) message.fatcaTrigger = true;
      if (metadata.pep_trigger) message.pepTrigger = true;
      if (metadata.self_declaration_trigger) message.selfDeclTrigger = true;
      if (metadata.product_package_trigger) message.productPackageTrigger = true;
      if (metadata.ki_loop_prompt) message.kiLoopPrompt = true;
      if (metadata.moa_as_trigger) message.moaAsTrigger = true;
      if (metadata.so_as_trigger) message.asKiTrigger = true;
    }

    if (messageType === 'document_upload' || metadata.document_info) {
      if (messageType === 'document_upload') message.isUpload = true;

      if (metadata.document_info) {
        message.documentMetadata = {
          name: metadata.document_info.filename,
          type: metadata.document_info.file_type,
          size: metadata.document_info.file_size,
          previewUrl: metadata.document_info.preview_url,
          base64: null
        };
      }
    }

    if (messageType === 'validation_error') {
      message.isError = true;
      message.canRetry = true;
      message.errorType = 'wrong_document_type';

      if (metadata.uploaded_document_type) {
        message.documentType = metadata.uploaded_document_type;
      }

      if (metadata.expected_documents) {
        message.expectedDocuments = metadata.expected_documents;
      }

      // If there's an error list, use the first one as primary content if message is generic
      if (metadata.errors && metadata.errors.length > 0 && (!log.message || log.message.trim().length < 5)) {
        message.content = metadata.errors[0];
      }
    }

    if (messageType === 'welcome' || messageType === 'initial_welcome') {
      message.isWelcome = true;
    }

    // ── v3 message types ──────────────────────────────────────────────────
    if (messageType === 'fatca_confirmed') {
      message.isFatcaConfirmed = true;
    }
    if (messageType === 'ki_moa_as_saved') {
      message.isKiMoaAsSaved = true;
    }
    if (messageType === 'ubo_confirmed') {
      message.isUboConfirmed = true;
      message.memberName = metadata.member_name;
      message.isUbo = metadata.is_ubo;
    }
    if (messageType === 'self_declaration_confirmed') {
      message.isSelfDeclConfirmed = true;
    }
    if (messageType === 'ki_added') {
      message.isKiSaved = true;
    }

    // ── Progression / Onboarding fields ───────────────────────────────────
    if (metadata.next_document) {
      message.nextDocument = metadata.next_document;
    }
    if (metadata.remaining_documents) {
      message.remainingDocuments = metadata.remaining_documents;
    }
    if (metadata.onboarding_complete || metadata.is_onboarding_complete) {
      message.onboardingComplete = true;
    }

    // ── Extracted Data / Document Type ───────────────────────────────────
    if (metadata.extracted_data || metadata.extracted_fields) {
      message.extractedData = metadata.extracted_data || metadata.extracted_fields;
    }
    if (metadata.document_type) {
      message.documentType = metadata.document_type;
    }

    // Preserve the full metadata for background processes (e.g., sidebar role extraction)
    message.metadata = metadata;

    return message;
  };
  // ============================================================================
  // HELPER: CONVERT FILE TO BASE64
  // ============================================================================

  const fileToBase64 = (file) => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.readAsDataURL(file);
      reader.onload = () => {
        const base64 = reader.result.split(',')[1];
        resolve(base64);
      };
      reader.onerror = error => reject(error);
    });
  };

  // ============================================================================
  // INITIALIZATION WITH LANGUAGE PARAMETER
  // ============================================================================

  const initializeChat = useCallback(async () => {
    if (hasInitialized.current) {
      logger.log('[INIT] Chat already initialized, skipping');
      return;
    }

    logger.log(`[INIT] Starting chat initialization (mountId=${mountIdRef.current})`);
    logger.log('[INIT] User email:', user?.email);
    logger.log('[INIT] Selected language:', selectedLanguage);

    if (!user?.email) {
      logger.log('[INIT] No user email');
      return;
    }

    try {
      hasInitialized.current = true;
      setIsLoading(true);

      // First login on this browser (no local choice): adopt the language
      // saved on the account before the conversation starts, so the welcome
      // and history arrive in it. No-op when a local choice exists.
      let initLanguage = selectedLanguage;
      try {
        const accountLanguage = syncFromAccount ? await syncFromAccount(user.email) : null;
        if (accountLanguage) initLanguage = accountLanguage;
      } catch (e) { /* fail open */ }

      logger.log('[INIT] Calling start-conversation with language:', initLanguage);

      const startResp = await startConversation({
        email: user.email,
        language: initLanguage
      });

      logger.log('[INIT] Backend response received');
      logger.log('[INIT] should_resume:', startResp.data.should_resume);

      // Update backend state tracking
      if (startResp.data.stage) setBackendStage(startResp.data.stage);
      if (startResp.data.submitted_documents) setBackendSubmittedDocs(startResp.data.submitted_documents);

      if (startResp.data.should_resume || startResp.data.ref_prompt) {
        // ref_prompt: true means the backend has this user marked onboarding_complete
        // (see /start-conversation's "Post-onboarding returning user" branch). It used
        // to fall into the "else" welcome-message branch below, which called
        // setMessages([welcomeMessage]) with welcome_message = undefined (that field is
        // only ever sent for genuinely new users) — wiping the whole thread on every
        // reload/relogin, including anything the user sent after completion. Loading
        // history the same way as should_resume fixes that; it does not yet do anything
        // extra with existing_ref/ref_prompt itself.
        logger.log('[INIT] Returning user - loading history');

        // BUGFIX: this passed `{ params: {...} }`, but getConversationLogs()
        // already wraps its 2nd argument in `params`, so limit/channel went
        // out as params[limit]=... and were ignored — and no `language` was
        // sent at all, so a reload / re-login in Arabic or Spanish got the
        // history back in whatever language each row was stored in.
        const historyResp = await getConversationLogs(user.email, {
          limit: 100, channel: 'chat', language: initLanguage,
        });

        logger.log('[BACKEND-DEBUG] /conversation-logs/ response:', historyResp.data);

        if (historyResp.data?.logs && historyResp.data.logs.length > 0) {

          // deriveCardState: card completion (AS card, "Add More
          // Individuals?", FATCA) comes from the stored history itself, so a
          // reload / re-login in any language restores the same card state.
          const loadedMessages = deriveCardState(historyResp.data.logs
            .reverse()
            .map(log => transformLogToMessage(log)));

          setMessages(loadedMessages);

          // AUTO-COMPLETE CARDS BASED ON CURRENT BACKEND STAGE (Healing)
          const bStage = startResp.data.stage || '';
          // Stages that come AFTER signer selection
          const isDoneSigners = ['member_eids', 'so_member_eids', 'ejari', 'fatca', 'pep', 'self_declaration', 'declaration', 'complete'].includes(bStage);
          // Stages that come AFTER the overall KI/Member collection loop
          const isDoneKiLoop = ['fatca', 'pep', 'self_declaration', 'declaration', 'complete'].includes(bStage);

          if (isDoneSigners || isDoneKiLoop) {
            setMessages(prev => prev.map(m => {
              let updated = { ...m };
              if (isDoneSigners && (updated.moaAsTrigger || updated.asKiTrigger)) {
                updated.asSelectionCompleted = true;
              }
              if (isDoneKiLoop && (updated.kiLoopPrompt || updated.ki_loop_prompt)) {
                updated.kiLoopCompleted = true;
                updated.kiLoopChoice = updated.kiLoopChoice || 'no';
              }
              if (isDoneKiLoop && updated.isAiKiEidCapture) {
                updated.aiKiCaptured = true;
              }
              // If stage is past fatca, ensure fatca cards are confirmed
              if (bStage !== 'identification' && bStage !== 'moa' && bStage !== 'member_eids' && bStage !== 'so_member_eids' && bStage !== 'ejari') {
                if (updated.fatcaTrigger || updated.stage === 'fatca') updated.isFatcaConfirmed = true;
              }
              return updated;
            }));
          }

          // RESTORE ONBOARDING PROGRESSION STATE (currentStepId)
          // Find the last message that had a progression card so it renders correctly after refresh
          const lastProgressionId = [...loadedMessages]
            .reverse()
            .find(m => m.nextDocument || m.remainingDocuments || m.onboardingComplete)?.id;
          if (lastProgressionId) {
            logger.log('[INIT] Restoring currentStepId:', lastProgressionId);
            setCurrentStepId(lastProgressionId);
          }

          // If the last message was onboarding complete, set the state
          if (loadedMessages.length > 0 && loadedMessages[loadedMessages.length - 1].onboardingComplete) {
            setIsOnboardingComplete(true);
          }

          // BACK-FILL COMPLIANCE TRIGGERS FROM STATUS (Wait for status sync)
          // Use allSettled so a 404 on FATCA/PEP (not yet submitted) doesn't
          // prevent the product package status from loading.
          await syncPendingActions();

          // Also populate validatedDocs from history
          const historicalValidatedDocs = loadedMessages
            .filter(msg => msg.documentMetadata && msg.tamperingStatus === 'ACCEPT')
            .map(msg => ({
              id: msg.id,
              type: msg.documentType || 'unknown',
              name: msg.documentMetadata.name,
              timestamp: msg.timestamp,
              filePath: msg.documentMetadata.filePath, // Assuming filePath is available in metadata
              extractedData: msg.extractedData,
              previewUrl: msg.documentMetadata.previewUrl
            }));
          setValidatedDocs(historicalValidatedDocs);
          logger.log('[INIT] History loaded successfully');
        }
      } else {
        logger.log('[INIT] New user - displaying welcome message');

        const welcomeMessage = {
          id: 'welcome-' + Date.now(), // Assign a unique ID
          role: 'assistant',
          content: startResp.data.welcome_message,
          timestamp: new Date().toISOString(),
          isWelcome: true
        };

        setMessages([welcomeMessage]);
        logger.log('[INIT] Welcome displayed');
      }

    } catch (error) {
      logger.error('[INIT] Error:', error);

      const fallbackWelcome = {
        id: 'fallback-welcome-' + Date.now(), // Assign a unique ID
        role: 'assistant',
        content: t('chat.welcomeFallback'),
        timestamp: new Date().toISOString(),
        isWelcome: true
      };

      setMessages([fallbackWelcome]);
      toast.error(t('chat.couldNotLoadHistory'));

    } finally {
      setIsLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.email, selectedLanguage]);

  // Re-sync the ground-truth pending-action flags whenever the conversation
  // advances.
  //
  // The init effect above runs once per login. Every action that follows —
  // document upload, ownership save, AS/KI selection, KI-loop finalize, package
  // save, declaration submit — changes these flags on the backend and appends a
  // message here. Keying off the message count therefore catches all of them
  // without threading a callback through six card components, several of which
  // call their endpoint themselves and only report back via onConfirmed.
  //
  // Cheap and safe to run this often: syncPendingActions() is idempotent (every
  // back-fill inside it bails if the trigger is already present), so the only
  // cost is four GETs, and the alternative was users refreshing the page by hand
  // after every step.
  //
  // The re-sync is STAGGERED, not fired once. Keying off messages.length says
  // "something happened", but the message is appended the instant the response
  // arrives — which for the last member EID is BEFORE the backend has finished
  // the work that sets the next pending flag. The container log shows the gap
  // plainly: last member verified at 16:23:51, ki/loop-finalize not until
  // 16:24:30. A single immediate sync reads "nothing pending", messages.length
  // never changes again, and the FATCA card therefore only appeared after a
  // manual refresh — which remounts and re-reads.
  //
  // B8: the staggered version of this was a guess, and it said so — "a backend
  // step slower than 4 s would still need a refresh". It fired at 0, 1.5 s and
  // 4 s because the observed gap was 39 s of backend work reported by a message
  // that arrived immediately. Three fixed offsets do not cover a variable wait;
  // they cover the one wait that was measured.
  //
  // This polls instead, and stops on its own terms:
  //
  //   - it keeps going until syncPendingActions() reports it back-filled
  //     something, which is the real completion signal;
  //   - intervals widen (0.5 s -> 8 s) so a fast backend costs two requests and
  //     a slow one does not hammer the server;
  //   - it gives up after POLL_BUDGET_MS rather than polling forever;
  //   - it aborts the moment the component unmounts or messages change again.
  //
  // Still not the ideal fix. The ideal fix is a completion callback threaded
  // out of the card components, so the client is told rather than asking. That
  // is a change to six components, several of which call their own endpoint and
  // only report back via onConfirmed — a bigger, riskier edit than this one,
  // and one that wants a browser to verify. What this does is remove the fixed
  // deadline, which is the part that was provably wrong.
  useEffect(() => {
    if (!user?.email) return;
    if (messages.length === 0) return;

    let cancelled = false;
    let timer = null;

    const POLL_BUDGET_MS = 30000;
    const startedAt = Date.now();
    let delay = 500;

    const poll = async () => {
      if (cancelled) return;

      // syncPendingActions is idempotent — every back-fill inside it bails if
      // the trigger is already present — so an extra pass costs four GETs and
      // inserts nothing.
      let changed = false;
      try {
        changed = await syncPendingActions();
      } catch (err) {
        // A failed sync must not kill the loop; the next pass may succeed.
        logger.warn('[SYNC] pending-action poll failed, will retry', err);
      }

      if (cancelled) return;
      if (changed) return;                              // found it, stop
      if (Date.now() - startedAt > POLL_BUDGET_MS) {    // give up, do not spin
        logger.warn('[SYNC] no pending action surfaced within budget');
        return;
      }

      delay = Math.min(delay * 2, 8000);
      timer = setTimeout(poll, delay);
    };

    poll();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [user?.email, messages.length, syncPendingActions]);


  useEffect(() => {
    if (user?.email) {
      initializeChat();
    }
  }, [user?.email, selectedLanguage, initializeChat]);

  // ============================================================================
  // FILE HANDLING
  // ============================================================================

  const handleFileSelect = (e) => {
    const picked = Array.from(e.target.files || []);
    if (picked.length === 0) return;

    const validTypes = ['application/pdf', 'image/jpeg', 'image/jpg', 'image/png', 'image/webp'];
    const maxSize = 10 * 1024 * 1024;

    const valid = [];
    let rejected = 0;
    for (const file of picked) {
      if (!validTypes.includes(file.type)) {
        rejected += 1;
        continue;
      }
      if (file.size > maxSize) {
        rejected += 1;
        continue;
      }
      valid.push(file);
    }

    if (rejected > 0) {
      toast.error(
        picked.length === 1
          ? 'Please upload PDF, JPG, PNG, or WEBP files under 10MB'
          : `${rejected} file(s) skipped — PDF, JPG, PNG, or WEBP under 10MB only`
      );
    }

    if (valid.length === 0) {
      e.target.value = '';
      return;
    }

    setUploadedFiles(valid);
    setUploadedFile(valid[0]);
    toast.success(valid.length === 1 ? t('ui.fileSelected', { name: valid[0].name }) : t('ui.filesSelected', { count: valid.length }));
  };

  // ============================================================================
  // HANDLE DOCUMENT UPLOAD WITH IMMEDIATE ERROR COLORS
  // ============================================================================

  const handleUploadDocument = async () => {
    if (!uploadedFile) {
      toast.error(t('chat.selectFileFirst'));
      return;
    }

    // ✅ IMMEDIATE LOCK: Set loading state before any message state changes
    setIsLoading(true);

    if (showMemberInput && !memberName.trim()) {
      toast.error(t('chat.enterMemberName'));
      return;
    }

    const previewUrl = URL.createObjectURL(uploadedFile);
    const userMessageId = 'user-upload-' + Date.now();

    let base64Data = null;
    try {
      base64Data = await fileToBase64(uploadedFile);
    } catch (error) {
      logger.error('[UPLOAD] Base64 conversion error:', error);
    }

    const filename = uploadedFile.name.toLowerCase();
    const isCorporateFile = filename.includes('license') || filename.includes('commercial') || filename.includes('commerical') || filename.includes('ejari') || filename.includes('moa') || filename.includes('tenancy') || filename.includes('coi') || filename.includes('incorporation') || filename.includes('tc_') || filename.includes('establishment') || filename.includes('article');
    const isIdentityFile = filename.includes('passport') || filename.includes('eid') || filename.includes('identity') || filename.includes('visa') || filename.includes('emirates') ||
      filename.includes('pillai') || filename.includes('whitmore') || filename.includes('mazrouei') || filename.includes('rashidi') ||
      filename.includes('james') || filename.includes('balaji') || filename.includes('meera') || filename.includes('selfie') ||
      filename.includes('photo') || filename.includes('naida') || filename.includes('nadia') || filename.includes('faisal') ||
      filename.includes('edward') || filename.includes('suresh') || filename.includes('hamdan') || filename.includes('saeed');



    // Use filename keywords first, then fall back to the currently active tab, then finally the CURRENT LIVE SECTION.
    // This prevents jumping to Corporate during Identity uploads when filenames don't match keywords.
    const inferredStage = isCorporateFile ? 'corporate' : (isIdentityFile ? 'user' : (activeChatFilter || getCurrentLiveSection() || backendStage));


    // ✅ LOCK TAB: Ensure the user stays in the correct tab for the document they are uploading
    if (activeChatFilter !== inferredStage) {
      logger.log(`[UPLOAD] Locking tab filter to: ${inferredStage}`);
      setActiveChatFilter(inferredStage);
    }

    const userMessage = {
      id: userMessageId,
      role: 'user',
      content: memberName
        ? t('chat.uploadedForMember', { name: uploadedFile.name, member: memberName })
        : t('chat.uploaded', { name: uploadedFile.name }),
      timestamp: new Date().toISOString(),
      isUpload: true,
      documentType: pendingReuploadType,
      stage: inferredStage,              // Context-aware stage
      documentMetadata: {
        name: uploadedFile.name,
        type: uploadedFile.type,
        size: uploadedFile.size,
        previewUrl: previewUrl,
        base64: base64Data
      }
    };

    setMessages(prev => [...prev, userMessage]);

    // Clear chat-bar file pill immediately after hitting send. The composer
    // chip is rendered from uploadedFiles (the array — added for multi-select),
    // not uploadedFile (the older singular field this function still uses
    // internally) — clearing only uploadedFile left the chip on screen
    // through the whole upload, including the Planning loader, since nothing
    // here ever emptied the array it actually reads from.
    setUploadedFile(null);
    setUploadedFiles([]);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }

    const progressMessageId = 'progress-' + Date.now();
    setMessages(prev => [...prev, {
      id: progressMessageId,
      role: 'assistant',
      content: t('chat.authenticating'),
      timestamp: new Date().toISOString(),
      isProgress: true,
      documentType: pendingReuploadType,
      stage: inferredStage,              // Context-aware stage
      moaAsTrigger: false,               // Explicitly prevent empty cards
      asKiTrigger: false                 // Explicitly prevent empty cards
    }]);
    try {
      const formData = new FormData();
      formData.append('email', user.email);
      formData.append('files', uploadedFile);
      formData.append('language', selectedLanguage);

      if (memberName.trim()) {
        formData.append('member_name', memberName.trim());
      }

      // ── KI loop: tell backend this upload is for an AI-added individual ──
      // When awaitingAiAddEid is true the user clicked "Yes, Add Another" in
      // the KiLoopCard. The backend skips all member-routing logic and returns
      // is_ai_ki_eid_capture: true so the frontend can show KiRoleAssignCard.
      if (awaitingAiAddEid) {
        formData.append('is_ki_loop_add_eid', 'true');
      }

      if (pendingReuploadType) {
        formData.append('is_reupload', 'true');
        formData.append('reupload_target', pendingReuploadType);
        // Clear it after appending to form data
        setPendingReuploadType(null);
      }

      logger.log('[UPLOAD] Sending request with language:', selectedLanguage);

      const response = await uploadDocument(formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 140000
      });

      logger.log('[UPLOAD] Response received');
      logger.log('[UPLOAD-DEBUG] response.data keys:', Object.keys(response.data));
      if (response.data.extracted_fields || response.data.extracted_data) {
        logger.log('[UPLOAD-DEBUG] ✅ Extracted data present in response');
      } else {
        logger.log('[UPLOAD-DEBUG] ❌ Extracted data MISSING in response');
      }

      setMessages(prev => prev.filter(msg => msg.id !== progressMessageId));


      // ====================================================================
      // FIX #1: Handle REJECT (Tampering - already correct, but confirm)
      // ====================================================================
      if (response.data.tampering_detected || response.data.decision === 'REJECT') {
        logger.log('[UPLOAD] Document REJECTED - Tampering detected');

        const reasoningMessage = response.data.message ||
          response.data.llm_analysis ||
          t('ui.rejectedSecurity');

        setMessages(prev => [...prev, {
          id: 'reject-' + Date.now(),
          role: 'assistant',
          content: reasoningMessage,
          timestamp: new Date().toISOString(),
          isError: true,  // IMMEDIATE RED STYLING
          tamperingStatus: 'REJECT',
          testReportId: response.data.test_report_id,
          tamperingScore: response.data.tampering_score
        }]);

        toast.error(t('chat.docRejectedSecurity'));
        setUploadedFile(null);
        setUploadedFiles([]);
        if (fileInputRef.current) fileInputRef.current.value = '';
        return;
      }

      // ====================================================================
      // FIX #2: Handle ESCALATE (Tampering - already correct, but confirm)
      // ====================================================================
      if (response.data.manual_review_required || response.data.decision === 'ESCALATE') {
        logger.log('[UPLOAD] Document ESCALATED - Manual review required');

        const reasoningMessage = response.data.message ||
          response.data.llm_analysis ||
          t('ui.manualVerification');

        setMessages(prev => [...prev, {
          id: 'escalate-' + Date.now(),
          role: 'assistant',
          content: reasoningMessage,
          timestamp: new Date().toISOString(),
          isWarning: true,  // YELLOW STYLING (NOT RED)
          tamperingStatus: 'ESCALATE',
          testReportId: response.data.test_report_id,
          tamperingScore: response.data.tampering_score
        }]);

        toast.warning(t('ui.manualReviewToast'));
        setUploadedFile(null);
        setUploadedFiles([]);
        if (fileInputRef.current) fileInputRef.current.value = '';
        return;
      }

      // ====================================================================
      // ✅ FIX #5: Handle EXPIRY validation (NEW)
      // ====================================================================
      if (response.data.expiry_failed === true || response.data.decision === 'EXPIRED') {
        logger.log('[UPLOAD] Document EXPIRED - validation failed');

        const expiryMessage = response.data.message ||
          response.data.ai_reasoning ||
          t('ui.expiredMsg');

        setMessages(prev => [...prev, {
          id: 'expired-' + Date.now(),
          role: 'assistant',
          content: expiryMessage,
          timestamp: new Date().toISOString(),
          isError: true,  // IMMEDIATE RED STYLING
          errorType: 'expiry',
          expiryValidation: response.data.expiry_validation,
          canRetry: true
        }]);

        toast.error(t('chat.docExpired'));
        setUploadedFile(null);
        setUploadedFiles([]);
        if (fileInputRef.current) fileInputRef.current.value = '';
        return;
      }

      // ====================================================================
      // FIX #3: Handle WRONG DOCUMENT TYPE (NEW - IMMEDIATE RED)
      // ====================================================================
      if (response.data.wrong_document_type === true) {
        logger.log('[UPLOAD] WRONG document type uploaded');

        const errorMessage = response.data.message ||
          t('ui.notNeededMsg');

        setMessages(prev => [...prev, {
          id: 'wrong-type-' + Date.now(),
          role: 'assistant',
          content: errorMessage,
          timestamp: new Date().toISOString(),
          isError: true,  // IMMEDIATE RED STYLING
          canRetry: true,
          documentType: response.data.document_type,
          errorType: 'wrong_document_type',
          expectedDocuments: response.data.expected_documents,
          remainingDocuments: response.data.remaining_documents
        }]);

        toast.error(t('chat.wrongDocType', { type: response.data.document_type?.toUpperCase() || '' }));
        setUploadedFile(null);
        setUploadedFiles([]);
        if (fileInputRef.current) fileInputRef.current.value = '';
        return;
      }

      // ====================================================================
      // FIX #4: Handle UNKNOWN DOCUMENT TYPE (MAIN FIX - IMMEDIATE RED)
      // ====================================================================
      if (response.data.document_type === 'unknown' || (!response.data.success && !response.data.tampering_detected)) {
        logger.log('[UPLOAD] UNKNOWN document type or processing failure');

        const errorMessage = response.data.message ||
          t('ui.unidentifiedMsg');

        setMessages(prev => [...prev, {
          id: 'unknown-doc-' + Date.now(),
          role: 'assistant',
          content: errorMessage,
          timestamp: new Date().toISOString(),
          isError: true,  // IMMEDIATE RED STYLING
          canRetry: true,
          documentType: response.data.document_type || 'unknown',
          errorType: response.data.error_type || 'validation_error',
          severity: response.data.severity || 'high'
        }]);

        toast.error(t('chat.docNotIdentified'));
        setUploadedFile(null);
        setUploadedFiles([]);
        if (fileInputRef.current) fileInputRef.current.value = '';
        return;
      }

      // ====================================================================
      // SUCCESS: Document processed and valid
      // ====================================================================
      logger.log('[UPLOAD] SUCCESS - Document processed');

      const successMessageId = 'success-' + Date.now();

      // ====================================================================
      // SUCCESSFUL EXTRACTION - Combined with v3 triggers and progression info
      // ====================================================================

      // ── v4→v5: Mismatch detection no longer pops the modal immediately here.
      // A name/business mismatch on the Commercial License is now deferred —
      // the backend records it to a breadcrumb and only surfaces it as
      // mismatch_role_pending once we're right before member verification
      // (Ejari/MOA verified). See the ground-truth restoration block below,
      // mirrored on the same pattern as the AS/KI role card.

      let rawMsg = (response.data.response || response.data.message || response.data.acknowledgment || t('ui.processedOk'));
      let cleanedMsg = rawMsg;
      let ownershipMap = {};

      const ownershipRegex = /\d+\.\s+(?:\*\*)?(.+?)(?:\*\*)?\s*[-—–]\s*([0-9.]+%)/gi;
      let match;
      while ((match = ownershipRegex.exec(rawMsg)) !== null) {
        const name = match[1].replace(/\(UBO\)/gi, '').trim().toUpperCase();
        ownershipMap[name] = match[2].trim();
      }

      // ✅ NEW: Extraction from JSON structure (Partners array) - Robust fallback for "Share: —"
      const extracted = response.data.extracted_fields || response.data.extracted_data;
      if (Array.isArray(extracted?.partners)) {
        extracted.partners.forEach(p => {
          const name = (p.name_english || p.name || '').trim().toUpperCase();
          const share = p.share_percentage || p.share || p.percentage;
          if (name && share) {
            ownershipMap[name] = share;
          }
        });
      }
      // Single owner fallback
      if (extracted?.owner?.name_english && extracted?.owner?.share_percentage) {
        ownershipMap[extracted.owner.name_english.toUpperCase()] = extracted.owner.share_percentage;
      }


      const listRegex = /\n?\s*\d+\.\s+(?:\*\*)?[^-]+?(?:\(UBO\))?(?:\*\*)?\s*[-—–]\s*.*?(?:[0-9.]+%|effective ownership|verified|pending).*?(?=\n\d+\.|\n\r?\n|Please complete|Please confirm|All identity|$)/gi;
      cleanedMsg = rawMsg.replace(listRegex, '\n').replace(/\n{3,}/g, '\n\n').trim();

      // Strip member lists in any language (utils/i18nText.js).
      cleanedMsg = stripMemberLists(cleanedMsg, t('chat.membersListedBelow'));

      logger.log('[MOA-Clean] Raw Message:', rawMsg);
      logger.log('[MOA-Clean] Extracted Ownership:', ownershipMap);
      logger.log('[MOA-Clean] Cleaned Message:', cleanedMsg);

      const successMsg = {
        id: successMessageId,
        role: 'assistant',
        content: stripFormatting(rawMsg),
        ownershipMap: Object.keys(ownershipMap).length > 0 ? ownershipMap : undefined,
        timestamp: new Date().toISOString(),
        documentType: response.data.document_type,
        extractedData: response.data.extracted_fields || response.data.extracted_data || null,
        tamperingScore: response.data.tampering_score,
        tamperingStatus: response.data.decision || 'ACCEPT',
        nextDocument: response.data.next_document,
        remainingDocuments: response.data.remaining_documents,
        documentMetadata: {
          name: uploadedFile.name,
          previewUrl: previewUrl,
          type: uploadedFile.type,
          size: uploadedFile.size,
          base64: base64Data
        },
        // v3/v4 triggers
        fatcaTrigger: response.data.fatca_trigger || false,
        kiTrigger: response.data.ki_trigger || false,
        moaAsTrigger: response.data.moa_as_trigger || false,
        moaMembers: response.data.moa_members || [],
        uboNames: response.data.ubo_names || [],
        selfDeclTrigger: response.data.self_declaration_trigger || false,
        uboTrigger: response.data.ubo_trigger || false,
        uboMember: response.data.ubo_member || null,
        uboShare: response.data.ubo_share || 0,
        uboSuggested: response.data.ubo_suggested || false,
        // v4 triggers
        pepTrigger: response.data.pep_trigger || false,
        asKiTrigger: response.data.so_as_trigger || false,
        soOwner: response.data.so_owner || null,
        // KI loop
        kiLoopPrompt: response.data.ki_loop_prompt || false,
        // v5 triggers
        productPackageTrigger: response.data.product_package_trigger || false,
        // ✅ CRITICAL MOA/COLLECTION SYNC
        isComplete: response.data.is_complete !== undefined ? response.data.is_complete : true,
        isValid: response.data.is_valid !== undefined ? response.data.is_valid : true,
        stage: response.data.stage || response.data.new_stage,
      };

      // ✅ GUARDED: Only auto-navigate if corporate phase is actually finished
      if (successMsg.fatcaTrigger || successMsg.pepTrigger || successMsg.selfDeclTrigger || successMsg.productPackageTrigger) {
        successMsg.nextDocument = null;
        successMsg.remainingDocuments = [];
        // Removed auto-reset of filter to keep user on current tab
      }

      // ── KI loop: if we were waiting for an EID, capture it for role assignment ─
      // Check both key names: backend returns extracted_fields for KI loop uploads
      // (Fix B) and extracted_data for regular uploads — accept either.
      const _kiExtracted = response.data.extracted_fields || response.data.extracted_data;
      if (awaitingAiAddEid && _kiExtracted) {
        const docId = response.data.document_id || successMessageId;
        setAwaitingAiAddEid(false);
        successMsg.isAiKiEidCapture = true;
        successMsg.aiKiExtractedData = _kiExtracted;
        successMsg.aiKiDocumentId = docId;
      }

      // ── Stage transition handling (mirroring handleSendMessage) ─────────
      if (response.data.stage_transition && response.data.new_stage === 'corporate_shareholder_docs') {
        successMsg.isStageTransition = true;
        successMsg.fromStage = 'identification';
        successMsg.toStage = 'corporate_shareholder_docs';
      }
      let messagesToAdd = [successMsg];

      if (response.data.stage_transition && response.data.new_stage === 'member_eids') {
        const membersList = response.data.moa_members || response.data.members || [];

        // NEW: If MOA is validated, we split the message to keep MOA in Corporate 
        // but move the Signatories card to Identity.
        if (response.data.document_type === 'moa') {
          successMsg.moaAsTrigger = false; // MOA result message doesn't show the card

          const idTransitionMsg = {
            id: 'id-transition-' + Date.now(),
            role: 'assistant',
            content: t('chat.businessDocsVerified'),
            timestamp: new Date().toISOString(),
            isStageTransition: true,
            fromStage: 'corporate_shareholder_docs',
            toStage: 'member_eids',
            membersList: membersList,
            moaAsTrigger: true, // The card now appears in this Identity-stage message
            moaMembers: membersList,
            uboNames: response.data.ubo_names || [],
            ownershipMap: ownershipMap, // Pass ownership data to transition message
            stage: 'member_eids'
          };

          messagesToAdd.push(idTransitionMsg);
          setCurrentStepId(idTransitionMsg.id);
          // Removed automatic tab switch to keep user on Corporate until they are ready
        } else {
          // Standard transition (e.g. from Identification or other paths)
          successMsg.isStageTransition = true;
          successMsg.fromStage = response.data.fatca_trigger !== undefined ? 'corporate_shareholder_docs' : 'identification';
          successMsg.toStage = 'member_eids';
          successMsg.membersList = membersList;
          successMsg.moaAsTrigger = true;
          successMsg.moaMembers = membersList;
          successMsg.uboNames = response.data.ubo_names || [];
        }
      }

      // Add to Validated Docs Vault
      const newDocEntry = {
        id: successMessageId, // Use the message ID as the doc ID
        type: response.data.document_type || 'Unknown',
        name: uploadedFile.name,
        timestamp: new Date().toISOString(),
        filePath: response.data.document_file_path,
        extractedData: response.data.extracted_fields || response.data.extracted_data,
        previewUrl: previewUrl
      };
      setValidatedDocs(prev => [...prev, newDocEntry]);

      // Set the message as the current ACTIVE step ID
      setCurrentStepId(successMessageId);

      setMessages(prev => {
        const filtered = prev.filter(msg => msg.id !== progressMessageId);
        return [...filtered, ...messagesToAdd];
      });

      // Update backend state tracking
      if (response.data.stage || response.data.new_stage) {
        setBackendStage(response.data.stage || response.data.new_stage);
      }
      // Re-fetch submitted documents or update from this response
      // For now, we can manually add this one if it succeeded
      setBackendSubmittedDocs(prev => {
        const newDoc = {
          document_type: response.data.document_type,
          is_valid: response.data.is_valid !== undefined ? response.data.is_valid : true
        };
        // Avoid duplicates
        const updated = [...prev.filter(d => d.document_type !== newDoc.document_type), newDoc];
        return updated;
      });

      // Auto-open the Security Hub with the new data
      setTimeout(() => {
        setActiveDocData(successMsg);
        setSidebarMode('data'); // Switch to data view for the newly uploaded doc
      }, 500);

      // ── v3: show FATCA modal immediately if triggered ──────────────────
      // Suppressed for Corporate accounts — inline FatcaInlineCard handles it
      if (response.data.fatca_trigger && !isCorporateAccount) {
        setTimeout(() => setShowFatcaModal(true), 600);
      }



      toast.success(t('chat.uploadSuccess'));
      window.dispatchEvent(new Event('compliance-updated')); // Trigger Sidebar refresh

      if (showMemberInput) {
        setMemberName('');
      }

      setUploadedFile(null);
      setUploadedFiles([]);
      if (fileInputRef.current) fileInputRef.current.value = '';

    } catch (error) {
      logger.error('[UPLOAD] Error:', error);
      logger.error('[UPLOAD] Error details:', error.response?.data);

      // Remove progress indicator
      setMessages(prev => prev.filter(msg => msg.id !== progressMessageId));

      // Clean up upload state
      setUploadedFile(null);
      setUploadedFiles([]);
      if (fileInputRef.current) fileInputRef.current.value = '';

      // ✅ VISIBLE ERROR HANDLING — previously this was silent ("don't add error
      // to chat"), so a request timeout (e.g. the extraction API taking longer
      // than the model's response window) looked identical to nothing having
      // happened at all: no message, no retry prompt, just the spinner
      // disappearing. The user had no way to tell "still processing" apart
      // from "actually failed", and no cue to re-upload. Surface it instead —
      // note this does NOT affect whether the AS/KI or Product Package cards
      // reappear; that is handled by the ground-truth pending flags fetched on
      // load (see initializeChat), independent of this specific request.
      const isTimeout = error.code === 'ECONNABORTED' || /timeout/i.test(error.message || '');
      const backendDetail = error.response?.data?.detail || error.response?.data?.message;
      const errorText = isTimeout
        ? t('ui.timeoutOne')
        : (backendDetail || t('ui.uploadFailedOne'));

      toast.error(errorText);

      setMessages(prev => [...prev, {
        id: 'upload-error-' + Date.now(),
        role: 'assistant',
        content: `⚠️ ${errorText}`,
        timestamp: new Date().toISOString(),
        isUploadError: true,
      }]);

    } finally {
      setIsLoading(false);
    }
  };

  // ============================================================================
  // HANDLE BULK DOCUMENT UPLOAD (paperclip, more than one file selected)
  // ============================================================================
  // Same endpoint family as handleUploadDocument, same message-bubble
  // mechanics — one request carrying every file, one bubble pushed per
  // result instead of one bubble per request. No separate card, no mode
  // toggle: this only runs because uploadedFiles.length > 1, which only
  // happens because the file input above now allows multi-select.
  const handleBulkUpload = async () => {
    if (uploadedFiles.length < 2) {
      toast.error(t('chat.selectMultiple'));
      return;
    }

    setIsLoading(true);

    // Same reasoning as handleUploadDocument's inferredStage: getMessageSection()
    // classifies every message into a tab by reading msg.documentType/msg.stage,
    // falling back to a possibly-stale backendStage if neither is set. Without
    // this, the progress bubble below (and the user bubble) can land in a tab
    // that isn't the one currently open and simply never render — which is why
    // the PlanningTimeline loader appeared to not show up for bulk uploads even
    // though isProgress was already being set correctly.
    const bulkStage = activeChatFilter || getCurrentLiveSection() || backendStage;

    const filesToSend = uploadedFiles;
    const userMessageId = 'user-upload-bulk-' + Date.now();
    setMessages(prev => [...prev, {
      id: userMessageId,
      role: 'user',
      content: t('chat.uploadedN', { count: filesToSend.length }),
      timestamp: new Date().toISOString(),
      isUpload: true,
      stage: bulkStage,
      documentMetadata: { bulk: true, filenames: filesToSend.map(f => f.name) },
    }]);

    setUploadedFiles([]);
    setUploadedFile(null);
    if (fileInputRef.current) fileInputRef.current.value = '';

    const progressMessageId = 'progress-bulk-' + Date.now();
    setMessages(prev => [...prev, {
      id: progressMessageId,
      role: 'assistant',
      content: t('chat.processingN', { count: filesToSend.length }),
      timestamp: new Date().toISOString(),
      isProgress: true,
      stage: bulkStage,
      moaAsTrigger: false,
      asKiTrigger: false,
    }]);

    try {
      const formData = new FormData();
      formData.append('email', user.email);
      formData.append('language', selectedLanguage);
      filesToSend.forEach(f => formData.append('files', f));

      const response = await uploadDocumentsBulk(formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 180000,
      });

      setMessages(prev => prev.filter(msg => msg.id !== progressMessageId));

      const results = response.data?.results || [];
      // A file's tab is normally decided by its document TYPE (eid -> Identity,
      // moa -> Corporate — see getMessageSection). That's the right rule once
      // the account has actually reached its identity-collection stage. But a
      // bulk batch submitted while still in the Corporate stage (bulkStage ===
      // 'corporate' — e.g. Ejari + EID uploaded together before MOA and before
      // the Authorised Signatory card even exists to attribute the EID to
      // anyone) shouldn't have one of its own files jump ahead to the Identity
      // tab: from the user's perspective they were still doing Corporate work
      // when they picked those files. sectionOverride forces getMessageSection
      // to keep the whole batch's messages together in the tab the user was
      // actually in, for exactly this one case.
      const _identityDocTypes = ['eid', 'passport', 'identity'];
      const resultMessages = results.map((r, i) => {
        const label = r.member_name
          ? t('chat.docLabelForMember', { type: (r.document_type || 'document').toUpperCase(), member: r.member_name })
          : (r.filename || 'document');
        let content;
        if (r.is_valid) {
          // display_message is the backend's short, doc-type-aware line
          // ("Commercial License verified for X, 3 owner(s) listed.") — falls
          // back to the generic label only if that's somehow missing, rather
          // than r.message, which for a valid result is the full N/A field
          // dump this whole bulk feature deliberately keeps out of chat.
          content = r.display_message || t('chat.docVerifiedGeneric', { label });
          if (r.name_matches_expected === false) {
            content += ` ${t('chat.nameMismatch', { member: r.member_name })}`;
          }
        } else if (r.duplicate_in_batch) {
          content = `↷ ${r.filename}: ${r.message}`;
        } else {
          content = `❌ ${r.filename || label}: ${r.message || t('chat.couldNotBeVerified')}`;
        }
        const isPrematureIdentityDoc =
          bulkStage === 'corporate' && _identityDocTypes.includes((r.document_type || '').toLowerCase());
        return {
          id: `bulk-result-${Date.now()}-${i}`,
          role: 'assistant',
          content,
          timestamp: new Date().toISOString(),
          isUpload: true,
          documentType: r.document_type,
          sectionOverride: isPrematureIdentityDoc ? 'corporate' : undefined,
          // Fallback only — getMessageSection() already classifies most of
          // these correctly from documentType (e.g. "eid" -> user tab,
          // "moa" -> corporate tab). This just covers the "unknown"/null
          // document_type case (failed OCR, unassigned file) so the message
          // still lands in the tab the user is actually looking at instead
          // of falling through to a stale backendStage.
          stage: bulkStage,
          // Set directly from the response rather than left for the
          // filename/type "healing" matcher in successDocs to find later —
          // that matcher is a best-effort fallback for messages that never
          // carried this data client-side (e.g. restored from history), and
          // relying on it here is exactly what left Ejari's Unified Report
          // card empty while Commercial/CoI/MOA happened to heal: this
          // request already has the real data, so just attach it.
          extractedData: r.is_valid ? (r.extracted_data || null) : null,
          documentMetadata: r.is_valid ? {
            name: r.filename,
            type: inferMimeTypeFromFilename(r.filename),
            size: null,
            previewUrl: r.preview_url || null,
            base64: null,
          } : null,
        };
      });

      // The backend already computes next_document/remaining_documents for
      // this batch (same call get_onboarding_status makes for the
      // single-file path) — attach them to the last bubble in this batch and
      // point currentStepId at it, mirroring what handleUploadDocument does
      // for its one success message. NextDocumentCard gates on BOTH: it only
      // renders for the message whose id === currentStepId, and it needs
      // nextDocument/remainingDocuments to have anything to show — bulk was
      // missing both, which is why the "Capture Required" progression card
      // never appeared after a bulk upload even though the data existed.
      if (resultMessages.length > 0) {
        const lastMsg = resultMessages[resultMessages.length - 1];
        lastMsg.nextDocument = response.data?.next_document || null;
        lastMsg.remainingDocuments = response.data?.remaining_documents || [];
        setCurrentStepId(lastMsg.id);
      }

      setMessages(prev => [...prev, ...resultMessages]);

      const validCount = results.filter(r => r.is_valid).length;
      toast.success(t('chat.nOfMVerified', { valid: validCount, total: results.length }));
      window.dispatchEvent(new Event('compliance-updated'));

      // Ground-truth refresh — the same mechanism the single-file path and
      // the polling effect already use, so whatever card should naturally
      // come next (NextDocumentCard, KiLoopCard, ownership question, ...)
      // reappears exactly as it would after any other action, without this
      // handler needing to know which card that is.
      await syncPendingActions();

    } catch (error) {
      logger.error('[BULK-UPLOAD] Error:', error);

      setMessages(prev => prev.filter(msg => msg.id !== progressMessageId));

      const isTimeout = error.code === 'ECONNABORTED' || /timeout/i.test(error.message || '');
      const backendDetail = error.response?.data?.detail || error.response?.data?.message;
      const errorText = isTimeout
        ? t('ui.timeoutMany')
        : (backendDetail || t('ui.uploadFailedMany'));

      toast.error(errorText);

      setMessages(prev => [...prev, {
        id: 'upload-bulk-error-' + Date.now(),
        role: 'assistant',
        content: `⚠️ ${errorText}`,
        timestamp: new Date().toISOString(),
        isUploadError: true,
      }]);

    } finally {
      setIsLoading(false);
    }
  };

  // ============================================================================
  // HANDLE TEXT MESSAGE WITH LANGUAGE
  // ============================================================================

  const handleSendMessage = useCallback(async () => {
    if (!input.trim()) {
      toast.error(t('chat.enterMessage'));
      return;
    }

    const userMessageId = 'user-msg-' + Date.now();
    const userMessage = {
      id: userMessageId,
      role: 'user',
      content: input,
      timestamp: new Date().toISOString()
    };

    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);

    try {
      logger.log('[CHAT] Sending message in language:', selectedLanguage);

      const response = await sendChatMessage({
        email: user.email,
        message: input,
        language: selectedLanguage,
        chat_history: messages.slice(-10).map(msg => ({
          role: msg.role,
          content: msg.content,
          timestamp: msg.timestamp
        }))
      });
      logger.log('[BACKEND-DEBUG] /chat-conversational/ response:', response.data);


      const rd = response.data;
      logger.log('[CHAT-DEBUG] rd keys:', Object.keys(rd || {}));
      if (rd && (rd.extracted_fields || rd.extracted_data)) {
        logger.log('[CHAT-DEBUG] ✅ Extracted data present in rd');
      }

      // ── Phase 1 (chat-language-mirroring-plan.html / language-mirroring-verdict.html):
      // the backend may have detected the user actually typed in a different
      // language than the active toggle and translated it before answering.
      // Patch the bubble we already rendered optimistically, in place, by id
      // — rather than re-sending the message or rebuilding the send flow.
      if (rd && rd.was_translated && rd.translated_message) {
        logger.log('[CHAT] User message translated:', rd.detected_language, '->', selectedLanguage);
        setMessages(prev => prev.map(m => (
          m.id === userMessageId
            ? { ...m, content: rd.translated_message, wasTranslated: true, detectedLanguage: rd.detected_language }
            : m
        )));
      }

      const agentMessageId = 'agent-msg-' + Date.now();


      // ── Verification response path (is_verification: true, next_message) ─
      if (rd && rd.is_verification && rd.next_message) {
        const verifyMsg = {
          id: agentMessageId,
          role: 'assistant',
          content: stripFormatting(rd.next_message), // ✅ CLEANED IN LIVE TIME
          timestamp: new Date().toISOString(),
          isVerificationResponse: true,

          // v4 flow triggers
          fatcaTrigger: !!(rd.fatca_trigger || rd.fatcaTrigger),
          pepTrigger: !!(rd.pep_trigger || rd.pepTrigger),
          productPackageTrigger: !!(rd.product_package_trigger || rd.package_trigger || rd.productPackageTrigger),
          selfDeclTrigger: !!(rd.self_declaration_trigger || rd.selfDeclTrigger),
          stage: rd.stage || rd.new_stage,
          // KI loop prompt — show KiLoopCard after all EIDs verified
          kiLoopPrompt: rd.ki_loop_prompt || false,

          // ✅ NEW: Capture extraction data in verification path
          extractedData: rd.extracted_fields || rd.extracted_data || null,
          documentType: rd.document_type,
          tamperingScore: rd.tampering_score,
          tamperingStatus: rd.decision || 'ACCEPT',
        };


        setMessages(prev => [...prev, verifyMsg]);
        setCurrentStepId(agentMessageId);



        logger.log('[CHAT] Verification response received');
        return;
      }

      if (rd && rd.response) {
        // ── Build base message ────────────────────────────────────────────
        let rawMsg = rd.response;
        let cleanedMsg = rawMsg;
        let ownershipMap = {};

        const ownershipRegex = /\d+\.\s+(?:\*\*)?(.+?)(?:\*\*)?\s*[-—–]\s*([0-9.]+%)/gi;
        let match;
        while ((match = ownershipRegex.exec(rawMsg)) !== null) {
          const name = match[1].replace(/\(UBO\)/gi, '').trim().toUpperCase();
          ownershipMap[name] = match[2].trim();
        }

        // ✅ NEW: Extraction from JSON structure (Partners array) - Robust fallback for "Share: —"
        const extracted = rd.extracted_fields || rd.extracted_data;
        if (Array.isArray(extracted?.partners)) {
          extracted.partners.forEach(p => {
            const name = (p.name_english || p.name || '').trim().toUpperCase();
            const share = p.share_percentage || p.share || p.percentage;
            if (name && share) {
              ownershipMap[name] = share;
            }
          });
        }
        // Single owner fallback
        if (extracted?.owner?.name_english && extracted?.owner?.share_percentage) {
          ownershipMap[extracted.owner.name_english.toUpperCase()] = extracted.owner.share_percentage;
        }


        const listRegex = /\n?\s*\d+\.\s+(?:\*\*)?[^-]+?(?:\(UBO\))?(?:\*\*)?\s*[-—–]\s*.*?(?:[0-9.]+%|effective ownership|verified|pending).*?(?=\n\d+\.|\n\r?\n|Please complete|Please confirm|All identity|$)/gi;
        cleanedMsg = rawMsg.replace(listRegex, '\n').replace(/\n{3,}/g, '\n\n').trim();

        // Strip member lists in any language (utils/i18nText.js).
        cleanedMsg = stripMemberLists(cleanedMsg, t('chat.membersListedBelow'));

        logger.log('[CHAT-Clean] Raw Message:', rawMsg);
        logger.log('[CHAT-Clean] Extracted Ownership:', ownershipMap);
        logger.log('[CHAT-Clean] Cleaned Message:', cleanedMsg);

        const agentMessage = {
          id: agentMessageId,
          role: 'assistant',
          content: stripFormatting(cleanedMsg), // ✅ ALREADY CLEANED, BUT APPLY STRIPFORMATTING FOR CONSISTENCY
          ownershipMap: Object.keys(ownershipMap).length > 0 ? ownershipMap : undefined,
          timestamp: new Date().toISOString(),
          // v4 flow triggers
          fatcaTrigger: !!(rd.fatca_trigger || rd.fatcaTrigger),
          pepTrigger: !!(rd.pep_trigger || rd.pepTrigger),
          productPackageTrigger: !!(rd.product_package_trigger || rd.package_trigger || rd.productPackageTrigger),
          selfDeclTrigger: !!(rd.self_declaration_trigger || rd.selfDeclTrigger),
          stage: rd.stage || rd.new_stage,

          // ✅ NEW: Capture extraction data in standard response path
          extractedData: rd.extracted_fields || rd.extracted_data || null,
          documentType: rd.document_type,
          tamperingScore: rd.tampering_score,
          tamperingStatus: rd.decision || 'ACCEPT',
        };



        // ── Stage transition: identification → corporate_shareholder_docs ─
        if (rd.stage_transition && rd.new_stage === 'corporate_shareholder_docs') {
          agentMessage.isStageTransition = true;
          agentMessage.fromStage = 'identification';
          agentMessage.toStage = 'corporate_shareholder_docs';
          logger.log('[CHAT] Stage transition → corporate_shareholder_docs');
        }

        // ── Stage transition: any → member_eids ──────────────────────────
        // Covers BOTH Type-1 (identification → member_eids) and
        // Type-2 (corporate_shareholder_docs → member_eids).
        // moa_as_trigger is always true for both paths.
        if (rd.stage_transition && rd.new_stage === 'member_eids') {
          const membersList = rd.moa_members || rd.members || [];
          agentMessage.isStageTransition = true;
          // Derive fromStage: Type-2 response includes fatca_trigger flag at this
          // point (fired after COI+MOA analysis); Type-1 does not.
          agentMessage.fromStage = rd.fatca_trigger !== undefined
            ? 'corporate_shareholder_docs'
            : 'identification';
          agentMessage.toStage = 'member_eids';
          agentMessage.membersList = membersList;
          // Always show AsKiManagementCard with UBO labels pre-populated
          agentMessage.moaAsTrigger = true;
          agentMessage.moaMembers = membersList;
          agentMessage.uboNames = rd.ubo_names || [];
          logger.log('[CHAT] Stage transition →', agentMessage.fromStage, '→ member_eids,',
            membersList.length, 'members, UBOs:', rd.ubo_names);
          // FATCA trigger fires for Type-2 after COI+MOA analysis
          // Suppressed for Corporate accounts — inline FatcaInlineCard handles it
          if (rd.fatca_trigger && !isCorporateAccount) {
            setTimeout(() => setShowFatcaModal(true), 600);
          }
        }

        setMessages(prev => [...prev, agentMessage]);
        setCurrentStepId(agentMessageId);
        // Removed auto-reset of filter to respect user manual selection
        logger.log('[CHAT] Response received in', selectedLanguage);
      }
    } catch (error) {
      logger.error('[CHAT] Error:', error);
      toast.error(t('chat.sendFailed'));

      const errorMessage = t('chat.errorTryAgain');

      setMessages(prev => [...prev, {
        id: 'error-msg-' + Date.now(),
        role: 'assistant',
        content: errorMessage,
        timestamp: new Date().toISOString(),
        isError: true
      }]);
    } finally {
      setIsLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [input, messages, user, selectedLanguage, isCorporateAccount]);

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (uploadedFile) {
        handleUploadDocument();
      } else {
        handleSendMessage();
      }
    }
  };

  const handleSuggestionClick = useCallback((suggestion) => {
    if (!suggestion || isLoading) return;
    setInput(suggestion);
    // Use a small timeout to ensure the state update is processed before sending
    setTimeout(() => {
      // In AIAssistant, we can directly call handleSendMessage
      handleSendMessage();
    }, 100);
  }, [isLoading, handleSendMessage]);

  // ============================================================================
  // v3: FATCA / KI CALLBACKS
  // ============================================================================

  const handleFatcaConfirmed = useCallback(({ message, so_as_trigger, so_owner, stage }) => {
    const confirmMsgId = 'fatca-confirm-' + Date.now();
    // Only add the backend's confirmation message — it already contains the
    // correct "next document" instruction for every account type.
    // Do NOT hardcode a MOA prompt here: Single Owner needs EID next, not MOA.
    const confirmMsg = {
      id: confirmMsgId,
      role: 'assistant',
      content: message || t('ui.fatcaSavedFallback'),
      timestamp: new Date().toISOString(),
      isFatcaConfirmed: true,
      stage: stage,
      // ── Single Owner: show AS/KI card right after FATCA ────────────────
      asKiTrigger: so_as_trigger || false,
      soOwner: so_owner || null,
    };
    setMessages(prev => [...prev, confirmMsg]);
    setCurrentStepId(confirmMsgId);
  }, []);

  const handleOwnershipTypeSaved = useCallback(({ ownership_type, partnership_details, ai_message }) => {
    // Mark the initiating card as completed in message history
    setMessages(prev => {
      const lastIdx = prev.findLastIndex(m => m.ownershipTypeTrigger);
      if (lastIdx === -1) return prev;
      const newMsgs = [...prev];
      newMsgs[lastIdx] = {
        ...newMsgs[lastIdx],
        ownershipTypeCompleted: true,
        ownershipTypeChoice: ownership_type,
      };
      return [
        ...newMsgs,
        {
          id: 'ownership-type-confirm-' + Date.now(),
          role: 'assistant',
          content: ai_message || t('ui.ownershipNoted', { type: ownership_type === 'Single Owner' ? t('ui.soleProprietorship') : t('ui.jointOwnership') }),
          timestamp: new Date().toISOString(),
          stage: 'user',
        },
      ];
    });

    // Reflect the choice locally right away so isCorporateAccount/document
    // requirement derivations don't wait on a full page reload.
    if (user) {
      user.ownership_type = ownership_type;
      if (partnership_details) user.partnership_details = partnership_details;
    }

    // Give the backend a moment to finish saving before re-fetching ground truth
    // (document requirements now depend on ownership_type, which just changed).
    setTimeout(() => {
      fetchGroundTruth();
    }, 1000);
  }, [user, fetchGroundTruth]);

  const handleAsSelection = useCallback(async (individuals, moaResponseData) => {
    // Single Owner: individuals contains the SO_OWNER + any manually-added KIs.
    // We MUST call /ki/so-as-selection here so the backend can:
    //   1. Build member_progress.json  ([Owner, KI-1, KI-2, ...])
    //   2. Transition document_stage → so_member_eids
    //   3. Sequence EID uploads:  Owner EID → KI EIDs → Ejari
    // Without this call, member_progress is never written and the upload
    // endpoint jumps straight to Ejari after the Owner EID.
    const soOwner = (individuals || []).find(i => i.source === 'SO_OWNER');
    // Backend's own confirmation message — captured so the bubble below can
    // use it instead of a hardcoded string. The backend already checks
    // whether the owner's identity document was uploaded earlier (e.g. bulk-
    // uploaded alongside Ejari, before this card even existed) and words the
    // message accordingly ("already on file" vs "next please upload it") —
    // a hardcoded client-side string can't know that, and used to always
    // say "please proceed with identity verification" even when there was
    // nothing left to verify.
    let asSelectionMessage = null;
    // Multiple Owner (Type-1/Type-2): the AS/KI card already called
    // /ki/moa-as-selection itself (see AsKiManagementCard.handleProceed) and
    // passes its response here as moaResponseData — this used to be
    // discarded entirely, which is why this bubble always fell back to the
    // generic hardcoded string below even when every member's identity
    // document was already verified (e.g. reconciled from an earlier bulk
    // upload). all_members_verified tells us whether to skip straight to
    // the "Add More Individuals?" card instead of waiting for an EID upload
    // that will never come because there's nothing left to upload.
    let allMembersVerified = false;
    if (soOwner) {
      try {
        const soResp = await selectSingleOwnerAuthorisedSignatory({
          email: user?.email,
          owner_role: soOwner.role || 'AS',
        });
        asSelectionMessage = soResp?.data?.message || null;
      } catch (e) {
        logger.warn('[handleAsSelection] so-as-selection API call failed:', e);
      }
    } else if (moaResponseData) {
      asSelectionMessage = moaResponseData.message || null;
      allMembersVerified = !!moaResponseData.all_members_verified;
    }

    // Mark the initiating card as completed in message history
    setMessages(prev => {
      const lastIdx = prev.findLastIndex(m => m.moaAsTrigger || m.asKiTrigger);
      if (lastIdx !== -1) {
        const newMsgs = [...prev];
        newMsgs[lastIdx] = {
          ...newMsgs[lastIdx],
          asSelectionCompleted: true,
          selectedIndividuals: individuals
        };
        return newMsgs;
      }
      return prev;
    });

    // ✅ OPTIMISTIC UPDATE: Update local membersInfo immediately so sidebar reflects changes instantly
    const roleMap = {};
    individuals.forEach(m => {
      const n = (m.display_name || m.name || '').trim().toUpperCase();
      if (n) roleMap[n] = m.role || (m.is_authorised_signatory ? 'AS' : 'MEMBER');
    });

    setPersistentRoleMap(prev => ({ ...prev, ...roleMap })); // 🔒 Save to vault

    setMembersInfo(prev => ({
      ...prev,
      member_role_map: { ...(prev?.member_role_map || {}), ...roleMap }
    }));

    setMessages(prev => [...prev, {
      id: 'as-confirm-' + Date.now(),
      role: 'assistant',
      content: asSelectionMessage
        || t('chat.asConfirmedFallback'),
      timestamp: new Date().toISOString(),
      stage: 'user', // Explicitly trigger the next section
      // Everyone already has a verified ID on file (reconciled from an
      // earlier upload) — there's no EID left to upload, so show the "Add
      // More Individuals?" card right here instead of leaving the user on
      // an instruction with nothing to act on.
      kiLoopPrompt: allMembersVerified,
    }]);

    // Give the backend a moment to finish saving before we re-fetch ground truth
    setTimeout(() => {
      fetchGroundTruth();
    }, 1000);

    // ✅ FIX: pin the tab explicitly instead of setActiveChatFilter(null).
    // The backend flips document_stage -> so_member_eids as part of this
    // same AS/KI-selection call, but fetchGroundTruth() (the only thing that
    // re-reads it into backendStage) is deliberately delayed 1s above to let
    // that write land. Clearing the filter here handed navigation back to
    // getCurrentLiveSection() a full second before backendStage caught up —
    // during that gap it still read as identification/corporate_shareholder_docs,
    // and the "still collecting corporate docs" guard snapped the tab back to
    // Corporate even though the message we just added is unambiguously an
    // Identity-stage message. We know for certain this always belongs on the
    // Identity tab, so say so directly instead of asking the stale guesser.
    setActiveChatFilter('user');
  }, [user?.email, fetchGroundTruth]);

  // ── KI Conversational Loop handlers ──────────────────────────────────────
  const handleKiLoopAddAnother = useCallback(() => {
    setAwaitingAiAddEid(true);
    setMessages(prev => {
      const lastIdx = prev.findLastIndex(m => m.kiLoopPrompt);
      if (lastIdx === -1) return prev;
      const newMsgs = [...prev];
      newMsgs[lastIdx] = { ...newMsgs[lastIdx], kiLoopCompleted: true, kiLoopChoice: 'yes' };
      return [...newMsgs, {
        id: 'ki-loop-add-' + Date.now(),
        role: 'assistant',
        content: '📎 Please upload the EID or Passport for the next individual.',
        timestamp: new Date().toISOString(),
        stage: 'user', // Ensure it stays in the Identity tab
      }];
    });
  }, []);

  const handleKiLoopProceed = useCallback(async () => {
    setAwaitingAiAddEid(false);

    let resp = null;
    try {
      resp = await finalizeKeyIndividualLoop({ email: user?.email });
    } catch (e) {
      logger.warn('[KiLoop] loop-finalize failed:', e);
    }

    const rd = resp?.data || {};
    let displayMsg = rd.message || t('chat.allRecordedFallback');

    // Strip member lists in any language (utils/i18nText.js).
    displayMsg = stripMemberLists(displayMsg, t('chat.membersListedBelow'));

    const loopDoneMsg = {
      id: 'ki-loop-done-' + Date.now(),
      role: 'assistant',
      content: displayMsg,
      timestamp: new Date().toISOString(),
      // ── Wire up the correct next-step trigger from backend response ──────
      fatcaTrigger: !!(rd.fatca_trigger || rd.fatcaTrigger),
      pepTrigger: !!(rd.pep_trigger || rd.pepTrigger),
      productPackageTrigger: !!(rd.product_package_trigger || rd.package_trigger || rd.productPackageTrigger),
      selfDeclTrigger: !!(rd.self_declaration_trigger || rd.selfDeclTrigger),
      stage: rd.stage || rd.new_stage,
      // ── Progression card: show next required document (e.g. Ejari for Single Owner) ──
      nextDocument: rd.next_document || null,
      remainingDocuments: rd.remaining_documents || [],
    };

    // Suppress document-progression widget when a compliance step fires
    if (loopDoneMsg.fatcaTrigger || loopDoneMsg.pepTrigger || loopDoneMsg.selfDeclTrigger || loopDoneMsg.productPackageTrigger) {
      loopDoneMsg.nextDocument = null;
      loopDoneMsg.remainingDocuments = [];
    }

    setMessages(prev => {
      const lastIdx = prev.findLastIndex(m => m.kiLoopPrompt);
      if (lastIdx !== -1) {
        const newMsgs = [...prev];
        newMsgs[lastIdx] = { ...newMsgs[lastIdx], kiLoopCompleted: true, kiLoopChoice: 'no' };
        return [...newMsgs, loopDoneMsg];
      }
      return [...prev, loopDoneMsg];
    });
    // ✅ FIX: pin the tab from the backend's own trigger flags instead of
    // setActiveChatFilter(null). fetchGroundTruth() below is what refreshes
    // backendStage, but that call is async — clearing the filter first (the
    // old order) handed navigation to getCurrentLiveSection() while
    // backendStage could still be stale, same race as handleAsSelection
    // above. loopDoneMsg already tells us definitively where we're going,
    // so use that instead of waiting on backendStage to catch up.
    if (loopDoneMsg.fatcaTrigger || loopDoneMsg.pepTrigger || loopDoneMsg.productPackageTrigger) {
      setActiveChatFilter('additional');
    } else if (loopDoneMsg.selfDeclTrigger) {
      setActiveChatFilter('declaration');
      setIsDeclarationEnabled(true);
    } else {
      // Nothing triggered yet (e.g. more corporate documents still pending
      // for this account type) — stay in Identity rather than guessing.
      setActiveChatFilter('user');
    }
    fetchGroundTruth(); // Force a fresh sync of backendStage and membersInfo
  }, [user?.email, fetchGroundTruth]);

  const handleKISaved = useCallback(({ ki } = {}) => {
    // ── Single Owner KI loop: do NOT print a separate chat bubble here ────────
    // The KiRoleAssignCard's onSaved callback already adds a new KiLoopCard
    // message (with the person's name + "Would you like to add another?"), so
    // adding a second confirmation bubble here is redundant and clutters the chat.
    // We still need to update currentStepId and refresh the AsKiManagementCard.
    const kiSavedMsgId = 'ki-saved-' + Date.now();
    setCurrentStepId(kiSavedMsgId);

    // ✅ ROBUST SYNC: Save the role to persistent vault so Sidebar/Insights show correct role
    if (ki) {
      const normalizedName = (ki.display_name || ki.name || '').trim().toUpperCase();
      const role = ki.role || (ki.ki?.is_authorised_signatory ? 'AS' : 'MEMBER');

      if (normalizedName) {
        setPersistentRoleMap(prev => ({ ...prev, [normalizedName]: role }));
        setMembersInfo(prev => ({
          ...prev,
          member_role_map: { ...(prev?.member_role_map || {}), [normalizedName]: role }
        }));
      }
    }

    // Add the new KI into the AsKiManagementCard list (so it shows up when finalised)
    if (moaCardResetRef.current && moaCardResetRef.current.current && ki) {
      moaCardResetRef.current.current(ki);
    }

    // ✅ FIX: a new KI being saved always means we're mid-Identity — pin the
    // tab directly instead of setActiveChatFilter(null), which risked the
    // same stale-backendStage race as handleAsSelection/handleKiLoopProceed
    // above (this fires right after a save call, before any refetch of
    // backendStage has had a chance to land).
    setActiveChatFilter('user');
  }, [moaCardResetRef]);


  // eslint-disable-next-line no-unused-vars
  const handleUboConfirmed = useCallback(({ message, stage }) => {
    if (message) {
      const uboConfirmMsgId = 'ubo-confirm-' + Date.now();
      setMessages(prev => [...prev, {
        id: uboConfirmMsgId,
        role: 'assistant',
        content: message,
        timestamp: new Date().toISOString(),
        stage: stage,
      }]);
      setCurrentStepId(uboConfirmMsgId);
    }
  }, []);

  const handleSelfDeclConfirmed = useCallback(({ message, crossValidation, stage }) => {
    const selfDeclConfirmMsgId = 'self-decl-confirm-' + Date.now();
    // Add self-declaration confirmation message
    if (message) {
      setMessages(prev => [...prev, {
        id: selfDeclConfirmMsgId,
        role: 'assistant',
        content: message,
        timestamp: new Date().toISOString(),
        isSelfDeclConfirmed: true,
        stage: stage,
      }]);
      setCurrentStepId(selfDeclConfirmMsgId);
    }
    // Add cross-validation result message if available
    if (crossValidation?.message) {
      const crossValidMsgId = 'cross-valid-' + Date.now();
      setMessages(prev => [...prev, {
        id: crossValidMsgId,
        role: 'assistant',
        content: crossValidation.message,
        timestamp: new Date().toISOString(),
        isCrossValidResult: true,
        crossValidPassed: crossValidation.passed,
      }]);
      setCurrentStepId(crossValidMsgId);
    }
    setActiveChatFilter(null);
    // NO LONGER AUTOMATICALLY ADDING ONBOARDING COMPLETE MESSAGE HERE.
    // It is now triggered by the 'OK' button in the Unified Report sidebar (handleOnboardingComplete).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // EXPOSE SIDEBAR MODE GLOBALLY FOR AUTO-TRIGGERS
  useEffect(() => {
    window.setAiaSidebarMode = (mode) => {
      setSidebarMode(mode || 'data');
      // In this project, sidebar only shows if activeDocData is set
      if (!activeDocData) {
        setActiveDocData({ is_virtual_trigger: true });
      }
    };
    return () => { delete window.setAiaSidebarMode; };
  }, [activeDocData]);

  // ============================================================================
  // CLEAR CHAT - RE-INITIALIZE
  // ============================================================================

  // eslint-disable-next-line no-unused-vars
  const handleClearChat = () => {
    if (window.confirm(t('ui.clearChatConfirm'))) {
      setMessages([]);
      setValidatedDocs([]); // Clear validated docs too
      setActiveDocData(null); // Clear active doc data
      setSidebarMode('library'); // Reset sidebar to library view
      initializeChat();
    }
  };

  const removeFile = (index) => {
    if (typeof index !== 'number') {
      setUploadedFiles([]);
      setUploadedFile(null);
      if (fileInputRef.current) fileInputRef.current.value = '';
      return;
    }
    setUploadedFiles(prev => {
      const next = prev.filter((_, i) => i !== index);
      setUploadedFile(next[0] || null);
      if (next.length === 0 && fileInputRef.current) fileInputRef.current.value = '';
      return next;
    });
  };

  // ── v4: Mismatch role assignment ──────────────────────────────────────────
  const handleMismatchRoleSelected = async (role) => {
    try {
      const res = await assignMismatchRole({
        email: user?.email,
        extracted_name: mismatch.extractedName,
        extracted_business: mismatch.extractedBiz,
        assigned_role: role,
      });

      const confirmMsgId = 'mismatch-confirm-' + Date.now();
      const content = res.data?.message || t('ui.mismatchAdded', { name: mismatch.extractedName, role: role === 'authorized_signatory' ? t('ui.authorizedSignatory') : t('ui.keyIndividual') });

      setMessages(prev => [...prev, {
        id: confirmMsgId,
        role: 'assistant',
        content,
        timestamp: new Date().toISOString()
      }]);
      setCurrentStepId(confirmMsgId);
      setMismatch(m => ({ ...m, open: false, roleConfirmed: true }));
      toast.success(t('chat.roleAssigned'));
    } catch (e) {
      logger.warn('[MISMATCH] Failed to assign role:', e);
      toast.error(t('chat.roleAssignFailed'));
    }
  };

  // ============================================================================
  // DOCUMENT PREVIEW
  // ============================================================================

  const openPreview = async (doc) => {
    logger.log('[PREVIEW] Opening document:', doc);

    if (doc.previewUrl && doc.previewUrl.startsWith('blob:')) {
      logger.log('[PREVIEW] Using active session JSON blob URL');
      setPreviewDocument(doc);
      setSidebarMode('preview');
      return;
    }

    // doc.previewUrl (when present) already points at /chatupload/get-document/
    // {email}/{doc_type}/{filename} — the doc-type-aware endpoint that knows
    // how to find a document under its actual saved name (documents get
    // renamed to a prefix+ref_no form at save time, e.g. "MOA.pdf" as
    // uploaded is saved as "MOA-{ref_no}.pdf" — there's no string
    // relationship between the two). Always falling back to
    // /chatupload/preview/{email}/{doc.name} (searches by the ORIGINAL
    // filename only, with no doc_type to work from) is what made every
    // preview fail regardless of session, live or reloaded — that endpoint
    // can never find a renamed file. Only fall back to it when a message
    // genuinely has no previewUrl at all (very old restored history).
    let endpoint;
    if (doc.previewUrl) {
      // previewUrl is a full path already including the API base prefix
      // (config.API_BASE_PATH on the backend, matching api.defaults.baseURL
      // here by default) — strip that prefix back off so it's relative to
      // this axios instance's own baseURL instead of being doubled.
      endpoint = doc.previewUrl.startsWith(api.defaults.baseURL)
        ? doc.previewUrl.slice(api.defaults.baseURL.length)
        : doc.previewUrl;
    } else if (doc.name) {
      endpoint = `/chatupload/preview/${encodeURIComponent(user.email)}/${encodeURIComponent(doc.name)}`;
    }

    if (endpoint) {
      try {
        logger.log('[PREVIEW] Fetching document via:', endpoint);

        const response = await api.get(endpoint, {
          responseType: 'blob'
        });

        const blobUrl = URL.createObjectURL(response.data);

        const previewDoc = {
          ...doc,
          previewUrl: blobUrl,
          type: response.data.type || doc.type
        };

        logger.log('[PREVIEW] Document fetched successfully');
        setPreviewDocument(previewDoc);
        setSidebarMode('preview');

      } catch (error) {
        logger.error('[PREVIEW] Failed to fetch document:', error);
        toast.error(t('chat.previewFailed'));
      }
    }
  };

  const closePreview = () => {
    setSidebarMode('data');
    setPreviewDocument(null);
  };

  // Language is now changed via <LanguageToggle /> (writes straight to
  // LanguageContext); selectedLanguage above just mirrors it. The old
  // handleLanguageChange handler that used to live here was never wired to
  // any element — see docs/multilingual-support-plan.html, Finding 1.

  // successDocs memo was here, now moved up to fix ReferenceError

  return (
    <div className="flex h-screen bg-gray-50 overflow-hidden font-sans">
      <Sidebar
        onSectionClick={(sectionId) => {
          setActiveChatFilter(sectionId);
          if (sectionId === 'declaration') {
            setActiveDocData({ isVirtual: true, documentType: 'summary_declaration', name: 'Summary Declaration' });
            setSidebarMode('data');
          }
        }}
        activeSection={effectiveFilter}
      />

      <DocumentPreviewModal
        isOpen={showPreview}
        onClose={closePreview}
        document={previewDocument}
      />

      <FatcaModal
        isOpen={showFatcaModal}
        onClose={() => setShowFatcaModal(false)}
        onConfirmed={handleFatcaConfirmed}
        userEmail={user?.email}
      />

      {/* ── v4: Mismatch Modal ─────────────────────────────────────────────── */}
      {mismatch.open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-brand-primary bg-opacity-50 p-4" onClick={() => setMismatch(m => ({ ...m, open: false }))}>
          <div className="bg-white rounded-2xl shadow-2xl max-w-lg w-full overflow-hidden" onClick={e => e.stopPropagation()}>
            <div className="bg-brand-primary px-6 py-4">
              <h2 className="text-white font-bold text-lg">{t('ui.mismatchTitle')}</h2>
              <p className="text-amber-100 text-sm mt-0.5">{t('ui.mismatchBody')}</p>
            </div>
            <div className="p-6 space-y-4">
              <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm space-y-1">
                {mismatch.extractedName && (
                  <p><span className="font-medium text-gray-700">{t('ui.extractedName')}</span> <span className="text-gray-900">{mismatch.extractedName}</span></p>
                )}
                {mismatch.extractedBiz && (
                  <p><span className="font-medium text-gray-700">{t('ui.extractedBusiness')}</span> <span className="text-gray-900">{mismatch.extractedBiz}</span></p>
                )}
              </div>
              <p className="text-gray-700 text-sm font-medium">{t('ui.addIndividualAs')}</p>
              <div className="space-y-2">
                {[
                  { value: 'authorized_signatory', label: t('ui.authorizedSignatory'), desc: t('ui.authorizedSignatoryDesc') },
                  { value: 'key_individual', label: t('ui.keyIndividual'), desc: t('ui.keyIndividualDesc') },
                ].map(opt => (
                  <button
                    key={opt.value}
                    onClick={() => handleMismatchRoleSelected(opt.value)}
                    className="w-full flex items-start gap-3 p-3 rounded-lg border-2 border-gray-200 hover:border-indigo-300 text-start transition-colors hover:bg-indigo-50"
                  >
                    <div className="w-4 h-4 rounded-full border-2 border-gray-400 mt-0.5 flex-shrink-0" />
                    <div>
                      <p className="text-sm font-semibold text-gray-900">{opt.label}</p>
                      <p className="text-xs text-gray-500">{opt.desc}</p>
                    </div>
                  </button>
                ))}
              </div>
              <button onClick={() => setMismatch(m => ({ ...m, open: false }))} className="w-full py-2.5 border border-gray-300 rounded-lg text-sm font-medium text-gray-700 hover:bg-gray-50">
                {t('ui.cancel')}
              </button>
            </div>
          </div>
        </div>
      )}

      <div className={`flex-1 ml-64 rtl:ml-0 rtl:mr-64 flex bg-white relative`}>
        {/* LEFT: Chat Section */}
        <div className={`flex flex-col h-full bg-white transition-all duration-500 ease-in-out border-r border-gray-100 ${activeDocData ? (isFinalDeclarationStep ? 'w-0 opacity-0 overflow-hidden border-none' : 'w-full lg:w-[50%]') : 'w-full'}`}>
          <div className="w-full flex flex-col h-full relative">
            {/* Razorpay Minimal Header */}
            <header className="px-8 py-6 border-b border-gray-50 flex items-center justify-between bg-white z-10">
              <div className="flex items-center gap-3">
                <div className="p-1 px-2 bg-gray-900 text-[10px] font-black text-white rounded italic">R</div>
                <h1 className="text-sm font-bold text-gray-800 tracking-tight">{t('onboarding.needHelp')}</h1>
              </div>
              <div className="flex items-center gap-3">
                <LanguageToggle />
                <div className="w-8 h-8 rounded-full bg-gray-900 flex items-center justify-center text-[10px] font-black text-white shadow-lg shadow-gray-200 border-2 border-white ring-1 ring-gray-100">
                  {getUserInitials(user)}
                </div>
              </div>
            </header>

            {/* Messages Container */}
            <main
              className="flex-1 overflow-y-auto bg-gray-50/40 custom-scrollbar"
            >
              <div className="px-8 py-6 space-y-4">
                {/* Phase 2 (docs/language-mirroring-verdict.html): brief banner
                    while history is being re-fetched/re-translated after a
                    toggle switch. On a cache hit (already translated once
                    this conversation) the backend answers fast enough that
                    this barely flashes -- the "instant after the first time"
                    behaviour the plan calls for falls naturally out of that,
                    rather than being tracked as a separate cache-hit signal. */}
                {isTranslatingHistory && (
                  <div className="flex items-center justify-center gap-2 text-xs text-gray-400 py-2">
                    <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                    <span>{t('chat.translatingConversation')}</span>
                  </div>
                )}
                <AnimatePresence initial={false}>
                  {sortedFilteredMessages.map((msg, fIdx) => {
                    const isAssistant = msg.role === 'assistant';
                    if (isAssistant && isIdentityTab) {
                      logger.log(`[RENDER-DEBUG] Msg ID: ${msg.id}, hasExtractedData: ${!!msg.extractedData}, docType: ${msg.documentType}, content: ${msg.content?.substring(0, 30)}...`);
                    }

                    const originalIndex = processedMessages.indexOf(msg);


                    return (
                      <motion.div
                        key={msg.id || fIdx}
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                      >
                        <div className={`
                          flex flex-col gap-2
                          ${msg.role === 'user' ? 'max-w-[80%] items-end' : 'max-w-[75%] items-start'}
                        `}>
                          {/* Bubble */}
                          {!msg.onboardingComplete && (
                            <div className={`
                              px-5 py-3.5 rounded-2xl text-[15px] leading-relaxed
                              ${msg.role === 'user'
                                ? 'bg-brand-primary text-white shadow-md shadow-blue-100/50 rounded-tr-none'
                                : 'bg-white text-gray-800 shadow-sm border border-gray-100 rounded-tl-none'
                              }
                            `}>
                              <div className="flex items-center gap-4">
                                <MessageContent
                                  {...msg}
                                  onUploadTrigger={() => fileInputRef.current?.click()}
                                  currentStepId={currentStepId}
                                  membersInfo={membersInfo}
                                />
                                {msg.isUpload && msg.documentMetadata && (
                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setActiveDocData(msg);
                                      openPreview(msg.documentMetadata);
                                    }}
                                    className="flex-shrink-0 flex items-center justify-center p-2 bg-white/20 hover:bg-white/30 text-white rounded-xl transition-all border border-white/10 group shadow-sm"
                                    title={t('ui.previewDocument')}
                                  >
                                    <Eye className="h-4 w-4 group-hover:scale-110 transition-transform" />
                                  </button>
                                )}
                              </div>
                            </div>
                          )}

                          {/* "Translated from X" caption -- Phase 1 polish, the
                              same honest convention LinkedIn/X use so patching
                              a user's own words in place doesn't read as a
                              glitch. Only ever set on role:'user' messages,
                              by the was_translated patch in handleSendMessage. */}
                          {msg.role === 'user' && msg.wasTranslated && (
                            <span className="text-[11px] text-gray-400 px-1">
                              {t('ui.translatedFrom', { lang: t(`ui.${TRANSLATED_FROM_KEY[msg.detectedLanguage] || TRANSLATED_FROM_KEY.unknown}`) })}
                            </span>
                          )}

                          {/* Interactive Triggers (Outside the bubble) */}
                          {/*
                            C5 — one boundary per message, wrapping that
                            message's card region only. A card that throws
                            during render degrades to an inline notice; the
                            chat, the input and every other message survive.
                            resetKey is the message id, so a later message
                            never inherits an earlier one's failure.

                            This catches render-time exceptions only. It does
                            not catch event-handler or async failures — see
                            the header of OnboardingErrorBoundary.jsx.
                          */}
                          <OnboardingErrorBoundary
                            region={`msg-${msg.id || fIdx}`}
                            resetKey={msg.id || fIdx}
                            label="This step"
                          >
                          <div className="w-full">
                            {msg.role === 'assistant' && msg.suggestions && msg.suggestions.length > 0 && (
                              <div className="flex flex-wrap gap-2 mt-2">
                                {msg.suggestions.map((s, idx) => (
                                  <button
                                    key={idx}
                                    onClick={() => handleSuggestionClick(s)}
                                    className="px-4 py-2 bg-white/60 hover:bg-brand-primary hover:text-white border border-blue-100 rounded-xl text-[13px] font-semibold text-brand-primary transition-all shadow-sm hover:shadow-md"
                                  >
                                    {s}
                                  </button>
                                ))}
                              </div>
                            )}

                            {(msg.fatcaTrigger || msg.pepTrigger || (msg.stage === 'fatca' && !messages.some(m => m.fatcaTrigger) && originalIndex === messages.findLastIndex(m => m.stage === 'fatca')) || (msg.stage === 'pep' && !messages.some(m => m.pepTrigger) && originalIndex === messages.findLastIndex(m => m.stage === 'pep'))) && isAdditionalTab && (
                              <div className="mt-3 space-y-3 animate-in fade-in slide-in-from-top-2 duration-500">
                                <div className="flex flex-col gap-3">
                                  {(msg.fatcaTrigger || (msg.stage === 'fatca' && !messages.some(m => m.fatcaTrigger) && originalIndex === messages.findLastIndex(m => m.stage === 'fatca'))) && (
                                    <div className="w-full">
                                      <FatcaInlineCard
                                        userEmail={user?.email}
                                        onConfirmed={(fData) => {
                                          setFatcaData(fData);
                                          setActiveDocData({ isVirtual: true });
                                          setSidebarMode('data');
                                          // ✅ FIX: explicitly pin the next tab instead of clearing
                                          // activeChatFilter (setActiveChatFilter(null)), which used
                                          // to hand control back to getCurrentLiveSection(). That
                                          // function trusts backendStage as ground truth, but the
                                          // backend's document_stage field (stage_table.py) has no
                                          // concept of FATCA/PEP/compliance — it stays frozen at
                                          // so_member_eids/member_eids for the rest of the journey.
                                          // Whenever that stale value wasn't recognized as
                                          // "post-corporate" the guard below it forced the tab back
                                          // to Corporate right after every FATCA submit. Mirrors the
                                          // ProductPackageCard pattern, which never had this bug
                                          // because it already set the tab explicitly.
                                          if (fData.self_declaration_trigger) {
                                            setMessages(prev => {
                                              const last = prev[prev.length - 1];
                                              return [...prev.slice(0, -1), { ...last, selfDeclTrigger: true }];
                                            });
                                            setActiveChatFilter('declaration');
                                            setIsDeclarationEnabled(true);
                                          } else {
                                            if (fData.pep_trigger) {
                                              setMessages(prev => {
                                                const last = prev[prev.length - 1];
                                                return [...prev.slice(0, -1), { ...last, pepTrigger: true }];
                                              });
                                            } else if (fData.product_package_trigger) {
                                              setMessages(prev => {
                                                const last = prev[prev.length - 1];
                                                return [...prev.slice(0, -1), { ...last, productPackageTrigger: true }];
                                              });
                                            }
                                            setActiveChatFilter('additional');
                                          }
                                        }}
                                      />
                                    </div>
                                  )}
                                  {(msg.pepTrigger || (msg.stage === 'pep' && !messages.some(m => m.pepTrigger) && originalIndex === messages.findLastIndex(m => m.stage === 'pep'))) && (
                                    <div className="w-full">
                                      <PepInlineCard
                                        userEmail={user?.email}
                                        onConfirmed={(pData) => {
                                          setPepData(pData);
                                          setActiveDocData({ isVirtual: true });
                                          setSidebarMode('data');
                                          // PEP → Product Package → Self-Declaration chain
                                          // ✅ FIX: same issue as FatcaInlineCard above — pin the tab
                                          // explicitly instead of setActiveChatFilter(null), which
                                          // relied on backendStage (frozen at so_member_eids/
                                          // member_eids post-identity) and bounced back to Corporate.
                                          if (pData.self_declaration_trigger) {
                                            // Idempotency fallback: package already saved, skip straight to self-decl
                                            setMessages(prev => {
                                              const last = prev[prev.length - 1];
                                              return [...prev.slice(0, -1), { ...last, selfDeclTrigger: true }];
                                            });
                                            setActiveChatFilter('declaration');
                                            setIsDeclarationEnabled(true);
                                          } else {
                                            if (pData.product_package_trigger) {
                                              setMessages(prev => {
                                                const last = prev[prev.length - 1];
                                                return [...prev.slice(0, -1), { ...last, productPackageTrigger: true }];
                                              });
                                            }
                                            setActiveChatFilter('additional');
                                          }
                                        }}
                                      />
                                    </div>
                                  )}
                                </div>
                              </div>
                            )}
                            {(msg.productPackageTrigger || msg.product_package_trigger || msg.package_trigger || (msg.stage === 'product_package' && !messages.some(m => m.productPackageTrigger || m.product_package_trigger) && originalIndex === messages.findLastIndex(m => m.stage === 'product_package'))) && isAdditionalTab && (
                              <div className="mt-2 animate-in fade-in slide-in-from-top-2 duration-500">
                                <ProductPackageCard
                                  userEmail={user?.email}
                                  onConfirmed={(pkgData) => {
                                    logger.log('[ProductPackage] Selected:', pkgData);
                                    setProductPackageData(pkgData);
                                    setActiveDocData({
                                      id: 'product-package-report',
                                      documentType: 'PRODUCT_PACKAGE',
                                      name: 'Product Package Selection',
                                      extractedData: pkgData,
                                      isVirtual: true
                                    });
                                    setSidebarMode('data');
                                    window.dispatchEvent(new Event('compliance-updated'));
                                    if (pkgData.self_declaration_trigger) {
                                      setMessages(prev => {
                                        const last = prev[prev.length - 1];
                                        return [...prev.slice(0, -1), {
                                          ...last,
                                          selfDeclTrigger: pkgData.self_declaration_trigger || true,
                                        }];
                                      });
                                      // Switch to declaration tab so SelfDeclarationCard renders
                                      setActiveChatFilter('declaration');
                                      setIsDeclarationEnabled(true);
                                    } else {
                                      // ✅ FIX: self_declaration_trigger wasn't set — stay pinned to
                                      // Additional (this card only ever renders inside the
                                      // Additional tab, see isAdditionalTab above) instead of
                                      // clearing the filter and risking the same stale-backendStage
                                      // revert-to-Corporate race fixed elsewhere in this file.
                                      setActiveChatFilter('additional');
                                    }
                                  }}
                                />
                              </div>
                            )}


                            {msg.role === 'assistant' && (msg.ownershipTypeTrigger || msg.ownershipTypeCompleted) && originalIndex === messages.findLastIndex(m => m.ownershipTypeTrigger || m.ownershipTypeCompleted) && (
                              <OwnershipTypeCard
                                userEmail={user?.email}
                                isCompleted={!!msg.ownershipTypeCompleted}
                                savedChoice={msg.ownershipTypeChoice}
                                onSaved={handleOwnershipTypeSaved}
                              />
                            )}

                            {msg.role === 'assistant' && getMessageSection(msg) === 'user' && (msg.asKiTrigger || msg.moaAsTrigger || msg.stage === 'member_eids' || msg.toStage === 'member_eids') && originalIndex === messages.findLastIndex(m => m.role === 'assistant' && getMessageSection(m) === 'user' && (m.asKiTrigger || m.moaAsTrigger || m.stage === 'member_eids' || m.toStage === 'member_eids')) && (
                              <div className="mt-3">
                                <AsKiManagementCard
                                  {...msg}
                                  key={`aski-${msg.id}-${msg.asSelectionCompleted || 'open'}`}
                                  isCompleted={msg.asSelectionCompleted}
                                  initialIndividuals={msg.selectedIndividuals}
                                  userEmail={user?.email}
                                  membersInfo={membersInfo}
                                  messages={messages}
                                  preloadedMembers={
                                    msg.selectedIndividuals?.length > 0
                                      ? msg.selectedIndividuals
                                      : (msg.moaMembers?.length > 0
                                        ? msg.moaMembers
                                        : (msg.soOwner ? [msg.soOwner] : []))
                                  }
                                  memberSource={msg.soOwner ? 'SO_OWNER' : 'MOA_EXTRACTED'}
                                  onKiSavedCallback={kiSavedCallbackBridge.current}
                                  onProceed={handleAsSelection}
                                />
                              </div>
                            )}

                            {msg.complianceHistoryTrigger && originalIndex === messages.findLastIndex(m => m.complianceHistoryTrigger) && (
                              <div className="mt-3">
                                <ComplianceHistoryToggle
                                  history={complianceHistory}
                                  userEmail={user?.email}
                                />
                              </div>
                            )}

                            {msg.role === 'assistant' && msg.id === 'ejari-analysis' && originalIndex === messages.findLastIndex(m => m.id === 'ejari-analysis') && (
                              <div className="mt-3">
                                <RoleMismatchSelector
                                  options={[
                                    { label: t('ui.primaryMember'), value: 'primary', desc: t('ui.primaryMemberDesc') },
                                    { label: t('ui.secondaryMember'), value: 'secondary', desc: t('ui.secondaryMemberDesc') },
                                    { label: t('ui.generalEmployee'), value: 'employee', desc: t('ui.generalEmployeeDesc') }
                                  ]}
                                  onSelect={(role) => {
                                    setMessages(prev => [...prev, {
                                      role: 'assistant',
                                      content: t('chat.roleUpdated', { role }),
                                      kiLoopPrompt: true,
                                    }]);
                                  }}
                                />
                              </div>
                            )}

                            {/* KiLoopCard restored as per request */}
                            {msg.role === 'assistant' && (msg.kiLoopPrompt || msg.ki_loop_prompt) && originalIndex === messages.findLastIndex(m => m.role === 'assistant' && (m.kiLoopPrompt || m.ki_loop_prompt)) && (
                              <div className="mt-3" key={`ki-loop-${msg.id}-${msg.kiLoopCompleted || 'open'}`}>
                                <KiLoopCard
                                  isCompleted={msg.kiLoopCompleted}
                                  initialChoice={msg.kiLoopChoice}
                                  onAddAnother={handleKiLoopAddAnother}
                                  onProceed={handleKiLoopProceed}
                                />
                              </div>
                            )}

                            {msg.isAiKiEidCapture && msg.aiKiExtractedData && !msg.aiKiCaptured && (
                              <div className="mt-3">
                                <KiRoleAssignCard
                                  userEmail={user?.email}
                                  extractedData={msg.aiKiExtractedData}
                                  documentId={msg.aiKiDocumentId}
                                  onSaved={(savedKi) => {
                                    handleKISaved({ ki: savedKi });
                                    const _savedName = savedKi?.display_name || t('report.roles.individual');
                                    const _savedRole = savedKi?.ki?.is_authorised_signatory
                                      ? t('report.roles.as')
                                      : t('report.roles.member');
                                    setMessages(prev => {
                                      const newMsgs = [...prev];
                                      // Mark the capture message as handled so card doesn't re-render
                                      const captureIdx = newMsgs.findLastIndex(m => m.id === msg.id);
                                      if (captureIdx !== -1) {
                                        newMsgs[captureIdx] = { ...newMsgs[captureIdx], aiKiCaptured: true };
                                      }
                                      // ✅ NEW: Push KiDetailsCard trigger instead of going straight to loop
                                      // We also attach the role map to the message so it persists in history
                                      const roleKey = _savedName.trim().toUpperCase();
                                      const roleVal = savedKi?.ki?.is_authorised_signatory ? 'AS' : 'MEMBER';

                                      return [...newMsgs, {
                                        id: 'ki-details-trigger-' + Date.now(),
                                        role: 'assistant',
                                        content: t('chat.kiAddedComplete', { name: _savedName, role: _savedRole }),
                                        timestamp: new Date().toISOString(),
                                        kiDetailsTrigger: true,
                                        kiDetailsName: _savedName,
                                        kiDetailsRole: _savedRole,
                                        member_role_map: { [roleKey]: roleVal },
                                        stage: 'user',
                                      }];

                                    });
                                  }}
                                />
                              </div>
                            )}

                            {/* ✅ NEW: KiDetailsCard — Email+OTP, Phone, Share% after role assigned */}
                            {msg.kiDetailsTrigger && !msg.kiDetailsCaptured && (
                              <div className="mt-3">
                                <KiDetailsCard
                                  userEmail={user?.email}
                                  kiName={msg.kiDetailsName}
                                  kiRole={msg.kiDetailsRole}
                                  onConfirmed={(details) => {
                                    // ✅ FIX: contact details are always captured mid-Identity —
                                    // pin the tab directly instead of setActiveChatFilter(null),
                                    // which risked the same stale-backendStage revert-to-Corporate
                                    // race fixed at the other Identity/KI handlers in this file.
                                    setActiveChatFilter('user');

                                    setMessages(prev => {
                                      const newMsgs = [...prev];
                                      // Mark KiDetailsCard as captured so it doesn't re-render
                                      const detIdx = newMsgs.findLastIndex(m => m.id === msg.id);
                                      if (detIdx !== -1) {
                                        newMsgs[detIdx] = { ...newMsgs[detIdx], kiDetailsCaptured: true };
                                      }
                                      // Push kiLoopPrompt with ownershipMap + kiContactMap for report sync
                                      return [...newMsgs, {
                                        id: 'ki-loop-prompt-' + Date.now(),
                                        role: 'assistant',
                                        content: details.message || t('ui.addAnotherAsKi'),
                                        timestamp: new Date().toISOString(),
                                        kiLoopPrompt: true,
                                        ownershipMap: details.ownershipMap || {},
                                        kiContactMap: details.kiContactMap || {},
                                        stage: 'user',
                                      }];
                                    });
                                  }}
                                />
                              </div>
                            )}

                            {msg.selfDeclTrigger && effectiveFilter === 'declaration' && originalIndex === messages.findLastIndex(m => m.selfDeclTrigger) && (
                              <div className="mt-3">
                                <SelfDeclarationCard
                                  userEmail={user?.email}
                                  isEnabled={isDeclarationEnabled || !!productPackageData}
                                  onConfirmed={(data) => {
                                    handleSelfDeclConfirmed(data);
                                    handleOnboardingComplete();
                                  }}
                                />
                              </div>
                            )}

                            {msg.onboardingComplete && (
                              <div className="mt-3">
                                <OnboardingSuccessCard content={msg.content} />
                              </div>
                            )}
                          </div>
                          </OnboardingErrorBoundary>

                          {isOnboardingComplete && <SuccessConfetti />}

                          {msg.extractedData && (
                            <button
                              onClick={() => {
                                setActiveDocData(msg);
                                setSidebarMode('data');
                              }}
                              className="mt-1 flex items-center gap-2 px-3 py-1 bg-emerald-50 text-emerald-600 rounded-full text-[10px] font-black uppercase tracking-widest border border-emerald-100 hover:bg-emerald-100 transition-colors shadow-sm"
                            >
                              <ShieldCheck className="h-3 w-3" />
                              {msg.documentType
                                ? t('ui.verificationInsights', { doc: translateDocName(t, msg.documentType) })
                                : t('ui.securityReportAttached')}
                            </button>
                          )}
                        </div>
                      </motion.div>
                    );
                  })}
                </AnimatePresence>

                {/* ✅ Task 10: Fallback for empty Additional tab after completion */}
                {isOnboardingComplete && isAdditionalTab && (
                  <div className="space-y-6 mt-4">
                    {!sortedFilteredMessages.some(m => m.fatcaTrigger || m.isFatcaConfirmed || logicText(m).includes('fatca')) && fatcaData && (
                      <div className="animate-in fade-in slide-in-from-bottom-4 duration-500">
                        <FATCAReportBlock data={fatcaData} isCompleted={true} onEdit={() => setShowFatcaModal(true)} />
                      </div>
                    )}
                    {!sortedFilteredMessages.some(m => m.pepTrigger || m.isPepConfirmed || logicText(m).includes('pep')) && pepData && (
                      <div className="animate-in fade-in slide-in-from-bottom-4 duration-500 delay-150">
                        <PEPReportBlock data={pepData} />
                      </div>
                    )}
                    {!sortedFilteredMessages.some(m => m.productPackageTrigger || m.isProductPackageConfirmed || logicText(m).includes('package')) && productPackageData && (
                      <div className="animate-in fade-in slide-in-from-bottom-4 duration-500 delay-300">
                        <ProductPackageReportBlock data={productPackageData} />
                      </div>
                    )}
                  </div>
                )}

                {isLoading && (
                  <motion.div
                    initial={{ opacity: 0, y: 5 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="flex justify-start items-center gap-3 px-4 mb-4"
                  >
                    {/* Assistant Avatar */}
                    <div className="w-8 h-8 rounded-full bg-gray-900 flex items-center justify-center text-[10px] font-black text-white shadow-lg shadow-gray-200 border-2 border-white ring-1 ring-gray-100">
                      AI
                    </div>

                    {/* Pulsing Dots Bubble */}
                    <div className="flex gap-1.5 bg-white p-3.5 px-5 rounded-[22px] rounded-tl-none border border-gray-100 shadow-xl shadow-gray-200/40">
                      <div className="w-1.5 h-1.5 bg-brand-primary rounded-full animate-bounce" />
                      <div className="w-1.5 h-1.5 bg-brand-primary rounded-full animate-bounce [animation-delay:0.2s]" />
                      <div className="w-1.5 h-1.5 bg-brand-primary rounded-full animate-bounce [animation-delay:0.4s]" />
                    </div>
                  </motion.div>
                )}
                <div ref={messagesEndRef} />
              </div>
            </main>

            {/* Minimal Input Bar */}
            <div className="px-8 py-8 bg-white border-t border-gray-50">
              <div className="max-w-3xl mx-auto">
                <div className="relative group bg-white border-2 border-gray-100 rounded-[28px] focus-within:border-indigo-500 transition-all duration-300 shadow-sm overflow-hidden">
                  <input
                    ref={fileInputRef}
                    type="file"
                    multiple
                    onChange={handleFileSelect}
                    className="hidden"
                  />

                  <div className="flex items-center px-6 gap-2">
                    {uploadedFiles.length > 0 && (
                      <div className="flex items-center gap-1.5 flex-wrap">
                        {uploadedFiles.map((f, i) => (
                          <div key={`${f.name}-${i}`} className="flex items-center gap-2 px-3 py-1.5 bg-blue-50 border border-blue-100 rounded-xl animate-in fade-in zoom-in duration-300">
                            <File className="h-3.5 w-3.5 text-brand-primary" />
                            <span className="text-[11px] font-black text-blue-900 truncate max-w-[120px]">{f.name}</span>
                            <button onClick={() => removeFile(i)} className="p-0.5 hover:bg-blue-100 rounded-full transition-colors text-blue-400 hover:text-rose-500">
                              <X className="h-3 w-3" />
                            </button>
                          </div>
                        ))}
                      </div>
                    )}
                    <input
                      type="text"
                      value={input}
                      onChange={(e) => setInput(e.target.value)}
                      onKeyPress={handleKeyPress}
                      placeholder={uploadedFiles.length > 0 ? t('ui.addMessage') : t('ui.typeResponse')}
                      className="flex-1 bg-transparent border-none focus:ring-0 py-6 text-[15px] font-medium text-gray-800 placeholder:text-gray-300"
                    />

                    <div className="flex items-center gap-3">
                      <button
                        onClick={() => fileInputRef.current?.click()}
                        className="flex items-center justify-center h-10 w-10 text-gray-400 hover:text-brand-primary hover:bg-blue-50 rounded-xl transition-all group"
                        title={t('ui.uploadFileTitle')}
                      >
                        <Paperclip className="h-5 w-5 group-hover:scale-110 transition-transform" />
                      </button>

                      <button
                        onClick={uploadedFiles.length > 1 ? handleBulkUpload : (uploadedFile ? handleUploadDocument : handleSendMessage)}
                        disabled={!input.trim() && !uploadedFile}
                        className={`h-10 w-10 flex items-center justify-center rounded-xl transition-all ${input.trim() || uploadedFile ? 'bg-brand-primary shadow-lg shadow-indigo-300 scale-105' : 'bg-gray-100 text-gray-400'}`}
                      >
                        <Send className="h-4 w-4 text-white" />
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* RIGHT: Document Intelligence Section */}
        <AnimatePresence>
          {activeDocData && (
            <motion.div
              initial={{ x: '100%', opacity: 0 }}
              animate={{ x: 0, opacity: 1 }}
              exit={{ x: '100%', opacity: 0 }}
              transition={{ type: 'spring', damping: 25, stiffness: 200 }}
              className={`absolute right-0 top-0 h-full bg-white border-l border-gray-100 flex flex-col shadow-2xl z-[100] transition-all duration-500 ${isFinalDeclarationStep ? 'w-full' : 'w-full lg:w-[50%]'}`}
            >
              {/* Security Hub Header */}
              <div className="px-8 py-3 border-b border-gray-50 bg-gray-900 text-white flex items-center justify-between font-sans min-h-[56px]">
                <div className="flex bg-white/10 p-1 rounded-xl gap-1">
                  <button
                    onClick={() => setSidebarMode('data')}
                    className={`px-3 py-1.5 text-[10px] font-black uppercase rounded-lg transition-all ${sidebarMode === 'data' ? 'bg-brand-primary shadow-lg shadow-indigo-900/40' : 'text-gray-400 hover:text-white'
                      }`}
                  >
                    {t('ui.tabDetails')}
                  </button>
                  <button
                    onClick={() => setSidebarMode('vault')}
                    className={`px-3 py-1.5 text-[10px] font-black uppercase rounded-lg transition-all ${sidebarMode === 'vault' ? 'bg-brand-primary shadow-lg shadow-indigo-900/40' : 'text-gray-400 hover:text-white'
                      }`}
                  >
                    {t('ui.tabVault')}
                  </button>
                  <button
                    onClick={() => {
                      if (activeDocData?.documentMetadata || previewDocument) {
                        openPreview(activeDocData?.documentMetadata || previewDocument);
                      }
                      setSidebarMode('preview');
                    }}
                    className={`px-3 py-1.5 text-[10px] font-black uppercase rounded-lg transition-all ${sidebarMode === 'preview' ? 'bg-brand-primary shadow-lg shadow-indigo-900/40' : 'text-gray-400 hover:text-white'
                      }`}
                  >
                    {t('ui.tabFileView')}
                  </button>
                  <button
                    onClick={() => setSidebarMode('reupload')}
                    className={`px-3 py-1.5 text-[10px] font-black uppercase rounded-lg transition-all ${sidebarMode === 'reupload' ? 'bg-brand-primary shadow-lg shadow-indigo-900/40' : 'text-gray-400 hover:text-white'
                      }`}
                  >
                    {t('ui.tabReupload')}
                  </button>
                </div>
                <button
                  onClick={() => {
                    setActiveDocData(null);
                    if (effectiveFilter === 'declaration') {
                      setSidebarDismissed(true);
                    }
                  }}
                  className="p-2 hover:bg-white/10 rounded-full transition-all"
                >
                  <X className="h-5 w-5 text-gray-400" />
                </button>
              </div>

              {/* Panes */}
              <div className="flex-1 overflow-hidden flex flex-col">
                {sidebarMode === 'data' ? (
                  <div className="flex-1 flex flex-col overflow-hidden bg-white">
                    <div
                      ref={sidebarScrollRef}
                      className="flex-1 overflow-y-auto custom-scrollbar p-6"
                    >
                      {/* Unified Intelligence Hub Container */}
                      <div className="mt-4 flex flex-col">
                        {/* Report Header */}
                        <div className="flex items-center justify-between mb-4 px-1">
                          <div>
                            <h3 className="text-sm font-black text-slate-800 tracking-tight leading-none mb-1 text-blue-900 uppercase">{t('report.title')}</h3>
                            {/* <p className="text-[10px] font-black text-slate-400 uppercase tracking-widest italic">Verification Hub · {categories.length}/4 Categories Verified</p> */}
                          </div>
                        </div>

                        <div className="space-y-6 mb-8">
                          {(() => {
                            if (categories.length === 0) {
                              return (
                                <div className="flex flex-col items-center justify-center p-12 opacity-40 border-2 border-dashed border-slate-100 rounded-[40px]">
                                  <AlertCircle className="h-10 w-10 text-slate-300 mb-4" />
                                  <p className="text-[11px] font-black text-slate-400 uppercase tracking-widest text-center">{t('report.awaiting')}</p>
                                </div>
                              );
                            }

                            const categoryColors = {
                              'Business Details': 'bg-brand-primary',
                              'User Details': 'bg-amber-500',
                              'Additional Details': 'bg-indigo-600',
                              'Declaration': 'bg-emerald-500'
                            };

                            return categories.map((cat, catIdx) => {
                              const dividerColor = categoryColors[cat.title] || 'bg-slate-200';
                              return (
                                <div key={catIdx} className="space-y-4">
                                  <div className="flex items-center gap-3 px-1">
                                    <div className={`h-6 w-6 rounded-lg flex items-center justify-center ${dividerColor.replace('bg-', 'bg-')}/10`}>
                                      <cat.icon className={`h-3.5 w-3.5 ${dividerColor.replace('bg-', 'text-')}`} />
                                    </div>
                                    {/* cat.title stays an English id (it keys categoryColors); only the heading is translated */}
                                    <h4 className="text-[11px] font-black text-slate-400 uppercase tracking-[0.2em]">{t(`report.sections.${REPORT_SECTION_KEYS[cat.title] || 'business'}`)}</h4>
                                  </div>

                                  <div className="border border-slate-200 rounded-3xl shadow-sm overflow-hidden bg-white mb-2">
                                    <div className="divide-y divide-slate-50">
                                      {cat.items.map((doc, idx) => {
                                        const type = (doc.documentType || '').toLowerCase();
                                        let label = doc.documentType?.replace(/_/g, ' ') || t('report.document');
                                        let Icon = FileText;
                                        let isDeclaration = doc.isVirtual && type === 'summary_declaration';
                                        let accentColor = 'bg-slate-800';
                                        logger.log('[SIDEBAR-ROUTING] Item:', { type, docType: doc.documentType });

                                        if (type.includes('coi') || type.includes('incorporation')) {
                                          label = t('report.docs.coi'); // Changed priority to check COI first
                                          Icon = ShieldCheck;
                                          accentColor = 'bg-brand-secondary-dark';
                                        } else if (type.includes('commercial') || type.includes('license')) {
                                          label = t('report.docs.commercial');
                                          Icon = Building;
                                          accentColor = 'bg-brand-primary';
                                        } else if (type.includes('eid') || type.includes('passport') || type.includes('id')) {
                                          label = t('report.docs.emiratesId');
                                          Icon = User;
                                          accentColor = 'bg-teal-600';
                                        } else if (type.includes('ejari') || type.includes('tenancy')) {
                                          label = t('report.docs.ejari');
                                          Icon = Home;
                                          accentColor = 'bg-brand-primary';
                                        } else if (type.includes('moa')) {
                                          label = t('report.docs.moa');
                                          Icon = FileText;
                                          accentColor = 'bg-indigo-600';
                                        } else if (type === 'fatca_declaration') {
                                          label = t('report.docs.fatca');
                                          Icon = ShieldCheck;
                                          accentColor = 'bg-blue-900';
                                        } else if (type === 'pep_declaration') {
                                          label = t('report.docs.pep');
                                          Icon = ShieldCheck;
                                          accentColor = 'bg-blue-900';
                                        } else if (type === 'product_package') {
                                          label = t('report.docs.productPackage');
                                          Icon = Package;
                                          accentColor = 'bg-blue-900';
                                        } else if (type === 'registered_individuals') {
                                          label = t('report.docs.registeredIndividuals');
                                          Icon = Users;
                                          accentColor = 'bg-brand-primary';
                                        } else if (type === 'summary_declaration') {
                                          label = t('report.docs.summaryDeclaration');
                                          Icon = CheckCircle;
                                          accentColor = 'bg-emerald-600';
                                        }

                                        return (
                                          <div key={doc.id || idx}>
                                            <div className="flex items-center gap-3 px-5 py-3 bg-white hover:bg-slate-50/50 transition-colors">
                                              <div className={`h-9 w-9 text-white rounded-xl flex items-center justify-center shadow-md flex-shrink-0 ${accentColor}`}>
                                                <Icon className="h-4 w-4" />
                                              </div>
                                              <div className="flex-1 min-w-0">
                                                <h4 className="text-[12px] font-black text-slate-800 tracking-tight uppercase leading-none mb-0.5">{label}</h4>
                                                <p className="text-[9px] font-bold text-slate-400 uppercase tracking-widest truncate">
                                                  {isDeclaration ? t('report.selfCertified') : t('report.verifiedFile', { name: doc.name || t('report.document') })}
                                                </p>
                                              </div>
                                              <div className={`flex items-center gap-1 px-2 py-1 rounded-lg border flex-shrink-0 transition-colors ${(isDeclaration ? isOnboardingComplete : true)
                                                ? 'bg-emerald-50 border-emerald-100'
                                                : 'bg-brand-primary border-brand-primary'
                                                }`}>
                                                {(isDeclaration ? isOnboardingComplete : true) ? (
                                                  <CheckCircle className="h-3 w-3 text-emerald-500" />
                                                ) : (
                                                  <div className="h-3 w-3 rounded-full bg-white animate-pulse" />
                                                )}
                                                <span className={`text-[8px] font-black uppercase tracking-widest ${(isDeclaration ? isOnboardingComplete : true) ? 'text-emerald-600' : 'text-white'
                                                  }`}>
                                                  {isDeclaration ? (isOnboardingComplete ? t('report.completed') : t('report.pending')) : t('report.verified')}
                                                </span>
                                              </div>
                                            </div>

                                            {isDeclaration ? (
                                              <div className="px-8 py-10 bg-white border-t border-slate-50">
                                                <SummaryDeclarationReportBlock
                                                  userEmail={user?.email}
                                                  onConfirmed={(data) => {
                                                    const refNo = data.reference_number || data.crossValidation?.reference_number || 'N/A';
                                                    setFinalRefNumber(refNo);
                                                    setShowFinalSuccess(true);
                                                    setIsOnboardingComplete(true);
                                                    setActiveDocData(null); // Close sidebar
                                                  }}
                                                />
                                              </div>
                                            ) : (
                                              <div className="px-5 py-3 bg-white border-t border-slate-50">
                                                {type === 'fatca_declaration' ? (
                                                  <FATCAReportBlock data={doc.extractedData} />
                                                ) : type === 'pep_declaration' ? (
                                                  <PEPReportBlock data={doc.extractedData} />
                                                ) : type === 'product_package' ? (
                                                  <ProductPackageReportBlock data={doc.extractedData} />
                                                ) : (type === 'registered_individuals' || type === 'REGISTERED_INDIVIDUALS') ? (
                                                  <RegisteredIndividualsReportBlock
                                                    data={doc.extractedData}
                                                    roleVault={persistentRoleMap}
                                                  />
                                                ) : (
                                                  <ExtractedDataDisplay
                                                    data={doc.extractedData}
                                                    documentType={doc.documentType}
                                                    isMinimal={true}
                                                  />
                                                )}
                                              </div>
                                            )}
                                          </div>
                                        );
                                      })}
                                    </div>
                                  </div>
                                  <div className={`h-1.5 w-full rounded-full ${dividerColor} opacity-20 mt-6 mb-8`} />
                                </div>
                              );
                            });
                          })()}
                        </div>
                      </div>
                    </div>

                    {/* Action Footer removed per user request */}
                  </div>
                ) : sidebarMode === 'reupload' ? (
                  <div className="flex-1 overflow-y-auto custom-scrollbar p-6 bg-white">
                    <div className="space-y-6">
                      <div className="flex items-center justify-between px-1">
                        <div>
                          <h3 className="text-sm font-black text-slate-800 tracking-tight leading-none mb-1 text-blue-900 uppercase">{t('report.documentManager')}</h3>
                          <p className="text-[10px] font-black text-slate-400 uppercase tracking-widest italic">{t('report.documentManagerSub')}</p>
                        </div>
                        <div className="w-10 h-10 rounded-2xl bg-indigo-50 flex items-center justify-center shadow-sm">
                          <RefreshCw className="h-5 w-5 text-indigo-500" />
                        </div>
                      </div>

                      <div className="grid grid-cols-1 gap-4">
                        {allReportItems.filter(i => !i.isVirtual).map((doc, idx) => {
                          const type = (doc.documentType || '').toLowerCase();
                          let label = doc.documentType?.replace(/_/g, ' ') || t('report.document');
                          let Icon = FileText;

                          if (type.includes('commercial')) { label = t('report.docs.commercial'); Icon = Building; }
                          else if (type.includes('eid') || type.includes('id')) { label = t('report.docs.emiratesId'); Icon = User; }
                          else if (type.includes('ejari')) { label = t('report.docs.ejari'); Icon = Home; }
                          else if (type.includes('moa')) { label = t('report.docs.moa'); Icon = FileText; }
                          else if (type.includes('coi')) { label = t('report.docs.coi'); Icon = ShieldCheck; }

                          return (
                            <div
                              key={idx}
                              className="group p-5 bg-slate-50 rounded-[32px] border border-slate-100 transition-all duration-300 hover:bg-white hover:border-indigo-200 hover:shadow-xl hover:shadow-indigo-100/40 relative overflow-hidden"
                            >
                              <div className="flex items-center justify-between relative z-10">
                                <div className="flex items-center gap-4">
                                  <div className="w-12 h-12 rounded-2xl bg-white shadow-sm flex items-center justify-center text-indigo-500 group-hover:bg-indigo-600 group-hover:text-white transition-all duration-300">
                                    <Icon className="h-6 w-6" />
                                  </div>
                                  <div>
                                    <h4 className="text-[13px] font-black text-slate-800 uppercase tracking-tight mb-0.5">{label}</h4>
                                    <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">{t('ui.currentlyVerified')}</p>
                                  </div>
                                </div>
                                <button
                                  onClick={() => {
                                    setPendingReuploadType(doc.documentType);
                                    fileInputRef.current?.click();
                                  }}
                                  className="px-5 py-2.5 bg-indigo-600 text-white text-[10px] font-black uppercase tracking-widest rounded-xl shadow-lg shadow-indigo-200 hover:bg-indigo-700 transition-all hover:-translate-y-0.5 active:translate-y-0"
                                >
                                  {t('ui.replace')}
                                </button>
                              </div>
                              {/* Background Pattern */}
                              <div className="absolute -right-4 -bottom-4 opacity-[0.03] group-hover:opacity-10 transition-opacity rotate-12">
                                <Icon className="h-24 w-24" />
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                ) : sidebarMode === 'vault' ? (
                  <div className="flex-1 overflow-y-auto custom-scrollbar p-8 bg-slate-50/50">
                    <div className="space-y-6">
                      <div className="flex items-center justify-between px-1">
                        <h3 className="text-[11px] font-black text-slate-400 uppercase tracking-[0.2em]">{t('ui.verifiedVault')}</h3>
                        <span className="text-[10px] font-black text-slate-400">{t('ui.artifactsCount', { count: successDocs.length })}</span>
                      </div>

                      {successDocs.length === 0 ? (
                        <div className="p-12 text-center border-2 border-dashed border-slate-100 rounded-[40px] opacity-40">
                          <Building className="h-10 w-10 text-slate-300 mx-auto mb-4" />
                          <p className="text-[11px] font-black text-slate-400 uppercase tracking-widest">{t('ui.noDocsVerifiedYet')}</p>
                        </div>
                      ) : (
                        <div className="grid grid-cols-1 gap-3">
                          {successDocs.map((doc, idx) => (
                            <div
                              key={idx}
                              onClick={() => {
                                setActiveDocData(doc);
                                setSidebarMode('data');
                              }}
                              className="group p-4 bg-white rounded-2xl border border-slate-100 cursor-pointer hover:border-indigo-200 hover:shadow-md transition-all duration-200 flex items-center gap-3 shadow-sm"
                            >
                              <div className="w-8 h-8 rounded-xl bg-indigo-50 flex items-center justify-center flex-shrink-0">
                                <FileText className="h-4 w-4 text-indigo-400" />
                              </div>
                              <div className="flex-1 min-w-0">
                                <p className="text-[11px] font-black text-slate-700 uppercase tracking-wider truncate">
                                  {doc.documentType ? translateDocName(t, doc.documentType) : t('report.document')}
                                </p>
                                <p className="text-[10px] text-slate-400 font-medium mt-0.5">{t('ui.verifiedCheck')}</p>
                              </div>
                              <ChevronRight className="h-4 w-4 text-slate-300 group-hover:text-indigo-400 transition-colors flex-shrink-0" />
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                ) : sidebarMode === 'preview' ? (
                  <div className="flex h-full overflow-hidden bg-gray-50">
                    <div className="w-20 border-r border-slate-100 bg-white flex flex-col items-center py-6 gap-5 overflow-y-auto custom-scrollbar shadow-sm">
                      {successDocs.map((doc, idx) => {
                        const isCurrent = (previewDocument || activeDocData)?.name === doc.name;
                        const t = (doc.documentType || '').toLowerCase();
                        let Icon = FileText;
                        if (t.includes('license') || t.includes('commercial')) Icon = Building;
                        if (t.includes('eid') || t.includes('passport') || t.includes('id')) Icon = User;
                        if (t.includes('ejari') || t.includes('tenancy')) Icon = Home;

                        return (
                          <button
                            key={idx}
                            onClick={() => openPreview(doc)}
                            className={`p-3.5 rounded-2xl transition-all relative group ${isCurrent
                              ? 'bg-brand-primary shadow-xl shadow-blue-200 scale-110'
                              : 'bg-transparent text-slate-400 hover:text-brand-primary hover:bg-slate-50'
                              }`}
                            title={doc.name}
                          >
                            <Icon className="h-5.5 w-5.5" />
                          </button>
                        );
                      })}
                    </div>

                    <div className="flex-1 overflow-hidden flex flex-col">
                      {(() => {
                        const doc = previewDocument || activeDocData;
                        const rawUrl = doc?.previewUrl || doc?.documentMetadata?.previewUrl;

                        const getFullUrl = (url) => {
                          if (!url) return null;
                          if (url.startsWith('blob:') || url.startsWith('data:')) return url;

                          const baseOrigin = window.location.origin;

                          // Handle localhost or 127.0.0.1 in the URL from backend
                          let clean = url;
                          if (url.includes('localhost:') || url.includes('127.0.0.1:')) {
                            const parts = url.split(':9000');
                            if (parts.length > 1) clean = parts[1];
                          }

                          if (clean.startsWith('http')) return clean;
                          return `${baseOrigin}${clean.startsWith('/') ? '' : '/'}${clean}`;
                        };

                        const previewUrl = getFullUrl(rawUrl);
                        const mimeType = doc?.type?.toLowerCase() || '';
                        const isPdf = mimeType.includes('pdf') || previewUrl?.toLowerCase().includes('.pdf');
                        if (!previewUrl) {
                          return (
                            <div className="flex-1 flex items-center justify-center text-center p-12">
                              <div className="opacity-40">
                                <FileText className="h-10 w-10 text-slate-300 mx-auto mb-3" />
                                <p className="text-[11px] font-black text-slate-400 uppercase tracking-widest">{t('ui.noPreviewAvailable')}</p>
                              </div>
                            </div>
                          );
                        }

                        if (isPdf) {
                          return (
                            <iframe
                              src={previewUrl}
                              className="flex-1 w-full border-0"
                              title={t('ui.documentPreview')}
                            />
                          );
                        }

                        return (
                          <div className="flex-1 overflow-hidden flex items-center justify-center p-4 lg:p-10 bg-slate-900/5 min-h-0">
                            <img
                              src={previewUrl}
                              alt={t('ui.documentPreview')}
                              className="w-full h-full object-contain rounded-xl shadow-2xl ring-1 ring-brand-primary/10 transition-transform duration-500 hover:scale-[1.01] animate-in fade-in zoom-in-95 duration-500"
                            />
                          </div>
                        );
                      })()}
                    </div>
                  </div>
                ) : null}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
        {/* Final Success Modal */}
        <FinalSuccessModal
          isOpen={showFinalSuccess}
          onClose={() => setShowFinalSuccess(false)}
          referenceNumber={finalRefNumber}
        />
      </div>
    </div>
  );
};

export default AIAssistant;
