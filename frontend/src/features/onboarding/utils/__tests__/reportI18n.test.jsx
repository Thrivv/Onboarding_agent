/**
 * @jest-environment jsdom
 */
// Unified Report / Planning card i18n — docs: planning-report-i18n artifact.
// Run: cd frontend && CI=true npx react-scripts test --watchAll=false reportI18n
import React from 'react';
import { render, screen, act } from '@testing-library/react';
import { translations } from '../../../../i18n/translations';
import { fieldSlug, translateFieldLabel, translateValue, translateRole, translateDocName } from '../reportI18n';

// Controllable LanguageContext: same t() semantics as the real provider
// (dot-path lookup, English fallback, {var} interpolation, key if missing).
let mockLang = 'english';
const resolve = (obj, p) => p.split('.').reduce((a, k) => (a && a[k] !== undefined ? a[k] : undefined), obj);
const mockT = (key, vars) => {
  let s = resolve(translations[mockLang], key);
  if (s === undefined) s = resolve(translations.english, key);
  if (s === undefined) return key;
  if (vars) Object.keys(vars).forEach((k) => { s = s.replace(new RegExp(`\\{${k}\\}`, 'g'), vars[k]); });
  return s;
};
jest.mock('../../../../context/LanguageContext', () => ({
  useLanguage: () => ({ language: mockLang, t: mockT }),
}));

// Keep the test hermetic: no network client, no logger side effects.
jest.mock('../../../../api/compliance', () => ({
  confirmSelfDeclaration: jest.fn(), getSelfDeclarationStatus: jest.fn(() => Promise.resolve({ data: {} })),
  getSelfDeclarationSummary: jest.fn(() => Promise.resolve({ data: {} })),
}), { virtual: true });
jest.mock('../../../../utils/logger', () => ({ __esModule: true, default: { log() {}, warn() {}, error() {} } }), { virtual: true });

// eslint-disable-next-line import/first
import { CommercialExtractedData } from '../../components/extracted/CommercialExtractedData';
// eslint-disable-next-line import/first
import { EIDExtractedData } from '../../components/extracted/EIDExtractedData';
// eslint-disable-next-line import/first
import { FATCAReportBlock, PEPReportBlock, RegisteredIndividualsReportBlock } from '../../components/compliance/ReportBlocks';
// eslint-disable-next-line import/first
import { NextDocumentCard } from '../../components/cards/NextDocumentCard';
// eslint-disable-next-line import/first
import { PlanningTimeline } from '../../components/status/PlanningTimeline';

const commercial = { english: {
  company_name_english: 'PINNACLE VENTURES TRADING LLC', license_number: 'DED-LLC-2024-087432',
  legal_type: 'Limited Liability Company (LLC)', mobile: '971-50-9876543', issue_date: '01/06/2024', expiry_date: '31/05/2026',
} };

describe('helpers', () => {
  test('slug', () => expect(fieldSlug('Area / Community')).toBe('area_community'));
  test('known label translates, unknown falls back to English', () => {
    mockLang = 'arabic';
    expect(translateFieldLabel(mockT, 'Company Name')).toBe('اسم الشركة');
    expect(translateFieldLabel(mockT, 'Some New Extractor Field')).toBe('Some New Extractor Field');
  });
  test('only fixed answers are translated', () => {
    mockLang = 'spanish';
    expect(translateValue(mockT, 'Yes')).toBe('Sí');
    expect(translateValue(mockT, 'False')).toBe('No');
    expect(translateValue(mockT, 'PINNACLE VENTURES TRADING LLC')).toBe('PINNACLE VENTURES TRADING LLC');
    expect(translateValue(mockT, '784-1999-0405761-1')).toBe('784-1999-0405761-1');
    expect(translateRole(mockT, 'AS')).toBe('Firmante Autorizado');
  });
});

describe.each([
  ['english', 'Company Name', 'View All Details'],
  ['arabic', 'اسم الشركة', 'عرض جميع التفاصيل'],
  ['spanish', 'Nombre de la empresa', 'Ver todos los detalles'],
])('Commercial License panel in %s', (lang, companyLabel, viewAll) => {
  test('labels in the UI language, data untouched', () => {
    mockLang = lang;
    render(<CommercialExtractedData data={commercial} />);
    expect(screen.getByText(companyLabel)).toBeTruthy();
    expect(screen.getByText(viewAll)).toBeTruthy();
    expect(screen.getByText('PINNACLE VENTURES TRADING LLC')).toBeTruthy();
    expect(screen.getByText('DED-LLC-2024-087432')).toBeTruthy();
    expect(screen.getByText('31/05/2026')).toBeTruthy();
  });
});

test('Emirates ID panel in Arabic', () => {
  mockLang = 'arabic';
  render(<EIDExtractedData data={{ Name: 'Varsha Balaji Balaji', 'ID Number': '784-1999-0405761-1' }} />);
  expect(screen.getByText('الاسم الكامل')).toBeTruthy();
  expect(screen.getByText('الهوية الإماراتية')).toBeTruthy();
  expect(screen.getByText('Varsha Balaji Balaji')).toBeTruthy();
  expect(screen.getByText('784-1999-0405761-1')).toBeTruthy();
});

test('FATCA + PEP blocks: Yes/No and False in the UI language', () => {
  mockLang = 'arabic';
  render(<>
    <FATCAReportBlock data={{ entity_type: 'Offshore', country_of_tax_residence: 'UAE', entity_incorporated_in_usa: true, entity_has_us_ownership: false, us_tax_id: '234' }} />
    <PEPReportBlock data={{ domestic_pep: false, foreign_pep: false }} />
  </>);
  expect(screen.getByText('مؤسَّس في الولايات المتحدة')).toBeTruthy();
  expect(screen.getByText('نعم')).toBeTruthy();
  expect(screen.getAllByText('لا').length).toBe(3); // US ownership + 2 PEP statuses
  expect(screen.queryByText('False')).toBeNull();
  expect(screen.getByText('Offshore')).toBeTruthy();
});

test('Registered individuals: roles translated, colour by role code', () => {
  mockLang = 'spanish';
  const { container } = render(<RegisteredIndividualsReportBlock data={{
    all_members: ['JAMES EDWARD WHITMORE', 'MEERA SURESH PILLAI'],
    verified_members: ['JAMES EDWARD WHITMORE', 'MEERA SURESH PILLAI'],
    member_role_map: { 'JAMES EDWARD WHITMORE': 'AS', 'MEERA SURESH PILLAI': 'MEMBER' },
    ownershipMap: { 'JAMES EDWARD WHITMORE': '48.0%' },
  }} />);
  expect(screen.getByText('Firmante Autorizado').className).toContain('text-purple-400');
  expect(screen.getByText('Miembro').className).toContain('text-indigo-400');
  expect(screen.getAllByText('Verificado').length).toBe(2);
  expect(screen.getByText('JAMES EDWARD WHITMORE')).toBeTruthy();
  expect(container.textContent).toContain('48.0%');
});

test('Planning card follows a language switch without restarting', () => {
  jest.useFakeTimers();
  mockLang = 'english';
  const { rerender } = render(<PlanningTimeline />);
  expect(screen.getByText('Planning')).toBeTruthy();
  act(() => { jest.advanceTimersByTime(4100); }); // -> step 2 active
  mockLang = 'arabic';
  rerender(<PlanningTimeline />);
  expect(screen.getByText('التخطيط')).toBeTruthy();
  const active = screen.getByText('بدء التحقق الأمني وكشف التلاعب...');
  expect(active.className).toContain('text-emerald-600'); // still on step 2
  expect(screen.queryByText('Securely connecting to document vault...')).toBeNull();
  jest.useRealTimers();
});

test('translateDocName maps raw types and display names; unknown input prettified', () => {
  const prev = mockLang;
  mockLang = 'arabic';
  expect(translateDocName(mockT, 'commercial_license')).toBe(translations.arabic.report.docs.commercial);
  expect(translateDocName(mockT, 'Emirates ID or Passport')).toBe(translations.arabic.report.docs.idOrPassport);
  expect(translateDocName(mockT, 'eid')).toBe(translations.arabic.report.docs.idOrPassport);
  expect(translateDocName(mockT, 'FATCA Self-Certification')).toBe(translations.arabic.report.docs.fatcaSelfCert);
  expect(translateDocName(mockT, 'Memorandum of Association')).toBe(translations.arabic.report.docs.moaFull);
  expect(translateDocName(mockT, 'some_new_doc')).toBe('Some New Doc');
  mockLang = prev;
});

test('NextDocumentCard renders fully in Arabic and switches with the language', () => {
  const prev = mockLang;
  mockLang = 'arabic';
  const props = {
    msgId: 'm1', nextDoc: { type: 'eid', member_name: 'VARSHA BALAJI' }, remainingDocs: ['eid', 'ejari'],
    membersInfo: { verified: 1, total: 2, all_members: ['VARSHA BALAJI', 'RAVI'], verified_members: ['RAVI'], current_member: 'VARSHA BALAJI' },
  };
  const { rerender, container } = render(<NextDocumentCard {...props} />);
  const ar = translations.arabic.ui;
  expect(screen.getByText(ar.progression)).toBeTruthy();
  expect(screen.getByText(ar.requiredNextDocument)).toBeTruthy();
  expect(screen.getByText(ar.remainingRequirements)).toBeTruthy();
  expect(screen.getByText(ar.idProcessingActive)).toBeTruthy();
  ['Onboarding Progression', 'Capture Required', 'Required Next Document', 'Remaining Requirements', 'Coming Up', 'Identity Verification Processing Active']
    .forEach((en) => expect(container.textContent).not.toContain(en));
  mockLang = 'spanish';
  rerender(<NextDocumentCard {...props} />);
  expect(screen.getByText(translations.spanish.ui.progression)).toBeTruthy();
  mockLang = prev;
});
