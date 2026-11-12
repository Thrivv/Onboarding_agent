// i18n regression tests — docs/multilingual-flow-approach.html
// Run: cd frontend && CI=true npx react-scripts test --watchAll=false i18nFlow
import { logicText, stripMemberLists, canonicalKeywords } from '../i18nText';
import { deriveCardState } from '../cardState';
import { translations } from '../../../../i18n/translations';

const M = (id, extra = {}, type = null) => ({ id, ...extra, metadata: type ? { message_type: type } : {} });

describe('logicText — keyword logic works in every language', () => {
  test.each([
    ['تم حفظ إقرار فاتكا. يُرجى استكمال إقرار الأشخاص المعرّضين سياسياً (PEP) أدناه.', ['fatca', 'pep', 'declaration']],
    ['Declaración FATCA guardada. Complete su Declaración PEP (Persona Expuesta Políticamente).', ['fatca', 'pep', 'declaration']],
    ['يُرجى اختيار باقة المنتجات أدناه.', ['package']],
    ['Seleccione su Paquete de Productos a continuación.', ['package']],
    ['تم التحقق من رخصتك التجارية وقبولها بنجاح.', ['license', 'commercial', 'successfully validated and accepted']],
    ['Su Licencia Comercial ha sido validada y aceptada exitosamente.', ['license', 'commercial', 'successfully validated and accepted']],
    ['يُرجى تأكيد قائمة المخولين بالتوقيع أدناه.', ['signatories']],
  ])('%s', (text, expected) => {
    const lt = logicText({ content: text });
    expected.forEach((kw) => expect(lt).toContain(kw));
  });

  test('prefers the stored English rendering', () => {
    expect(logicText({ content: 'نص', metadata: { i18n: { english: 'FATCA declaration saved' } } })).toContain('fatca');
    expect(logicText({ content: 'نص', logicText: 'Please select your Product Package' })).toContain('product package');
  });

  test('English text is unchanged apart from lower-casing', () => {
    expect(canonicalKeywords('Your MOA was verified')).toBe('your moa was verified');
  });
});

describe('stripMemberLists — same result in every language', () => {
  const cases = [
    'All 4 individuals are confirmed.\n\n**Registered Individuals:**\n1. **A** — Member\n2. **B** — Member\n\nOne more thing — please complete your FATCA Declaration below.',
    'تم تأكيد جميع الأفراد (4).\n\n**الأفراد المسجّلون:**\n1. **A** — عضو\n2. **B** — عضو\n\nأمر أخير — يُرجى استكمال إقرار فاتكا أدناه.',
    'Las 4 personas están confirmadas.\n\n**Personas registradas:**\n1. **A** — Miembro\n2. **B** — Miembro\n\nComplete su Declaración FATCA a continuación.',
    'All identity documents are verified.\n\n**Final Members List:**\n1. **A** — Member\n\nPlease complete your FATCA Declaration below.',
  ];
  test.each(cases)('removes the list: %#', (text) => {
    const out = stripMemberLists(text, 'x');
    expect(out).not.toMatch(/\*\*A\*\*/);
    expect(out.split('\n\n').length).toBe(2);
  });
});

describe('deriveCardState — card completion survives any rebuild', () => {
  const history = [
    M(1, { moaAsTrigger: true }),
    M(2, {}, 'ki_moa_as_saved'),
    M(3, { kiLoopPrompt: true }),
    M(4, {}, 'ki_ai_added'),
    M(5, { kiLoopPrompt: true }),
    M(6, { fatcaTrigger: true }, 'ki_loop_finalized'),
    M(7, {}, 'fatca_confirmed'),
    M(8, { pepTrigger: true }),
    M(9, {}, 'pep_confirmed'),
    M(10, { kiLoopPrompt: true }),
  ];
  const out = deriveCardState(history);
  test('AS card completed once an AS-saved row follows', () => expect(out[0].asSelectionCompleted).toBe(true));
  test('KI loop: yes when another individual was added', () => {
    expect(out[2].kiLoopCompleted).toBe(true);
    expect(out[2].kiLoopChoice).toBe('yes');
  });
  test('KI loop: no when finalized', () => expect(out[4].kiLoopChoice).toBe('no'));
  test('FATCA confirmed', () => expect(out[5].isFatcaConfirmed).toBe(true));
  test('PEP confirmed', () => expect(out[8].isPepConfirmed).toBe(true));
  test('the latest open card stays open', () => expect(out[9].kiLoopCompleted).toBeFalsy());
  test('does not depend on message language (content ignored)', () => {
    const ar = history.map((m) => ({ ...m, content: 'نص عربي' }));
    expect(deriveCardState(ar).map((m) => !!m.asSelectionCompleted)).toEqual(out.map((m) => !!m.asSelectionCompleted));
  });
  test('idempotent', () => expect(deriveCardState(out)).toEqual(out));
});

describe('translations — every language has every key and placeholder', () => {
  const keys = (o, p = '') => Object.entries(o).flatMap(([k, v]) => (typeof v === 'object' ? keys(v, `${p}${k}.`) : [`${p}${k}`]));
  const get = (o, k) => k.split('.').reduce((a, x) => a[x], o);
  const en = keys(translations.english);
  test('same key set', () => {
    expect(keys(translations.arabic).sort()).toEqual([...en].sort());
    expect(keys(translations.spanish).sort()).toEqual([...en].sort());
  });
  test('same placeholders', () => {
    en.forEach((k) => {
      const ph = (l) => (get(translations[l], k).match(/\{\w+\}/g) || []).sort().join();
      expect([k, ph('arabic')]).toEqual([k, ph('english')]);
      expect([k, ph('spanish')]).toEqual([k, ph('english')]);
    });
  });
});
