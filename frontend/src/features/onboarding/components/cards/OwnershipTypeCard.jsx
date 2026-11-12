import React, { useState } from 'react';
import { useLanguage } from '../../../../context/LanguageContext';
import { saveOwnershipType } from '../../../../api/onboarding';
import { CheckCircle, Loader } from 'lucide-react';
import toast from 'react-hot-toast';

const OwnershipTypeCard = ({ userEmail, onSaved, isCompleted = false, savedChoice = null }) => {
  const { t } = useLanguage();
  const [selected, setSelected] = useState(null);
  const [partnershipDetails, setPartnershipDetails] = useState('');
  const [saving, setSaving] = useState(false);

  if (isCompleted) {
    return (
      <div className="mt-3 bg-green-50 border border-green-200 rounded-xl p-4 flex items-center gap-2">
        <CheckCircle className="h-4 w-4 text-green-600 flex-shrink-0" />
        <span className="text-sm text-green-800 font-medium">
          {t('ui.ownershipLabel')} {savedChoice === 'Single Owner' ? t('ui.soleProprietorship') : t('ui.jointOwnership')}
        </span>
      </div>
    );
  }

  const needsDetails = selected && selected !== 'Single Owner';
  const canConfirm = selected === 'Single Owner' || (selected && partnershipDetails);

  const handleConfirm = async () => {
    if (!canConfirm) return;
    setSaving(true);
    try {
      const resp = await saveOwnershipType({
        email: userEmail,
        ownership_type: selected,
        partnership_details: needsDetails ? partnershipDetails : undefined,
      });
      onSaved && onSaved({
        ownership_type: selected,
        partnership_details: needsDetails ? partnershipDetails : null,
        ai_message: resp?.data?.ai_message,
      });
    } catch (err) {
      toast.error(t('ui.ownershipSaveFailed'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mt-3 bg-white border border-gray-200 rounded-xl p-4 space-y-3">
      <p className="text-sm font-medium text-gray-800">
        {t('ui.ownershipQuestion')}
      </p>
      <div className="flex gap-3">
        <button
          type="button"
          onClick={() => { setSelected('Single Owner'); setPartnershipDetails(''); }}
          className={`flex-1 px-4 py-2 rounded-lg border-2 text-sm font-medium transition-colors ${selected === 'Single Owner' ? 'border-brand-primary bg-blue-50' : 'border-gray-300 hover:border-brand-primary'}`}
        >
          {t('ui.soleProprietorship')}
        </button>
        <button
          type="button"
          onClick={() => setSelected('Partnership')}
          className={`flex-1 px-4 py-2 rounded-lg border-2 text-sm font-medium transition-colors ${selected && selected !== 'Single Owner' ? 'border-brand-primary bg-blue-50' : 'border-gray-300 hover:border-brand-primary'}`}
        >
          {t('ui.jointOwnership')}
        </button>
      </div>

      {needsDetails && (
        <div className="space-y-2 pt-1">
          <p className="text-sm text-gray-700">{t('ui.ownersTypeQuestion')}</p>
          {[
            'All shareholders are individual persons',
            'One or more shareholders are companies or other legal entities',
          ].map((detail) => (
            <label
              key={detail}
              className={`block p-3 border-2 rounded-lg cursor-pointer text-sm transition-colors ${partnershipDetails === detail ? 'border-brand-primary bg-blue-50' : 'border-gray-300 hover:border-brand-primary'}`}
            >
              <input
                type="radio"
                name="partnership_details"
                value={detail}
                checked={partnershipDetails === detail}
                onChange={(e) => setPartnershipDetails(e.target.value)}
                className="me-2"
              />
              {detail === 'All shareholders are individual persons' ? t('ui.allIndividuals') : t('ui.someCompanies')}
            </label>
          ))}
        </div>
      )}

      <button
        type="button"
        onClick={handleConfirm}
        disabled={saving || !canConfirm}
        className="w-full flex items-center justify-center gap-2 gradient-btn text-white px-4 py-2 rounded-lg text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-40"
      >
        {saving ? <Loader className="h-4 w-4 animate-spin" /> : <CheckCircle className="h-4 w-4" />}
        {t('ui.confirm')}
      </button>
    </div>
  );
};

// ============================================================================
// AS / KI MANAGEMENT CARD
// Shown after FATCA is completed. Allows adding multiple AS / Key Individuals.
// Also shown after MOA stage transition (moaAsTrigger) with pre-populated members.
// ============================================================================

export { OwnershipTypeCard };
