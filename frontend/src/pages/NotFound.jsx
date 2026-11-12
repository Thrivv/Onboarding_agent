// frontend/src/pages/NotFound.jsx

import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Home, ArrowLeft, Search } from 'lucide-react';
import { useLanguage } from '../context/LanguageContext';

const NotFound = () => {
  const navigate = useNavigate();
  const { t } = useLanguage();

  return (
    <div className="gx-main-layout">
      <div className="max-w-2xl w-full text-center">
        <div className="bg-white rounded-2xl shadow-2xl p-12">
          {/* 404 Animation */}
          <div className="mb-8">
            <h1 className="text-9xl font-bold gradient-text mb-4 animate-pulse">
              404
            </h1>
            <div className="flex items-center justify-center gap-2 text-gray-600">
              <Search className="h-6 w-6" />
              <p className="text-2xl font-semibold">{t('notFound.pageNotFound')}</p>
            </div>
          </div>

          {/* Message */}
          <p className="text-gray-600 text-lg mb-8">
            {t('notFound.message')}
          </p>

          {/* Actions */}
          <div className="flex flex-col sm:flex-row gap-4 justify-center">
            <button
              onClick={() => navigate(-1)}
              className="flex items-center justify-center gap-2 px-6 py-3 border-2 border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors"
            >
              <ArrowLeft className="h-5 w-5" />
              {t('notFound.goBack')}
            </button>
            
            <button
              onClick={() => navigate('/')}
              className="flex items-center justify-center gap-2 px-6 py-3 gradient-btn text-white rounded-lg hover:opacity-90 transition-opacity"
            >
              <Home className="h-5 w-5" />
              {t('notFound.goHome')}
            </button>
          </div>

          {/* Help Text */}
          <div className="mt-12 p-6 bg-blue-50 rounded-lg">
            <p className="text-sm text-gray-700 mb-2">
              <strong>💡 {t('notFound.commonPages')}</strong>
            </p>
            <div className="flex flex-wrap gap-2 justify-center">
              <button
                onClick={() => navigate('/login')}
                className="text-sm text-brand-primary hover:underline"
              >
                {t('notFound.login')}
              </button>
              <span className="text-gray-400">•</span>
              <button
                onClick={() => navigate('/signup')}
                className="text-sm text-brand-primary hover:underline"
              >
                {t('notFound.signup')}
              </button>
              <span className="text-gray-400">•</span>
              <button
                onClick={() => navigate('/ai-assistant')}
                className="text-sm text-brand-primary hover:underline"
              >
                {t('notFound.aiAssistant')}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default NotFound;