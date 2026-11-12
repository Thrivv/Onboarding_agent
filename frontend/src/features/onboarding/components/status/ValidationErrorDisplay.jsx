import React from 'react';
import { useLanguage } from '../../../../context/LanguageContext';
import { AlertCircle, CheckCircle } from 'lucide-react';
import { translateDocName } from '../../utils/reportI18n';

const ValidationErrorDisplay = ({ message, expectedDocuments, uploadedType }) => {
  const { t } = useLanguage();
  return (
  <div className="max-w-md w-full mb-1">
    <div className="bg-red-50/50 border-2 border-red-100 rounded-[28px] overflow-hidden shadow-lg shadow-red-100/30">
      <div className="bg-red-600 px-5 py-4 flex items-center gap-3">
        <div className="p-1.5 bg-white/20 rounded-lg backdrop-blur-md border border-white/30">
          <AlertCircle className="h-4 w-4 text-white" />
        </div>
        <div>
          <h2 className="text-[10px] font-black text-white uppercase tracking-[0.2em] opacity-80 mb-0.5">{t('ui.validationAlert')}</h2>
          <p className="text-white text-[15px] font-bold leading-tight">{t('ui.incorrectDocType')}</p>
        </div>
      </div>

      <div className="p-5 space-y-4">
        <div className="bg-white/60 p-3 rounded-2xl border border-red-50">
          <p className="text-[13px] font-bold text-gray-800 leading-relaxed italic">
            "{message}"
          </p>
        </div>

        {expectedDocuments && expectedDocuments.length > 0 && (
          <div className="space-y-2.5">
            <div className="flex items-center gap-2 ps-1">
              <div className="w-1 h-3 bg-red-500 rounded-full" />
              <h3 className="text-[11px] font-black text-red-600 uppercase tracking-widest">{t('ui.requiredInstead')}</h3>
            </div>
            <div className="grid grid-cols-1 gap-1.5">
              {expectedDocuments.map((doc, idx) => (
                <div key={idx} className="flex items-center gap-2.5 bg-white p-2.5 rounded-xl border border-gray-100 shadow-sm transition-all hover:border-red-200">
                  <div className="h-5 w-5 rounded-md bg-red-50 flex items-center justify-center">
                    <CheckCircle className="h-3 w-3 text-red-500" />
                  </div>
                  <span className="text-[12px] font-black text-gray-900 tracking-tight">{translateDocName(t, doc)}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="pt-2 border-t border-red-100/50">
          <p className="text-[11px] font-bold text-gray-500 text-center">
            {t('ui.reuploadCorrect')}
          </p>
        </div>
      </div>
    </div>
  </div>
  );
};

// ============================================================================
// STAGE TRANSITION DISPLAY
// ============================================================================

// eslint-disable-next-line no-unused-vars

export { ValidationErrorDisplay };
