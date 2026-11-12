import React, { useState } from 'react';
import { useLanguage } from '../../../../context/LanguageContext';
import { confirmUbo } from '../../../../api/onboarding';
import { CheckCircle, Loader, User } from 'lucide-react';
import toast from 'react-hot-toast';

const UboConfirmCard = ({ memberName, sharePercentage, suggestedUbo, userEmail, onConfirmed }) => {
  const { t } = useLanguage();
  const [isUbo, setIsUbo] = useState(suggestedUbo);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [confirmed, setConfirmed] = useState(false);

  const handleConfirm = async () => {
    setIsSubmitting(true);
    try {
      const res = await confirmUbo({
        email: userEmail,
        member_name: memberName,
        is_ubo: isUbo,
      });
      toast.success(t('ui.uboSavedToast', { name: memberName }));
      setConfirmed(true);
      if (onConfirmed) onConfirmed({ memberName, isUbo, message: res.data.message });
    } catch (e) {
      toast.error(t('ui.uboSaveFailed'));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="mt-3 p-4 bg-brand-primary rounded-xl border-2 border-amber-200">
      <div className="flex items-center gap-2 mb-2">
        <User className="h-5 w-5 text-amber-600" />
        <p className="text-sm font-bold text-amber-900">{t('ui.uboConfirmation')} {memberName}</p>
      </div>

      {sharePercentage > 0 && (
        <p className="text-xs text-gray-600 mb-3">
          {t('ui.shareOwnership')} <strong>{sharePercentage}{!String(sharePercentage).endsWith('%') ? '%' : ''}</strong>
          {suggestedUbo && <span className="ms-2 text-amber-700 font-semibold">{t('ui.suggestedUbo')}</span>}
        </p>
      )}

      {!confirmed ? (
        <>
          <p className="text-xs text-gray-700 mb-3 font-medium">
            {t('ui.isUboQuestion', { name: memberName })}
          </p>
          <div className="flex gap-3 mb-4">
            <button
              onClick={() => setIsUbo(true)}
              className={`flex-1 py-2 rounded-lg border-2 text-sm font-semibold transition-all ${isUbo
                ? 'bg-amber-500 border-amber-500 text-white'
                : 'bg-white border-gray-300 text-gray-700 hover:border-amber-400'
                }`}
            >
              {t('ui.yesUbo')}
            </button>
            <button
              onClick={() => setIsUbo(false)}
              className={`flex-1 py-2 rounded-lg border-2 text-sm font-semibold transition-all ${!isUbo
                ? 'bg-gray-600 border-gray-600 text-white'
                : 'bg-white border-gray-300 text-gray-700 hover:border-gray-400'
                }`}
            >
              {t('ui.noUbo')}
            </button>
          </div>
          <button
            onClick={handleConfirm}
            disabled={isSubmitting}
            className="w-full py-2.5 bg-brand-primary text-white rounded-xl font-semibold hover:opacity-90 transition-all disabled:opacity-50 flex items-center justify-center gap-2 text-sm"
          >
            {isSubmitting ? (
              <><Loader className="h-4 w-4 animate-spin" /> {t('ui.saving')}</>
            ) : (
              <><CheckCircle className="h-4 w-4" /> {t('ui.confirmUbo')}</>
            )}
          </button>
        </>
      ) : (
        <div className="flex items-center gap-2">
          <CheckCircle className="h-5 w-5 text-green-600" />
          <span className="text-sm font-semibold text-green-700">
            {t('ui.recordedAs', { name: memberName, status: isUbo ? t('ui.ubo') : t('ui.notUbo') })}
          </span>
        </div>
      )}
    </div>
  );
};


// ============================================================================
// SELF-DECLARATION SUMMARY CARD
// ============================================================================

export { UboConfirmCard };
