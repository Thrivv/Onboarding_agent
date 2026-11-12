import React, { useState } from 'react';
import { addKeyIndividualViaAi } from '../../../../api/keyIndividuals';
import { CheckCircle, Loader, Phone, User } from 'lucide-react';
import toast from 'react-hot-toast';
import { useLanguage } from '../../../../context/LanguageContext';

const KiRoleAssignCard = ({ userEmail, extractedData, documentId, onSaved }) => {
  const { t } = useLanguage();
  const [role, setRole] = useState('AS');
  const [isSaving, setIsSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  // Try EID-style name fields first, then passport-style (given_names + surname)
  const extractedName = (() => {
    const eidName = extractedData?.name_english || extractedData?.full_name || extractedData?.name || '';
    if (eidName.trim()) return eidName.trim();
    const given = (extractedData?.given_names || '').trim();
    const surname = (extractedData?.surname || '').trim();
    if (given || surname) return `${given} ${surname}`.trim();
    return t('cards.kiRoleAssign.defaultIndividual');
  })();

  const handleSave = async () => {
    setIsSaving(true);
    try {
      const res = await addKeyIndividualViaAi({
        email: userEmail,
        role,
        document_id: documentId,
        extracted_data: extractedData,
      });
      if (res.data.success) {
        setSaved(true);
        toast.success(t('cards.kiRoleAssign.toastAdded', { name: res.data.display_name || extractedName }));
        if (onSaved) onSaved(res.data);
      } else {
        toast.error(t('cards.kiRoleAssign.toastFailed'));
      }
    } catch (e) {
      toast.error(t('cards.kiRoleAssign.toastFailed'));
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="mt-3 p-4 bg-white rounded-xl border-2 border-blue-200">
      <div className="flex items-center gap-2 mb-3">
        <div className="p-1.5 bg-brand-primary rounded-lg">
          <User className="h-4 w-4 text-white" />
        </div>
        <p className="text-sm font-bold text-brand-primary">{t('cards.kiRoleAssign.title')}</p>
      </div>
      <p className="text-xs text-gray-700 mb-1">
        {t('cards.kiRoleAssign.verifiedFor')} <span className="font-semibold text-brand-primary">{extractedName}</span>
      </p>
      <p className="text-xs text-gray-700 mb-4">{t('cards.kiRoleAssign.selectRole')}</p>

      {!saved ? (
        <>
          <div className="flex gap-3 mb-4">
            <button
              onClick={() => setRole('AS')}
              className={`flex-1 py-2.5 rounded-xl border-2 text-sm font-semibold transition-all ${role === 'AS'
                ? 'bg-brand-primary border-brand-primary text-white'
                : 'bg-white border-gray-300 text-brand-primary hover:border-brand-primary'
                }`}
            >
              {t('cards.common.authorisedSignatory')}
            </button>
            <button
              onClick={() => setRole('MEMBER')}
              className={`flex-1 py-2.5 rounded-xl border-2 text-sm font-semibold transition-all ${role === 'MEMBER'
                ? 'bg-brand-primary border-brand-primary text-white'
                : 'bg-white border-gray-300 text-brand-primary hover:border-brand-primary'
                }`}
            >
              {t('cards.common.member')}
            </button>
          </div>
          <button
            onClick={handleSave}
            disabled={isSaving}
            className="w-full py-2.5 bg-brand-primary text-white rounded-xl font-semibold text-sm hover:opacity-90 transition-all disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {isSaving
              ? <><Loader className="h-4 w-4 animate-spin text-white" /> {t('cards.common.saving')}</>
              : <><CheckCircle className="h-4 w-4 text-white" /> {t('cards.kiRoleAssign.confirmSave')}</>
            }
          </button>
        </>
      ) : (
        <div className="flex items-center gap-2 text-green-700 text-sm font-semibold p-2 bg-green-50 rounded-lg border border-green-200">
          <CheckCircle className="h-4 w-4" />
          {t('cards.kiRoleAssign.addedAs', {
            name: extractedName,
            role: role === 'AS' ? t('cards.common.authorisedSignatory') : t('cards.common.member'),
          })}
        </div>
      )}
    </div>
  );
};


// ============================================================================
// KI DETAILS CARD
// Shown after KiRoleAssignCard confirms a role.  Collects Email (with OTP),
// Phone Number, and Share Percentage for the individual whose EID / Passport
// was just verified.  Applies to ALL corporate account types:
//   - Single Owner      (SO_OWNER)
//   - Multiple Owners   (MOA_EXTRACTED / AI_ADDED)
//   - Savings           (same AI_ADDED path)
// ============================================================================

export { KiRoleAssignCard };
