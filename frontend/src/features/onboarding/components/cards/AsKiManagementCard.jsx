import React, { useEffect, useMemo, useRef, useState } from 'react';
import { selectMoaAuthorisedSignatory } from '../../../../api/keyIndividuals';
import { CheckCircle, Loader, Users } from 'lucide-react';
import { KiLoopCard } from './KiLoopCard';
import logger from '../../../../utils/logger';
import { useLanguage } from '../../../../context/LanguageContext';

const AsKiManagementCard = ({
  userEmail, preloadedMembers, uboNames, ownershipMap, onKiSavedCallback, onProceed,
  memberSource, isCompleted = false, initialIndividuals = null, membersInfo, messages
}) => {
  const { t, language } = useLanguage();
  // ✅ STABILIZE DEPENDENCIES: Use useMemo to prevent infinite update loops
  const effectiveOwnershipMap = useMemo(() => {
    // 1. Check if we have an explicit map passed as a prop
    const hasLocalMap = ownershipMap && Object.keys(ownershipMap).length > 0;
    if (hasLocalMap) return ownershipMap;

    // 2. Build a combined map from message history (Multiple + Single Owner)
    const combinedMap = { ...(membersInfo?.ownershipMap || membersInfo?.ownership_map || {}) };

    if (Array.isArray(messages)) {
      messages.forEach(m => {
        // Handle Multiple Owner flow (explicit ownershipMap field)
        if (m.ownershipMap) {
          Object.assign(combinedMap, m.ownershipMap);
        }
        // Handle Single Owner flow (extractedData/metadata fields)
        const extracted = m.extractedData || m.metadata?.extracted_fields;

        // ⚡️ NEW: Support for Partners array in extracted_fields
        if (Array.isArray(extracted?.partners)) {
          extracted.partners.forEach(p => {
            const name = (p.name_english || p.name || '').trim().toUpperCase();
            const share = p.share_percentage || p.share || p.percentage;
            if (name && share) {
              combinedMap[name] = share;
            }
          });
        }

        if (extracted?.owner?.name_english && extracted?.owner?.share_percentage) {
          combinedMap[extracted.owner.name_english.toUpperCase()] = extracted.owner.share_percentage;
        } else if (extracted?.owner?.name && extracted?.owner?.share) {
          // Additional fallback keys
          combinedMap[extracted.owner.name.toUpperCase()] = extracted.owner.share;
        }
      });
    }


    return combinedMap;
  }, [messages, membersInfo, ownershipMap]);

  const _uboSet = useMemo(() => {
    return new Set((uboNames || [])
      .filter(n => n && typeof n === 'string')
      .map(n => n.toUpperCase()));
  }, [uboNames]);

  logger.log('[DEBUG-SYNC] Chat Card Data Sync:', {
    effectiveMapKeys: Object.keys(effectiveOwnershipMap),
    preloadedMembers
  });

  // memberSource lets callers override the source tag ('SO_OWNER' for Single Owner,
  // defaults to 'MOA_EXTRACTED' for the existing Multiple Owner flow)
  const _src = memberSource || 'MOA_EXTRACTED';

  const [individuals, setIndividuals] = useState(() => {
    if (initialIndividuals && initialIndividuals.length > 0) return initialIndividuals;
    return (preloadedMembers || [])
      .map(name => {
        const displayName = typeof name === 'string' ? name : (name?.name || name?.display_name || '');
        const normalizedName = displayName.trim().toUpperCase();
        const isUbo = _uboSet?.has?.(normalizedName) || false;

        // Comprehensive lookup across possible name formats
        const ownershipText = (effectiveOwnershipMap && (
          effectiveOwnershipMap[normalizedName] ||
          effectiveOwnershipMap[displayName.toUpperCase()] ||
          effectiveOwnershipMap[displayName.trim()] ||
          effectiveOwnershipMap[displayName]
        )) || '';

        return {
          display_name: displayName,
          source: _src,
          // Default role: AS (pre-selected)
          role: 'AS',
          is_authorised_signatory: true,
          is_ubo: isUbo,
          ownershipText: ownershipText,
        };

      })
      // Guard: never render a slot with no name
      .filter(ind => ind.display_name && ind.display_name.trim());
  });

  // Synchronize state if preloadedMembers or ownership data changes
  useEffect(() => {
    if (preloadedMembers && preloadedMembers.length > 0) {
      setIndividuals(prev => {
        if (prev.length > 0) {
          return prev.map(ind => {
            const displayName = ind.display_name || '';
            const normalizedName = displayName.trim().toUpperCase();

            const ownershipText = (effectiveOwnershipMap && (
              effectiveOwnershipMap[normalizedName] ||
              effectiveOwnershipMap[displayName.toUpperCase()] ||
              effectiveOwnershipMap[displayName.trim()] ||
              effectiveOwnershipMap[displayName]
            )) || '';

            const isUbo = _uboSet?.has?.(normalizedName) || false;

            let role = ind.role;
            if (membersInfo?.member_role_map) {
              const globalRole = membersInfo.member_role_map[normalizedName] ||
                membersInfo.member_role_map[displayName.trim()] ||
                membersInfo.member_role_map[displayName];
              if (globalRole) role = globalRole;
            }

            return { ...ind, ownershipText, role, is_authorised_signatory: role === 'AS', is_ubo: isUbo };
          });

        }


        // Otherwise initialize the list
        return preloadedMembers
          .map(name => {
            const displayName = typeof name === 'string' ? name : (name?.name || name?.display_name || '');
            const normalizedName = displayName.trim().toUpperCase();
            const isUbo = _uboSet.has(normalizedName);

            const ownershipText = (effectiveOwnershipMap && (
              effectiveOwnershipMap[normalizedName] ||
              effectiveOwnershipMap[displayName.toUpperCase()] ||
              effectiveOwnershipMap[displayName.trim()] ||
              effectiveOwnershipMap[displayName]
            )) || '';

            // Default role from ground truth or fall back to 'AS'
            let role = 'AS';
            if (membersInfo?.member_role_map) {
              const globalRole = membersInfo.member_role_map[normalizedName] ||
                membersInfo.member_role_map[displayName.trim()] ||
                membersInfo.member_role_map[displayName];
              if (globalRole) role = globalRole;
            }

            return {
              display_name: displayName,
              source: _src,
              role: role,
              is_authorised_signatory: role === 'AS',
              is_ubo: isUbo,
              ownershipText: ownershipText,
            };
          })
          .filter(ind => ind.display_name && ind.display_name.trim());

      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preloadedMembers, effectiveOwnershipMap, _uboSet, _src, membersInfo]);

  const [proceeded, setProceeded] = useState(isCompleted);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    setProceeded(isCompleted);
    if (initialIndividuals && initialIndividuals.length > 0) {
      setIndividuals(initialIndividuals);
    }
  }, [isCompleted, initialIndividuals]);

  // addIndividualRef: called by parent when an AI_ADDED KI is saved via KiLoopCard
  const addIndividualRef = useRef(null);
  addIndividualRef.current = (ki) => {
    // Guard: skip if ki has no name to prevent empty slot appearing in the card
    if (!ki || !ki.display_name?.trim()) return;
    setIndividuals(prev => {
      const already = prev.find(p =>
        (p.id && p.id === ki.id) || p.display_name === ki.display_name
      );
      if (already) return prev;
      return [...prev, { ...ki, role: ki.is_authorised_signatory ? 'AS' : 'MEMBER' }];
    });
  };

  useEffect(() => {
    if (onKiSavedCallback) {
      onKiSavedCallback.register(addIndividualRef);
    }
    return () => {
      if (onKiSavedCallback) onKiSavedCallback.register(null);
    };
  }, [onKiSavedCallback]);

  // Role selector — switches between AS and MEMBER for a given row
  const handleRoleChange = (idx, newRole) => {
    if (proceeded) return;
    setIndividuals(prev => prev.map((ind, i) =>
      i === idx
        ? { ...ind, role: newRole, is_authorised_signatory: newRole === 'AS' }
        : ind
    ));
  };

  const handleProceed = async () => {
    setIsSaving(true);
    // Response from /ki/moa-as-selection — captured so the parent can use
    // the backend's real, reconciliation-aware message (it already checked
    // whether these members' identity documents were uploaded earlier, e.g.
    // bulk-uploaded alongside Ejari/MOA before this card even existed) and
    // decide whether to show the "Add More Individuals?" card immediately,
    // instead of always falling back to a generic "please proceed with
    // identity verification" line even when there's nothing left to verify.
    // Mirrors how the Single Owner path already threads its own response
    // (soResp) through handleAsSelection — this was the missing half.
    let moaResponseData = null;
    try {
      // Persist role selections for MOA-extracted members (Multiple Owner flow).
      // Single Owner (SO_OWNER) path calls /ki/so-as-selection via handleAsSelection.
      const moaMembers = individuals.filter(i => i.source === 'MOA_EXTRACTED');
      if (moaMembers.length > 0) {
        const roleMap = {};
        moaMembers.forEach(m => { roleMap[m.display_name] = m.role || 'AS'; });
        const resp = await selectMoaAuthorisedSignatory({
          email: userEmail,
          language,
          member_role_map: roleMap,
        });
        moaResponseData = resp?.data || null;
      }
    } catch (e) {
      logger.warn('[AsKiCard] Failed to save role map:', e);
    } finally {
      setIsSaving(false);
    }
    setProceeded(true);
    if (onProceed) onProceed(individuals, moaResponseData);
  };

  if (individuals.length === 0 && !proceeded) {
    return null; // Don't show an empty card during planning/initial stages
  }

  // "Select {as} or {member} for each individual below." — the highlighted
  // terms' surrounding words/order vary by language, so the translated
  // template carries literal `{as}`/`{member}` tokens and we split on them
  // (same technique as KiLoopCard's description) rather than hardcoding
  // English word order here.
  const [hintPre, hintAfterAs] = t('cards.asManagement.selectRoleHint').split('{as}');
  const [hintMid, hintPost] = (hintAfterAs || '').split('{member}');

  return (
    <div className="mt-3 p-4 bg-white rounded-xl border-2 border-blue-200 shadow-lg shadow-blue-200">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Users className="h-5 w-5 text-brand-primary" />
          <p className="text-sm font-bold text-brand-secondary">{t('cards.asManagement.title')}</p>
        </div>
        {!proceeded && (
          <span className="text-xs text-gray-400">
            {t(individuals.length !== 1 ? 'cards.asManagement.memberCountPlural' : 'cards.asManagement.memberCount', { count: individuals.length })}
          </span>
        )}
      </div>
      <p className="text-xs text-gray-500 mb-3">
        {hintPre}<span className="font-semibold text-purple-700">{t('cards.common.authorisedSignatory')}</span>{hintMid}{' '}
        <span className="font-semibold text-indigo-700">{t('cards.common.member')}</span>{hintPost}
      </p>

      {/* Individual List */}
      {individuals.length === 0 ? (
        <p className="text-xs text-gray-400 italic mb-3">{t('cards.asManagement.noIndividuals')}</p>
      ) : (
        <div className="space-y-2 mb-3">
          {individuals.map((ind, idx) => (
            <div key={idx} className="bg-white rounded-lg border border-gray-200 p-3">
              <div className="flex items-center gap-2 mb-2">
                <span className="flex-shrink-0 w-5 h-5 rounded-full bg-indigo-100 text-indigo-700 text-[10px] font-bold flex items-center justify-center">
                  {idx + 1}
                </span>
                <p className="flex-1 text-sm font-black text-slate-800 truncate tracking-tight">
                  {ind.display_name}
                </p>
                {ind.ownershipText && (
                  <span className="flex-shrink-0 px-2 py-0.5 bg-blue-50 text-brand-secondary border border-blue-100 rounded-lg text-[9px] font-black tracking-tight shadow-sm">
                    {t('cards.asManagement.share')} {String(ind.ownershipText).split(' ')[0]}
                  </span>
                )}

                {ind.is_ubo && (
                  <span className="flex-shrink-0 px-2 py-0.5 bg-amber-50 text-amber-600 border border-amber-200 rounded-lg text-[10px] font-black tracking-tight">
                    {t('cards.asManagement.ubo')}
                  </span>
                )}
              </div>
              {/* Role selector — two pill buttons */}
              {!proceeded ? (
                <div className="flex gap-2">
                  <button
                    onClick={() => handleRoleChange(idx, 'AS')}
                    className={`flex-1 py-1.5 rounded-lg border text-xs font-semibold transition-all ${ind.role === 'AS'
                      ? 'bg-purple-600 border-purple-600 text-white'
                      : 'bg-white border-gray-300 text-gray-500 hover:border-purple-400 hover:text-purple-600'
                      }`}
                  >
                    {t('cards.common.authorisedSignatory')}
                  </button>
                  <button
                    onClick={() => handleRoleChange(idx, 'MEMBER')}
                    className={`flex-1 py-1.5 rounded-lg border text-xs font-semibold transition-all ${ind.role === 'MEMBER'
                      ? 'bg-indigo-600 border-indigo-600 text-white'
                      : 'bg-white border-gray-300 text-gray-500 hover:border-indigo-400 hover:text-indigo-600'
                      }`}
                  >
                    {t('cards.common.member')}
                  </button>
                </div>
              ) : (
                <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-semibold ${ind.role === 'AS'
                  ? 'bg-purple-100 text-purple-700'
                  : 'bg-indigo-100 text-indigo-700'
                  }`}>
                  {ind.role === 'AS' ? t('cards.common.authorisedSignatory') : t('cards.common.member')}
                </span>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Confirm button — no Add Individual button */}
      {!proceeded ? (
        <div className="mt-1">
          <button style={{ padding: '1.1rem 1.2rem' }}
            onClick={handleProceed}
            disabled={isSaving}
            className="flex-1 py-2.5 bg-brand-primary text-white rounded-xl font-semibold text-sm hover:opacity-90 transition-all disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {isSaving
              ? <><Loader className="h-4 w-4 animate-spin" /> {t('cards.common.saving')}</>
              : <><CheckCircle className="h-4 w-4 text-white" /> {t('cards.asManagement.proceed')}</>
            }
          </button>
        </div>
      ) : (
        <div className="flex items-center gap-2 text-green-700 text-sm font-semibold mt-1 p-2 bg-green-50 rounded-lg border border-green-200">
          <CheckCircle className="h-4 w-4" />
          {t('cards.asManagement.confirmedProceedingVerification')}
        </div>
      )}
    </div>
  );
};


// ============================================================================
// UBO CONFIRMATION CARD (Stage 2 - per-member inline)
// ============================================================================

// eslint-disable-next-line no-unused-vars

export { AsKiManagementCard };
