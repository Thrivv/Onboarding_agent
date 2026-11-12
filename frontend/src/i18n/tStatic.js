// frontend/src/i18n/tStatic.js
//
// t() for code that can't use the useLanguage() hook: class components
// (error boundaries, which may render outside <LanguageProvider>) and
// module-level helpers. Reads the current language from api/languageState,
// which LanguageContext keeps in sync on every toggle. Same lookup and
// fallback rules as LanguageContext's t(): current language -> English ->
// the key itself.
import { translations } from './translations';
import { getRequestLanguage, isPseudoLocale } from '../api/languageState';

const resolvePath = (obj, path) =>
  path.split('.').reduce((acc, k) => (acc && acc[k] !== undefined ? acc[k] : undefined), obj);

export const tStatic = (key, vars) => {
  const lang = getRequestLanguage();
  let str = resolvePath(translations[lang], key);
  if (str === undefined) str = resolvePath(translations.english, key);
  if (str === undefined) return key;
  if (vars) {
    Object.keys(vars).forEach((k) => {
      str = str.replace(new RegExp(`\\{${k}\\}`, 'g'), vars[k]);
    });
  }
  return isPseudoLocale() ? `⟦${str}⟧` : str;
};
