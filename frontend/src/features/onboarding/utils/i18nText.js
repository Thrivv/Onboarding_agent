// frontend/src/features/onboarding/utils/i18nText.js
//
// Language-independent text helpers for OnboardingPage's routing / parsing
// logic (docs/multilingual-flow-approach.html, R1 + rule 1).
//
// Several fallbacks in OnboardingPage decide which Verification-Hub tab a
// message belongs to, or in which order compliance cards appear, by looking
// for English words in the message text ('fatca', 'signatory', 'package',
// 'license', ...). The primary signals are structural (message_type, stage,
// *_trigger flags) — these keyword checks only run when those are absent —
// but when they did run on Arabic or Spanish text they silently matched
// nothing, so messages landed in the wrong tab and cards reordered.
//
// logicText(msg) fixes that without touching each check:
//   1. it prefers the message's ENGLISH rendering when one is known —
//      catalog messages store all three renderings (metadata.i18n), and
//      /conversation-logs?language= returns `original_message` next to a
//      translated one;
//   2. it appends English aliases for Arabic/Spanish keywords found in the
//      text, so `logicText(msg).includes('fatca')` also matches "فاتكا".
//
// The member-list strippers are shared here too: the same three regexes were
// copied in four places in OnboardingPage and only knew the English headers.

const KEYWORD_ALIASES = [
  // compliance
  ['فاتكا', 'fatca'],
  ['المعرّضين سياسياً', 'pep'], ['المعرضين سياسيا', 'pep'], ['المعرّضين سياسيًا', 'pep'],
  ['expuesta políticamente', 'pep'], ['expuestas políticamente', 'pep'],
  ['باقة المنتجات', 'product package'], ['باقة', 'package'],
  ['paquete de productos', 'product package'], ['paquete de producto', 'product package'], ['paquete', 'package'],
  ['الإقرار الذاتي', 'self-declaration'], ['autodeclaración', 'self-declaration'], ['auto-declaración', 'self-declaration'],
  ['إقرار', 'declaration'], ['declaración', 'declaration'],
  // identity / signatories
  ['المفوّضين بالتوقيع', 'signatories'], ['المفوضين بالتوقيع', 'signatories'], ['المخولين بالتوقيع', 'signatories'],
  ['مفوّض بالتوقيع', 'signatory'], ['المفوّض بالتوقيع', 'signatory'], ['firmantes', 'signatories'], ['firmante', 'signatory'],
  ['الهوية الإماراتية', 'emirates id eid identity'], ['مستند الهوية', 'identity'], ['مستندات الهوية', 'identity'],
  ['جواز السفر', 'passport'], ['pasaporte', 'passport'], ['identidad', 'identity'],
  // corporate documents
  ['الرخصة التجارية', 'commercial license'], ['رخصتك التجارية', 'commercial license'],
  ['licencia comercial', 'commercial license'],
  ['عقد التأسيس', 'moa memorandum'], ['memorando de asociación', 'moa memorandum'],
  ['إيجاري', 'ejari'], ['عقد الإيجار', 'tenancy'], ['contrato de arrendamiento', 'tenancy'],
  ['شهادة التأسيس', 'certificate of incorporation'], ['certificado de constitución', 'certificate of incorporation'],
  // acceptance phrasing (Sidebar progress)
  ['وقبوله بنجاح', 'successfully validated and accepted'], ['وقبولها بنجاح', 'successfully validated and accepted'],
  ['validado y aceptado', 'successfully validated and accepted'], ['validada y aceptada', 'successfully validated and accepted'],
  ['جارٍ التحقق من ميزات أمان المستند', 'authenticating document'],
  ['verificando las características de seguridad', 'authenticating document'],
  ['المستندات المطلوبة', 'required documents'], ['documentos requeridos', 'required documents'],
];

const lower = (s) => (s || '').toLowerCase();

export function canonicalKeywords(text) {
  const t = lower(text);
  const extra = [];
  for (const [term, en] of KEYWORD_ALIASES) {
    if (t.includes(term)) extra.push(en);
  }
  return extra.length ? `${t} ${extra.join(' ')}` : t;
}

// Stable, lower-cased text for routing/keyword logic. Never for display.
export function logicText(msg) {
  if (!msg) return '';
  const english = msg.metadata?.i18n?.english;
  return canonicalKeywords(english || msg.logicText || msg.content || '');
}

// ── Member-list strippers (were copied 4× in OnboardingPage) ───────────────
// Header of the "Registered Individuals" summary the KI-loop messages append
// (backend app/i18n/messages.py: summary.header_registered).
// (+ summary.header_final "Final Members List", which the live upload path
// already stripped but a reload from history did not.)
const REGISTERED_HEADERS = [
  'Registered Individuals', 'الأفراد المسجّلون', 'الأفراد المسجلون', 'Personas registradas',
  'Final Members List', 'القائمة النهائية للأعضاء', 'Lista final de miembros',
];
// Stop tokens: the sentence that follows the list, in any language.
const STOP = [
  'Please complete', 'enough other', 'Please confirm', 'All identity',
  'يُرجى', 'يرجى', 'Por favor', 'Complete su', 'Todos los documentos',
];
const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const STOP_RE = STOP.map(esc).join('|');

export const REGISTERED_LIST_RE = new RegExp(
  `(?:\\*\\*)?(?:${REGISTERED_HEADERS.map(esc).join('|')}):(?:\\*\\*)?[\\s\\S]*?(?=\\n\\r?\\n|${STOP_RE}|$)`,
  'gi',
);

// "…verification is required for the following beneficial owners:" + list
// (backend member_expansion.py, Type-2 ownership analysis), per language.
const MOA_LIST_LEADS = [
  'verification is required for the following beneficial owners:',
  'para los siguientes beneficiarios:',
  'للمستفيدين الفعليين التاليين:',
];
export const MOA_LIST_RE = new RegExp(
  `(?:${MOA_LIST_LEADS.map(esc).join('|')})[\\s\\S]*?(?=\\n\\r?\\n|${STOP_RE}|$)`,
  'gi',
);

// Removes both member lists from a message body. `listedBelow` is the
// localized replacement lead-in (t('chat.membersListedBelow')); the list
// itself is rendered from data by the Authorised Signatories card.
export function stripMemberLists(text, listedBelow) {
  if (!text) return text;
  let out = text.replace(REGISTERED_LIST_RE, '\n');
  out = out.replace(MOA_LIST_RE, listedBelow || 'verification is required for the members listed below:');
  return out.replace(/\n{3,}/g, '\n\n').trim();
}
