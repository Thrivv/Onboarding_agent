// frontend/src/components/common/LanguageToggle.jsx
//
// The actual, working three-way language control. Replaces two things that
// used to exist separately: the read-only Globe badge in
// features/onboarding/OnboardingPage.jsx's chat header (visual only — it
// displayed selectedLanguage but nothing could change it), and the
// handleLanguageChange handler next to it, which was never wired to any
// element (see docs/multilingual-support-plan.html, Finding 1).
//
// Reused in both Navbar.jsx (so it's reachable outside the chat) and
// OnboardingPage.jsx's chat header, both reading/writing the same
// LanguageContext so the two can never disagree.
//
// Renders nothing at all when LANGUAGE_TOGGLE_ENABLED=false (see
// .env.docker, app/config.py, context/LanguageContext.jsx) — with only
// English available there's nothing useful to toggle, so callers
// (Navbar.jsx, OnboardingPage.jsx) can render <LanguageToggle /> unconditionally
// and trust it to hide itself rather than each needing its own check.

import React from 'react';
import { Globe } from 'lucide-react';
import { useLanguage } from '../../context/LanguageContext';

const OPTIONS = [
  { code: 'english', label: 'EN' },
  { code: 'arabic', label: 'AR' },
  { code: 'spanish', label: 'ES' },
];

const LanguageToggle = ({ className = '' }) => {
  const { language, setLanguage, languageToggleEnabled } = useLanguage();

  if (!languageToggleEnabled) return null;

  return (
    <div
      role="group"
      aria-label="Language"
      className={`inline-flex items-center gap-1 px-1.5 py-1 bg-indigo-50 border-2 border-blue-100 rounded-xl shadow-sm shadow-indigo-100/40 ${className}`}
    >
      <Globe className="h-3.5 w-3.5 text-brand-primary shrink-0" />
      {OPTIONS.map((opt) => {
        const active = language === opt.code;
        return (
          <button
            key={opt.code}
            type="button"
            onClick={() => setLanguage(opt.code)}
            aria-pressed={active}
            title={opt.code.charAt(0).toUpperCase() + opt.code.slice(1)}
            className={`px-2 py-1 rounded-lg text-[10px] font-black tracking-[0.1em] uppercase transition-colors ${
              active ? 'bg-brand-primary text-white shadow' : 'text-indigo-700 hover:bg-white'
            }`}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
};

export default LanguageToggle;
