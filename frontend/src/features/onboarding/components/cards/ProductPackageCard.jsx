import React, { useEffect, useState } from 'react';
import { getPackageRecommendation, getPackageStatus, savePackage } from '../../../../api/products';
import Sidebar from '../../../../components/layout/Sidebar';
import { CheckCircle, Edit, Loader, Package } from 'lucide-react';
import toast from 'react-hot-toast';
import { CONFIDENCE_STYLES, PACKAGE_DEFINITIONS, PACKAGE_ICONS } from '../../config/packages';
import { useLanguage } from '../../../../context/LanguageContext';

const ProductPackageCard = ({ userEmail, onConfirmed }) => {
  const { t } = useLanguage();
  // ── package selection state ──────────────────────────────────────────────
  const [selected, setSelected] = useState(null);
  const [availedProducts, setAvailedProducts] = useState([]);
  const [isSaving, setIsSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [savedPackage, setSavedPackage] = useState('');
  const [savedProducts, setSavedProducts] = useState([]);

  // ── AI recommendation state ──────────────────────────────────────────────
  const [aiRec, setAiRec] = useState(null);   // { recommended_package, confidence, reasoning, key_matches, nature_of_business }
  const [isLoadingRec, setIsLoadingRec] = useState(true);   // show spinner until rec arrives
  const [recError, setRecError] = useState(false);  // silent error — fallback shown

  // ── Step 1: check if already saved; then fetch AI recommendation ─────────
  useEffect(() => {
    if (!userEmail) return;

    // Check existing saved status first
    getPackageStatus(userEmail)
      .then(res => {
        if ((res.data?.status === 'completed' || !!res.data?.selected_package) && res.data?.selected_package) {
          const pkg = res.data.selected_package;
          const products = res.data.availed_products || [];
          setSelected(pkg);
          setAvailedProducts(products);
          setSavedPackage(pkg);
          setSavedProducts(products);
          setSaved(true);
          setIsLoadingRec(false); // skip recommendation — already done
          return;
        }

        // Not yet saved — fetch AI recommendation
        getPackageRecommendation(userEmail)
          .then(recRes => {
            const rec = recRes.data;
            setAiRec(rec);
            // Pre-select the recommended package so user sees it highlighted
            const recPkg = rec?.recommended_package;
            if (recPkg && PACKAGE_DEFINITIONS[recPkg] !== undefined) {
              setSelected(recPkg);
              setAvailedProducts([...PACKAGE_DEFINITIONS[recPkg]]);
            }
          })
          .catch(() => setRecError(true))
          .finally(() => setIsLoadingRec(false));
      })
      .catch(() => {
        // Status fetch failed — still try to get recommendation
        getPackageRecommendation(userEmail)
          .then(recRes => {
            const rec = recRes.data;
            setAiRec(rec);
            const recPkg = rec?.recommended_package;
            if (recPkg && PACKAGE_DEFINITIONS[recPkg] !== undefined) {
              setSelected(recPkg);
              setAvailedProducts([...PACKAGE_DEFINITIONS[recPkg]]);
            }
          })
          .catch(() => setRecError(true))
          .finally(() => setIsLoadingRec(false));
      });
  }, [userEmail]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── handlers ─────────────────────────────────────────────────────────────
  const handlePackageClick = (pkg) => {
    setSelected(pkg);
    setAvailedProducts([...PACKAGE_DEFINITIONS[pkg]]);
  };

  const handleConfirm = async () => {
    if (!selected) { toast.error(t('cards.productPackage.toastSelectPackage')); return; }
    if (availedProducts.length === 0) {
      toast.error(t('cards.productPackage.toastSelectPackage'));
      return;
    }
    setIsSaving(true);
    try {
      const res = await savePackage({
        email: userEmail,
        selected_package: selected,
        availed_products: availedProducts,
      });
      if (res.data.success) {
        setSaved(true);
        setSavedPackage(selected);
        setSavedProducts([...availedProducts]);
        toast.success(t('cards.productPackage.toastSelectedSuccess', { name: selected }));
        window.dispatchEvent(new Event('compliance-updated')); // Trigger Sidebar refresh
        if (onConfirmed) onConfirmed(res.data);
      } else {
        toast.error(t('cards.productPackage.toastSaveFailed'));
      }
    } catch (e) {
      toast.error(e.response?.data?.detail || t('cards.productPackage.toastSaveFailed'));
    } finally {
      setIsSaving(false);
    }
  };

  // ── Confirmed view (unchanged) ────────────────────────────────────────────
  if (saved) {
    return (
      <div className="mt-3 bg-white border border-slate-100 rounded-[32px] overflow-hidden shadow-2xl shadow-slate-200/50 animate-in zoom-in-95 duration-700">
        <div className="px-6 py-4 bg-slate-50 border-b border-slate-100 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="p-1.5 bg-indigo-100 rounded-lg">
              <Package className="h-3.5 w-3.5 text-indigo-600" />
            </div>
            <h3 className="text-[10px] font-black text-slate-400 uppercase tracking-[0.2em]">{t('cards.productPackage.packageSelection')}</h3>
          </div>
          <button
            onClick={() => setSaved(false)}
            className="flex items-center gap-2 px-4 py-2.5 bg-brand-primary hover:opacity-90 rounded-xl text-[10px] font-black text-white uppercase tracking-widest transition-all active:scale-95 shadow-lg shadow-indigo-200"
          >
            <Edit className="h-3.5 w-3.5" />
            {t('cards.productPackage.editPackage')}
          </button>
        </div>
        <div className="p-6">
          <div className="flex items-start gap-5 mb-6">
            <div className="h-16 w-16 bg-brand-primary rounded-2xl flex items-center justify-center shadow-lg shadow-indigo-200 shrink-0 text-3xl">
              {PACKAGE_ICONS[savedPackage]}
            </div>
            <div className="pt-2">
              <p className="text-2xl font-black text-slate-900 tracking-tight leading-none">
                {t('cards.productPackage.packageLabel', { name: savedPackage })}
              </p>
              <p className="text-[11px] font-bold text-indigo-600 uppercase tracking-widest mt-2 bg-indigo-50 px-2 py-0.5 rounded-md w-fit">
                {t('cards.productPackage.confirmed')}
              </p>
            </div>
          </div>
          {savedProducts.length > 0 && (
            <div className="space-y-3">
              <p className="text-[10px] font-black text-slate-400 uppercase tracking-wider ml-1">{t('cards.productPackage.includedServices')}</p>
              <div className="flex flex-wrap gap-2">
                {savedProducts.map((prod, idx) => (
                  <div key={idx} className="px-3 py-1.5 bg-slate-50 border border-slate-100 rounded-xl flex items-center gap-2 transition-all hover:border-indigo-200 group">
                    <div className="h-1.5 w-1.5 rounded-full bg-indigo-400 group-hover:bg-indigo-500 transition-colors" />
                    <span className="text-[11px] font-black text-slate-600 tracking-tight">{prod}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  // ── Loading view — AI is fetching recommendation ──────────────────────────
  if (isLoadingRec) {
    return (
      <div className="mt-3 rounded-xl border-2 border-indigo-200 overflow-hidden bg-white">
        <div className="px-4 py-3 bg-brand-primary text-white">
          <p className="text-sm font-bold flex items-center gap-2">
            <Loader className="h-4 w-4 animate-spin" /> {t('cards.productPackage.aiAnalysing')}
          </p>
          <p className="text-xs opacity-80 mt-0.5">{t('cards.productPackage.matchingBusiness')}</p>
        </div>
        <div className="p-5 space-y-3">
          {[
            t('cards.productPackage.stepReadingNob'),
            t('cards.productPackage.stepMatching'),
            t('cards.productPackage.stepGenerating'),
            t('cards.productPackage.stepConfidence'),
          ].map((step, i) => (
            <div key={i} className="flex items-center gap-3">
              <div className={`h-2 w-2 rounded-full flex-shrink-0 ${i === 0 ? 'bg-indigo-500 animate-pulse' : 'bg-gray-200'}`} />
              <span className={`text-xs ${i === 0 ? 'text-indigo-600 font-semibold' : 'text-gray-400'}`}>{step}</span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  // ── Main selection view ───────────────────────────────────────────────────
  const confStyle = aiRec ? (CONFIDENCE_STYLES[aiRec.confidence] || CONFIDENCE_STYLES.medium) : null;
  const nobDisplay = aiRec?.nature_of_business?.length
    ? aiRec.nature_of_business.slice(0, 4).join(', ') + (aiRec.nature_of_business.length > 4 ? ` +${aiRec.nature_of_business.length - 4} more` : '')
    : null;

  return (
    <div className="mt-3 rounded-xl border-2 border-blue-200 overflow-hidden bg-white">
      {/* Header */}
      <div className="px-4 py-3 bg-brand-primary text-white">
        <p className="text-sm font-bold">{t('cards.productPackage.selectYourPackage')}</p>
        <p className="text-xs opacity-80 mt-0.5">
          {aiRec ? t('cards.productPackage.aiSuggested') : t('cards.productPackage.chooseFits')}
        </p>
      </div>

      {/* ── AI Recommendation Banner ── */}
      {aiRec && !recError && (
        <div className="mx-4 mt-4 rounded-xl border-2 border-indigo-300 overflow-hidden shadow-sm">
          {/* Banner top bar */}
          <div className="bg-indigo-600 px-3 py-2 flex items-center gap-2">
            <span className="text-base">🤖</span>
            <span className="text-[11px] font-black text-white uppercase tracking-widest">{t('cards.productPackage.aiRecommended')}</span>
            {confStyle && (
              <span className={`ml-auto text-[10px] font-bold px-2 py-0.5 rounded-full ${confStyle.bg} ${confStyle.text}`}>
                {confStyle.label}
              </span>
            )}
          </div>

          {/* Banner body */}
          <div className="bg-indigo-50 p-3">
            {/* Recommended package name */}
            <div className="flex items-center gap-2 mb-2">
              <span className="text-2xl">{PACKAGE_ICONS[aiRec.recommended_package]}</span>
              <div>
                <p className="text-base font-black text-slate-900 leading-none">{t('cards.productPackage.packageLabel', { name: aiRec.recommended_package })}</p>
                <p className="text-[10px] text-indigo-500 font-semibold mt-0.5">✨ {t('cards.productPackage.aiPickForProfile')}</p>
              </div>
            </div>

            {/* NOB context */}
            {nobDisplay && (
              <p className="text-[10px] text-slate-500 mb-2">
                <span className="font-semibold text-slate-600">{t('cards.productPackage.basedOn')} </span>{nobDisplay}
              </p>
            )}

            {/* Reasoning */}
            {aiRec.reasoning && (
              <div className="bg-white rounded-lg p-2.5 mb-2 border border-indigo-100">
                <p className="text-[9px] font-black text-indigo-400 uppercase tracking-widest mb-1">✨ {t('cards.productPackage.whyThisPackage')}</p>
                <p className="text-[11px] text-slate-600 leading-relaxed">{aiRec.reasoning}</p>
              </div>
            )}

            {/* Key matches */}
            {aiRec.key_matches?.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {aiRec.key_matches.map((match, i) => (
                  <span key={i} className="text-[10px] font-semibold px-2 py-0.5 bg-indigo-100 text-indigo-700 rounded-full">
                    ✓ {match}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Package grid ── */}
      <div className={`${aiRec && !recError ? 'mt-3' : 'mt-0'}`}>
        {aiRec && !recError && (
          <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest px-4 mb-2">
            {t('cards.productPackage.orChooseDifferent')}
          </p>
        )}
        <div className="grid grid-cols-2 gap-3 px-4 pb-2">
          {Object.entries(PACKAGE_DEFINITIONS).map(([pkg, products]) => {
            const isSelected = selected === pkg;
            const isAiPick = aiRec?.recommended_package === pkg;
            return (
              <div
                key={pkg}
                onClick={() => handlePackageClick(pkg)}
                className={`relative rounded-xl border-2 cursor-pointer transition-all p-3 ${isSelected
                  ? 'border-indigo-500 bg-indigo-50 shadow-md'
                  : 'border-gray-200 bg-gray-50 hover:border-indigo-300 hover:bg-indigo-50/50'
                  }`}
              >
                {/* AI Pick ribbon */}
                {isAiPick && (
                  <span className="absolute top-0 right-0 bg-indigo-600 text-white text-[8px] font-black px-2 py-0.5 rounded-bl-lg rounded-tr-xl uppercase tracking-wider">
                    ✨ {t('cards.productPackage.aiPick')}
                  </span>
                )}

                <div className="flex items-center justify-between mb-2">
                  <p className="text-sm font-bold text-gray-800">{pkg}</p>
                  <span className="text-base">{PACKAGE_ICONS[pkg]}</span>
                </div>

                <ul className="space-y-1">
                  {products.map(p => (
                    <li key={p} className="text-xs text-gray-600 flex items-center gap-1">
                      <span className="w-1 h-1 rounded-full bg-indigo-400 flex-shrink-0" />
                      {p}
                    </li>
                  ))}
                </ul>

                {isSelected && (
                  <div className="absolute top-2 left-2">
                    <CheckCircle className="h-4 w-4 text-indigo-500" />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Confirm button */}
      <div className="px-4 pb-4">
        <button
          onClick={handleConfirm}
          disabled={isSaving || !selected}
          className="w-full py-2.5 bg-brand-primary text-white rounded-xl font-semibold text-sm hover:opacity-90 transition-all disabled:opacity-40 flex items-center justify-center gap-2"
        >
          {isSaving
            ? <><Loader className="h-4 w-4 animate-spin" /> {t('cards.common.saving')}</>
            : <><CheckCircle className="h-4 w-4" /> {selected ? t('cards.productPackage.confirmPackage', { name: selected }) : t('cards.productPackage.confirmPackageSelection')}</>
          }
        </button>
      </div>
    </div>
  );
};

// ============================================================================
// KI LOOP CARD — "Do you want to add another AS / KI?"
// Shown after all current members' EIDs are verified.
// ============================================================================

export { ProductPackageCard };
