import React, { useEffect, useState } from 'react';
import { CheckCircle, User, Users } from 'lucide-react';
import { useLanguage } from '../../../../context/LanguageContext';

const KiLoopCard = ({ onAddAnother, onProceed, isCompleted = false, initialChoice = null }) => {
  const { t } = useLanguage();
  const [decided, setDecided] = useState(isCompleted);
  const [choice, setChoice] = useState(initialChoice);

  // The description sentence has the two highlighted terms embedded inside
  // it, and their position/surrounding words vary by language (AR/ES word
  // order differs from EN) — so the translated template carries literal
  // `{as}`/`{ki}` placeholder tokens and we split on those rather than
  // hardcoding "X or Y" order here.
  const [descPre, descAfterAs] = t('cards.kiLoop.description').split('{as}');
  const [descMid, descPost] = (descAfterAs || '').split('{ki}');

  useEffect(() => {
    setDecided(isCompleted);
    setChoice(initialChoice);
  }, [isCompleted, initialChoice]);

  const handleYes = () => {
    setDecided(true);
    setChoice('yes');
    if (onAddAnother) onAddAnother();
  };

  const handleNo = () => {
    setDecided(true);
    setChoice('no');
    if (onProceed) onProceed();
  };

  return (
    <div className="mt-3 p-4 bg-white rounded-xl border-2 border-indigo-200 shadow-lg shadow-indigo-200">
      <div className="flex items-center gap-2 mb-3">
        <Users className="h-5 w-5 text-brand-primary" />
        <p className="text-sm font-bold text-brand-secondary">{t('cards.kiLoop.title')}</p>
      </div>
      <p className="text-xs text-gray-600 mb-4">
        {descPre}<span className="font-semibold text-purple-700">{t('cards.common.authorisedSignatory')}</span>{descMid}{' '}
        <span className="font-semibold text-indigo-700">{t('cards.common.keyIndividual')}</span>{descPost}
      </p>
      {!decided ? (
        <div className="flex gap-3">
          <button
            onClick={handleYes}
            className="flex-1 py-2.5 bg-brand-primary text-white rounded-xl font-semibold text-sm hover:opacity-90 transition-all flex items-center justify-center gap-2"
          >
            <span className="text-base leading-none text-white">+</span> {t('cards.kiLoop.yesAddAnother')}
          </button>
          <button
            onClick={handleNo}
            className="flex-1 py-2.5 border-2 border-gray-300 text-gray-700 rounded-xl font-semibold text-sm hover:bg-gray-50 transition-all flex items-center justify-center gap-2"
          >
            <CheckCircle className="h-4 w-4" /> {t('cards.kiLoop.noProceed')}
          </button>
        </div>
      ) : (
        <div className={`flex items-center gap-2 text-sm font-semibold p-2 rounded-lg border ${choice === 'yes' ? 'bg-indigo-50 text-indigo-700 border-indigo-200' : 'bg-green-50 text-green-700 border-green-200'
          }`}>
          <CheckCircle className="h-4 w-4" />
          {choice === 'yes'
            ? t('cards.kiLoop.uploadNext')
            : t('cards.kiLoop.confirmedProceeding')}
        </div>
      )}
    </div>
  );
};


// ============================================================================
// KI ROLE ASSIGN CARD — shown after OCR extracts a new individual's EID/Passport
// User assigns role (AS / Member) then calls /ki/add-ai
// ============================================================================

export { KiLoopCard };
