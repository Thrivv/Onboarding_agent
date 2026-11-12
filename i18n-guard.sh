#!/usr/bin/env bash
# i18n guard — docs/multilingual-flow-approach.html (P0 / P4).
# Fails when language-dependent logic or untranslated message pairs creep
# back in. Run locally or in CI:  ./i18n-guard.sh
set -u
cd "$(dirname "$0")"
fail=0
check() {  # $1 = description, $2 = matches (empty = pass)
  if [ -n "$2" ]; then echo "✗ $1"; echo "$2" | sed 's/^/    /'; fail=1; else echo "✓ $1"; fi
}

FE=frontend/src
check "no English-keyword routing on raw message text (use logicText())" \
  "$(grep -rnE "\(m(sg)?\.content \|\| ''\)\.toLowerCase\(\)|m\.content\.toLowerCase\(\)\.includes\(" $FE/features/onboarding/OnboardingPage.jsx || true)"
check "no English-only member-list regexes (use stripMemberLists())" \
  "$(grep -rnE "Registered Individuals:\(|following beneficial owners:\[" $FE/features/onboarding/OnboardingPage.jsx || true)"
check "no hardcoded English toasts in OnboardingPage (use t('chat.*'))" \
  "$(grep -nE "toast\.(error|success|info)\('[A-Z]" $FE/features/onboarding/OnboardingPage.jsx || true)"

check "no hardcoded English field labels in report/extracted components (use L('...'))" \
  "$(grep -rnE 'label="[A-Z]' $FE/features/onboarding/components/extracted $FE/features/onboarding/components/compliance/ReportBlocks.jsx || true)"
check "no hardcoded Planning steps (use cards.planning.*)" \
  "$(grep -nE '"Securely connecting|>\s*Planning\s*<' $FE/features/onboarding/components/status/PlanningTimeline.jsx || true)"
check "no hardcoded Unified Report header / pills" \
  "$(grep -nE '>UNIFIED REPORT<|>DOCUMENT MANAGER<|: .Verified.\}|Self-Certified' $FE/features/onboarding/OnboardingPage.jsx || true)"

BE=backend/app
check "no ES-else-EN message pairs in backend (use app.i18n.localized / render_message)" \
  "$(grep -rnE 'if (user_)?language == "spanish"' $BE --include=*.py | grep -v 'services/message_generator.py' | grep -v 'app/i18n/' || true)"
check "no hardcoded language=\"english\" call sites" \
  "$(grep -rnE 'language="english"\)?$|language="english",' $BE --include=*.py | grep -vE 'def |: str = |Optional' || true)"

exit $fail
