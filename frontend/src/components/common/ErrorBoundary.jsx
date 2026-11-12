// frontend/src/components/common/ErrorBoundary.jsx

import React from 'react';
import { AlertTriangle, RefreshCw, Home } from 'lucide-react';
import { reportClientError } from '../../api/errorLogger';
import logger from '../../utils/logger';
import { tStatic } from '../../i18n/tStatic';

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true };
  }

  componentDidCatch(error, errorInfo) {
    logger.error('ErrorBoundary caught an error:', error, errorInfo);
    this.setState({
      error: error,
      errorInfo: errorInfo
    });
    reportClientError({
      message: error?.message || error?.toString(),
      stack: error?.stack,
      componentStack: errorInfo?.componentStack,
      source: 'error-boundary',
    });
  }

  handleReload = () => {
    window.location.reload();
  };

  handleGoHome = () => {
    window.location.href = `${process.env.PUBLIC_URL || '/onboarding/ai'}/`;
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-brand-primary flex items-center justify-center p-4">
          <div className="max-w-2xl w-full bg-white rounded-2xl shadow-2xl p-8">
            <div className="text-center">
              <div className="inline-flex items-center justify-center w-20 h-20 bg-red-100 rounded-full mb-6">
                <AlertTriangle className="h-10 w-10 text-red-600" />
              </div>
              
              <h1 className="text-3xl font-bold text-gray-900 mb-4">
                {tStatic('ui.oops')}
              </h1>
              
              <p className="text-gray-600 mb-8">
                {tStatic('ui.sorryUnexpected')}
              </p>

              {process.env.NODE_ENV === 'development' && this.state.error && (
                <div className="mb-8 p-4 bg-gray-100 rounded-lg text-start">
                  <p className="text-sm font-mono text-red-600 mb-2">
                    <strong>{tStatic('ui.errorLabel')}</strong> {this.state.error.toString()}
                  </p>
                  <details className="text-xs font-mono text-gray-700">
                    <summary className="cursor-pointer hover:text-gray-900">
                      {tStatic('ui.stackTrace')}
                    </summary>
                    <pre className="mt-2 overflow-auto">
                      {this.state.errorInfo?.componentStack}
                    </pre>
                  </details>
                </div>
              )}

              <div className="flex gap-4 justify-center">
                <button
                  onClick={this.handleReload}
                  className="flex items-center gap-2 px-6 py-3 bg-brand-primary text-brand-primary text-white rounded-lg hover:opacity-90 transition-opacity"
                >
                  <RefreshCw className="h-5 w-5" />
                  {tStatic('ui.reloadPage')}
                </button>
                
                <button
                  onClick={this.handleGoHome}
                  className="flex items-center gap-2 px-6 py-3 border-2 border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors"
                >
                  <Home className="h-5 w-5" />
                  {tStatic('ui.goHome')}
                </button>
              </div>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;