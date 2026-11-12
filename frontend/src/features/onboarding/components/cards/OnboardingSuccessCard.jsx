import React from 'react';
import { useLanguage } from '../../../../context/LanguageContext';
import { motion } from 'framer-motion';
import { Clock, Copy, Mail, ShieldCheck } from 'lucide-react';
import toast from 'react-hot-toast';

const OnboardingSuccessCard = ({ content }) => {
  const { t } = useLanguage();
  // Extract reference number if present (e.g., REF-2026-KV4VVA)
  const refMatch = content?.match(/REF-[\d]{4}-[A-Z0-9]+/);
  const referenceNumber = refMatch ? refMatch[0] : null;
  const cleanContent = content?.replace(/Note: This is your reference number: REF-[\d]{4}-[A-Z0-9]+/, '').trim();

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      className="mt-6 w-full mx-auto overflow-hidden rounded-[32px] shadow-xl border border-emerald-100 bg-white"
    >
      <div className="bg-emerald-600 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="h-8 w-8 bg-white/20 backdrop-blur-md rounded-xl flex items-center justify-center border border-white/20">
            <ShieldCheck className="h-5 w-5 text-white" />
          </div>
          <h2 className="text-xs font-black text-white tracking-widest uppercase">{t('ui.onboardingComplete')}</h2>
        </div>
        <div className="h-2 w-2 rounded-full bg-white animate-pulse" />
      </div>

      <div className="p-6">
        <p className="text-slate-500 text-[11px] font-bold leading-relaxed mb-5 text-center px-2">
          {cleanContent || t('ui.allVerifiedActive')}
        </p>

        {referenceNumber && (
          <div className="mb-6 p-4 bg-slate-50 rounded-2xl border border-slate-100 flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <span className="text-[9px] font-black text-slate-400 uppercase tracking-widest">{t('ui.yourReferenceId')}</span>
              <button
                onClick={() => {
                  navigator.clipboard.writeText(referenceNumber);
                  toast.success(t('ui.referenceCopied'));
                }}
                className="p-1.5 hover:bg-slate-200 rounded-lg transition-colors text-slate-400 hover:text-slate-900 active:scale-90"
              >
                <Copy className="h-3.5 w-3.5" />
              </button>
            </div>
            <p className="text-xl font-black text-slate-900 font-mono tracking-tight text-center">
              {referenceNumber}
            </p>
          </div>
        )}

        <div className="grid grid-cols-2 gap-3">
          <div className="p-3 bg-slate-50 rounded-2xl border border-slate-100 flex items-center gap-2.5">
            <div className="h-7 w-7 bg-white rounded-lg flex items-center justify-center shadow-sm text-brand-primary">
              <Mail className="h-3.5 w-3.5" />
            </div>
            <div>
              <p className="text-[8px] font-black text-slate-400 uppercase tracking-widest leading-none mb-1">{t('ui.status')}</p>
              <p className="text-[10px] font-black text-slate-800">{t('ui.emailSent')}</p>
            </div>
          </div>
          <div className="p-3 bg-slate-50 rounded-2xl border border-slate-100 flex items-center gap-2.5">
            <div className="h-7 w-7 bg-white rounded-lg flex items-center justify-center shadow-sm text-emerald-600">
              <Clock className="h-3.5 w-3.5" />
            </div>
            <div>
              <p className="text-[8px] font-black text-slate-400 uppercase tracking-widest leading-none mb-1">{t('ui.timeline')}</p>
              <p className="text-[10px] font-black text-slate-800">{t('ui.threeFourDays')}</p>
            </div>
          </div>
        </div>
      </div>
    </motion.div>
  );
};

export { OnboardingSuccessCard };
