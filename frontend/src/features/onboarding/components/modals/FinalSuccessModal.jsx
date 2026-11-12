import React from 'react';
import { useLanguage } from '../../../../context/LanguageContext';
import { CheckCircle, Copy } from 'lucide-react';
import toast from 'react-hot-toast';

const FinalSuccessModal = ({ isOpen, onClose, referenceNumber }) => {
  const { t } = useLanguage();
  if (!isOpen) return null;
  return (
    <div className="fixed inset-0 z-[1000] flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-in fade-in duration-300">
      <div className="bg-white rounded-[40px] shadow-2xl max-w-lg w-full p-10 flex flex-col items-center text-center animate-in zoom-in-95 duration-300">
        <div className="w-20 h-20 bg-emerald-100 rounded-full flex items-center justify-center mb-6 shadow-xl shadow-emerald-500/10">
          <CheckCircle className="h-10 w-10 text-emerald-600" />
        </div>
        <h2 className="text-2xl font-black text-slate-900 mb-4 uppercase tracking-tight">{t('ui.submissionSuccessful')}</h2>
        <p className="text-slate-600 mb-8 leading-relaxed font-medium">
          {t('ui.submittedProcessing')}
        </p>

        {referenceNumber && (
          <div className="w-full p-6 bg-slate-50 rounded-3xl border border-slate-100 mb-8 relative group">
            <div className="flex items-center justify-between mb-2">
              <p className="text-[11px] font-black text-slate-400 uppercase tracking-widest">{t('ui.referenceNumber')}</p>
              <button
                onClick={() => {
                  navigator.clipboard.writeText(referenceNumber);
                  toast.success(t('ui.referenceCopied'));
                }}
                className="p-2 hover:bg-slate-200 rounded-xl transition-all text-slate-400 hover:text-slate-900 active:scale-90"
                title={t('ui.copyReferenceNumber')}
              >
                <Copy className="h-4 w-4" />
              </button>
            </div>
            <p className="text-2xl font-black text-slate-900 font-mono tracking-tight break-all">
              {referenceNumber}
            </p>
            <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mt-2 italic">
              {t('ui.saveForReference')}
            </p>
          </div>
        )}
        <button
          onClick={onClose}
          className="w-full py-4 bg-slate-900 text-white rounded-2xl font-black uppercase tracking-widest hover:bg-slate-800 transition-all shadow-xl shadow-slate-200 active:scale-[0.98]"
        >
          {t('ui.close')}
        </button>
      </div>
    </div>
  );
};

// ============================================================================
// SUMMARY DECLARATION REPORT BLOCK (SIDEBAR)
// ============================================================================

export { FinalSuccessModal };
