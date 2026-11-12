// frontend/src/features/onboarding/components/OnboardingErrorBoundary.jsx
//
// C5 — feature-level error boundary.
//
// WHY THIS IS SEPARATE FROM components/common/ErrorBoundary.jsx
//
// The app-level boundary is correct and stays where it is. Its fallback is a
// full-screen "Oops! Something went wrong" with Reload and Go Home. That is
// the right response to a crash in the shell — routing, auth, layout.
//
// It is the wrong response to a crash in one onboarding card. Onboarding is a
// long, stateful conversation: uploaded documents, verified EIDs, a KI loop
// part-way through. Replacing all of it with a full-page error because a
// single ProductPackageCard threw means the user loses sight of work that is,
// in fact, safely persisted on the backend. The chat is still readable. The
// input still works. Every other card still renders.
//
// So this boundary sits INSIDE the conversation and degrades one region.
//
//   app-level boundary   →  the shell died, reload is the only move
//   this boundary        →  one card died, the conversation continues
//
// WHAT IT DOES NOT CATCH — read this before trusting it
//
// React error boundaries catch errors thrown during render, in lifecycle
// methods, and in constructors of the tree below them. They do NOT catch:
//
//   - errors inside event handlers        (onClick, onChange, onSubmit)
//   - errors in async code               (fetch .then, await, setTimeout)
//   - errors thrown by the boundary itself
//
// This matters for this codebase specifically. Both render bugs found by
// walking the flows in B8 — the vanishing typed messages and the FATCA card
// needing a refresh — would NOT have been caught here. Neither one threw.
// One filtered a message out; the other never re-ran a sync. A boundary sees
// exceptions, not wrong answers.
//
// Treat this as a blast-radius limiter, not a bug detector.

import React from 'react';
import { AlertTriangle, RotateCcw } from 'lucide-react';
import { reportClientError } from '../../../api/errorLogger';
import logger from '../../../utils/logger';
import { tStatic } from '../../../i18n/tStatic';

// After this many retries in the same region we stop offering the button.
// A card that throws deterministically will throw again, and an endless
// "Try again" that never works is worse than saying so.
const MAX_RETRIES = 2;

class OnboardingErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null, retries: 0 };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    const region = this.props.region || 'onboarding';
    logger.error(`[OnboardingErrorBoundary:${region}]`, error, errorInfo);

    // Routed to the same backend sink as every other client error
    // (backend/app/api/routes/frontend_logs.py). The source prefix is what
    // makes a card crash findable in logs/frontend/ without grepping stacks.
    reportClientError({
      message: error?.message || String(error),
      stack: error?.stack,
      componentStack: errorInfo?.componentStack,
      source: `onboarding-card:${region}`,
    });
  }

  componentDidUpdate(prevProps) {
    // Reset when the caller says the context changed — a new message id, a
    // stage transition. Without this, one bad render would leave the region
    // dead for the rest of the session even after the cause had passed.
    if (
      this.state.hasError &&
      this.props.resetKey !== undefined &&
      this.props.resetKey !== prevProps.resetKey
    ) {
      this.setState({ hasError: false, error: null });
    }
  }

  handleRetry = () => {
    this.setState((s) => ({
      hasError: false,
      error: null,
      retries: s.retries + 1,
    }));
  };

  render() {
    if (!this.state.hasError) {
      return this.props.children;
    }

    const label = this.props.label || tStatic('ui.thisStep');
    const canRetry = this.state.retries < MAX_RETRIES;

    return (
      <div className="w-full mt-3">
        <div className="rounded-2xl border border-amber-200 bg-amber-50 px-5 py-4">
          <div className="flex items-start gap-3">
            <AlertTriangle className="h-5 w-5 flex-shrink-0 text-amber-600 mt-0.5" />
            <div className="flex-1 min-w-0">
              <p className="text-[15px] font-semibold text-amber-900">
                {tStatic('ui.couldNotBeDisplayed', { what: label })}
              </p>
              <p className="mt-1 text-[13px] leading-relaxed text-amber-800">
                {canRetry
                  ? tStatic('ui.nothingLostContinue')
                  : tStatic('ui.nothingLostRefresh')}
              </p>

              {canRetry && (
                <button
                  type="button"
                  onClick={this.handleRetry}
                  className="mt-3 inline-flex items-center gap-2 rounded-xl border border-amber-300 bg-white px-4 py-2 text-[13px] font-semibold text-amber-900 transition-colors hover:bg-amber-100"
                >
                  <RotateCcw className="h-4 w-4" />
                  {tStatic('ui.tryAgain')}
                </button>
              )}

              {process.env.NODE_ENV === 'development' && this.state.error && (
                <details className="mt-3 text-[12px] font-mono text-amber-900">
                  <summary className="cursor-pointer hover:text-amber-950">
                    {this.props.region || 'region'} — {String(this.state.error)}
                  </summary>
                  <pre className="mt-2 overflow-auto whitespace-pre-wrap">
                    {this.state.error?.stack}
                  </pre>
                </details>
              )}
            </div>
          </div>
        </div>
      </div>
    );
  }
}

export { OnboardingErrorBoundary };
export default OnboardingErrorBoundary;
