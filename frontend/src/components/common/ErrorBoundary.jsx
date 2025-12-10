// frontend/src/components/common/ErrorBoundary.jsx

import React from 'react';
import { AlertTriangle, RefreshCw, Home } from 'lucide-react';

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true };
  }

  componentDidCatch(error, errorInfo) {
    console.error('ErrorBoundary caught an error:', error, errorInfo);
    this.setState({
      error: error,
      errorInfo: errorInfo
    });
  }

  handleReload = () => {
    window.location.reload();
  };

  handleGoHome = () => {
    window.location.href = '/';
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-gradient-to-br from-red-50 to-orange-50 flex items-center justify-center p-4">
          <div className="max-w-2xl w-full bg-white rounded-2xl shadow-2xl p-8">
            <div className="text-center">
              <div className="inline-flex items-center justify-center w-20 h-20 bg-red-100 rounded-full mb-6">
                <AlertTriangle className="h-10 w-10 text-red-600" />
              </div>
              
              <h1 className="text-3xl font-bold text-gray-900 mb-4">
                Oops! Something went wrong
              </h1>
              
              <p className="text-gray-600 mb-8">
                We're sorry, but something unexpected happened. Please try refreshing the page or go back to the home page.
              </p>

              {process.env.NODE_ENV === 'development' && this.state.error && (
                <div className="mb-8 p-4 bg-gray-100 rounded-lg text-left">
                  <p className="text-sm font-mono text-red-600 mb-2">
                    <strong>Error:</strong> {this.state.error.toString()}
                  </p>
                  <details className="text-xs font-mono text-gray-700">
                    <summary className="cursor-pointer hover:text-gray-900">
                      Stack trace
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
                  className="flex items-center gap-2 px-6 py-3 bg-gradient-to-r from-primary to-primary-dark text-white rounded-lg hover:opacity-90 transition-opacity"
                >
                  <RefreshCw className="h-5 w-5" />
                  Reload Page
                </button>
                
                <button
                  onClick={this.handleGoHome}
                  className="flex items-center gap-2 px-6 py-3 border-2 border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors"
                >
                  <Home className="h-5 w-5" />
                  Go Home
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