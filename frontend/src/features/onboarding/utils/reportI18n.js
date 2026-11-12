// frontend/src/features/onboarding/utils/reportI18n.js
//
// Translation helpers for the Unified Report, the document field panels
// (components/extracted/*) and the compliance report blocks.
//
// Every label in those components used to be a hardcoded English literal
// (label="Company Name"), so the language toggle never reached them. They now
// go through one shared dictionary, translations.<lang>.report.fields, keyed
// by a slug of the English label — so a component keeps reading like
// `label={L('Company Name')}`, and a field the dictionary doesn't know yet
// (e.g. a new key from the extractor, shown by GenericExtractedData) falls
// back to its readable English label instead of a raw key or a blank.
//
// Values are NOT translated — names, ID numbers, dates, company names are
// document data and must stay exactly as extracted. The only exception is
// the fixed answer vocabulary (Yes / No / True / False / Identified / Clear),
// which V() maps. Status colouring in InfoRow still keys off the raw value.

import { useCallback } from 'react';
import { useLanguage } from '../../../context/LanguageContext';

export const fieldSlug = (label) =>
  String(label || '')
    .toLowerCase()
    .replace(/&/g, ' and ')
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');

const VALUE_KEYS = {
  yes: 'yes', true: 'yes', no: 'no', false: 'no',
  identified: 'identified', clear: 'clear', 'n/a': 'notAvailable',
};

// Pure versions (take t) — usable outside hooks, e.g. in memoized helpers.
export const translateFieldLabel = (t, english) => {
  const slug = fieldSlug(english);
  if (!slug) return english;
  const key = `report.fields.${slug}`;
  const out = t(key);
  return out === key ? english : out;
};

export const translateValue = (t, value) => {
  if (value === null || value === undefined) return value;
  const k = VALUE_KEYS[String(value).trim().toLowerCase()];
  if (!k) return value;
  const key = `report.values.${k}`;
  const out = t(key);
  return out === key ? value : out;
};

// Role codes / English role names -> localized role label.
export const translateRole = (t, role) => {
  const r = String(role || '').toUpperCase().replace(/_/g, ' ').trim();
  if (r === 'AS' || r === 'AUTHORISED SIGNATORY') return t('report.roles.as');
  if (r === 'MEMBER' || r === 'VERIFIED MEMBER') return t('report.roles.member');
  if (r === 'OWNER') return t('report.roles.owner');
  if (r === 'INDIVIDUAL') return t('report.roles.individual');
  return role;
};

// Document type / display name -> localized document name. Accepts raw types
// ("commercial_license", "eid", "moa") and English display names
// ("Emirates ID or Passport", "FATCA Self-Certification"). Unknown input is
// returned prettified, never blank.
const DOC_RULES = [
  [/fatca.*self|self.*cert/, 'fatcaSelfCert'],
  [/pep.*self|self.*decl.*pep/, 'pepSelfDecl'],
  [/package.*select/, 'packageSelection'],
  [/fatca/, 'fatca'],
  [/\bpep\b|politically/, 'pep'],
  [/package/, 'productPackage'],
  [/summary/, 'summaryDeclaration'],
  [/^final$/, 'final'],
  [/required.?doc/, 'requiredDocuments'],
  [/commercial|licen[cs]e|trade/, 'commercial'],
  [/memorandum/, 'moaFull'],
  [/\bmoa\b/, 'moa'],
  [/ejari.*address|address.*proof/, 'ejariAddress'],
  [/ejari|tenancy/, 'ejari'],
  [/\bcoi\b|incorporation/, 'coi'],
  [/(eid|emirates|identity).*(or|\/).*passport|passport.*(or|\/).*(eid|emirates)/, 'idOrPassport'],
  [/\beid\b|emirates.?id|identity|passport/, 'idOrPassport'],
];

const prettify = (str) => String(str).replace(/_/g, ' ')
  .split(' ').map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w)).join(' ');

export const translateDocName = (t, raw) => {
  if (!raw) return '';
  const lower = String(raw).toLowerCase().replace(/_/g, ' ').trim();
  for (const [re, key] of DOC_RULES) {
    if (re.test(lower)) {
      const k = `report.docs.${key}`;
      const out = t(k);
      if (out !== k) return out;
    }
  }
  return prettify(raw);
};

export function useReportI18n() {
  const { t } = useLanguage();
  const L = useCallback((english) => translateFieldLabel(t, english), [t]);
  const V = useCallback((value) => translateValue(t, value), [t]);
  const R = useCallback((key, vars) => t(`report.${key}`, vars), [t]);
  const role = useCallback((r) => translateRole(t, r), [t]);
  const D = useCallback((d) => translateDocName(t, d), [t]);
  return { t, L, V, R, role, D };
}
