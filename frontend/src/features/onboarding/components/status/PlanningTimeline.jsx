import React, { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { ShieldCheck } from 'lucide-react';
import { useLanguage } from '../../../../context/LanguageContext';

const ChecklistItem = ({ text, isStep = false, isLast = false, delay = 0, isActive = false, isPast = false }) => (
  <motion.div
    initial={{ x: -10, opacity: 0 }}
    animate={{ x: 0, opacity: 1 }}
    transition={{ delay }}
    className="relative flex items-start gap-4 py-2"
  >
    {/* Vertical Line Connector — start-anchored so it mirrors in RTL */}
    {!isLast && (
      <div className={`absolute ltr:left-[5px] rtl:right-[5px] top-4 w-[2px] h-full ${isPast ? 'bg-emerald-500' : 'bg-gray-100'}`} />
    )}

    {/* Step Icon/Dot */}
    <div className={`mt-1.5 z-10 flex items-center justify-center`}>
      {isActive ? (
        <div className="relative">
          <div className="absolute inset-0 bg-emerald-400 rounded-full animate-ping opacity-25" />
          <ShieldCheck className="h-3 w-3 text-emerald-500 bg-white rounded-full shadow-sm" />
        </div>
      ) : isPast ? (
        <div className="w-2.5 h-2.5 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]" />
      ) : (
        <div className="w-2.5 h-2.5 rounded-full bg-gray-200" />
      )}
    </div>

    <span className={`text-[13px] font-medium leading-relaxed ${isActive ? 'text-emerald-600 font-bold' : isPast ? 'text-gray-700' : 'text-gray-400'}`}>
      {text}
    </span>
  </motion.div>
);

// Step keys, not step text: the text comes from translations
// (cards.planning.*), so a language switch while a document is uploading
// re-renders the labels in place without resetting the animation position.
const STEP_KEYS = ['step1', 'step2', 'step3', 'step4', 'step5'];

const PlanningTimeline = () => {
  const { t } = useLanguage();
  const [activeStep, setActiveStep] = useState(0);

  const steps = STEP_KEYS.map((k) => t(`cards.planning.${k}`));

  useEffect(() => {
    const interval = setInterval(() => {
      setActiveStep(prev => (prev < steps.length - 1 ? prev + 1 : prev));
    }, 4000); // 4 seconds per step to feel natural
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex flex-col">
      <div className="flex items-center gap-2 text-emerald-600 font-black uppercase tracking-widest text-[11px] mb-4 bg-emerald-50 w-fit px-3 py-1.5 rounded-full border border-emerald-100">
        <div className="animate-spin-slow">
          <ShieldCheck className="h-4 w-4" />
        </div>
        {t('cards.planning.title')}
      </div>
      <div className="ml-1">
        {steps.map((step, i) => (
          <ChecklistItem
            key={STEP_KEYS[i]}
            text={step}
            isActive={activeStep === i}
            isPast={activeStep > i}
            isLast={i === steps.length - 1}
            delay={i * 0.15}
          />
        ))}
      </div>
    </div>
  );
};

// ============================================================================
// WELCOME ONBOARDING CARD
// ============================================================================

export { ChecklistItem, PlanningTimeline };
