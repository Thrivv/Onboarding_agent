// frontend/src/features/onboarding/utils/cardState.js
//
// Derive interactive-card completion from the conversation history itself
// (docs/multilingual-flow-approach.html, rule 4 — "the server owns card
// state").
//
// Completion flags such as asSelectionCompleted / kiLoopCompleted used to be
// set only on in-memory message objects when the user clicked a card. Any
// rebuild of the message list from stored history — a reload, a re-login,
// or a language switch (which re-fetches the translated history) — lost
// them. The language-switch path tried to carry them over by message id,
// but a card the user had just completed was usually a LIVE message with a
// client-side id ('as-confirm-…', 'bulk-result-…') that never matches its
// stored row's id, so exactly the most recent card reopened as unsubmitted.
//
// Every card action already writes a follow-up row with a distinct
// metadata.message_type, so "was this card acted on?" is answerable from
// history alone — the same answer on every rebuild, in every language.
//
// Pure function: returns a new array; messages that change are shallow-copied.

const typeOf = (m) => (m && m.metadata && m.metadata.message_type) || null;

const AS_DONE_TYPES = new Set(['ki_moa_as_saved', 'ki_so_as_saved']);
const KI_ADD_TYPES = new Set(['ki_ai_added', 'ki_added', 'ki_contact_info_saved']);
const isKiLoopPrompt = (m) => !!(m && (m.kiLoopPrompt || m.ki_loop_prompt || (m.metadata && m.metadata.ki_loop_prompt)));

export function deriveCardState(messages) {
  if (!Array.isArray(messages) || messages.length === 0) return messages;
  const types = messages.map(typeOf);

  return messages.map((m, i) => {
    let out = m;
    const set = (key, value) => {
      if (out[key] === value) return;
      if (out === m) out = { ...m };
      out[key] = value;
    };

    // Message-level confirmations
    if (types[i] === 'fatca_confirmed') set('isFatcaConfirmed', true);
    if (types[i] === 'pep_confirmed') set('isPepConfirmed', true);
    if (types[i] === 'product_package_saved') set('isProductPackageConfirmed', true);

    // Authorised Signatory / Member card: done once a later "AS saved" row exists.
    if ((m.moaAsTrigger || m.asKiTrigger) && !m.asSelectionCompleted) {
      for (let j = i + 1; j < messages.length; j++) {
        if (AS_DONE_TYPES.has(types[j]) || (messages[j].metadata && messages[j].metadata.as_selection_completed)) {
          set('asSelectionCompleted', true);
          break;
        }
      }
    }

    // "Add More Individuals?" card: the first thing after it tells us the choice.
    if (isKiLoopPrompt(m) && !m.kiLoopCompleted) {
      for (let j = i + 1; j < messages.length; j++) {
        if (types[j] === 'ki_loop_finalized') { set('kiLoopCompleted', true); set('kiLoopChoice', 'no'); break; }
        if (KI_ADD_TYPES.has(types[j]) || isKiLoopPrompt(messages[j])) { set('kiLoopCompleted', true); set('kiLoopChoice', 'yes'); break; }
      }
    }

    // FATCA trigger card: confirmed once a later fatca_confirmed row exists.
    if (m.fatcaTrigger && !m.isFatcaConfirmed) {
      for (let j = i + 1; j < messages.length; j++) {
        if (types[j] === 'fatca_confirmed') { set('isFatcaConfirmed', true); break; }
      }
    }
    return out;
  });
}
