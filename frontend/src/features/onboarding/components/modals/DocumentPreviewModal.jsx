import React from 'react';
import { useLanguage } from '../../../../context/LanguageContext';
import { FileText, X } from 'lucide-react';

const DocumentPreviewModal = ({ isOpen, onClose, document }) => {
  const { t } = useLanguage();
  if (!isOpen || !document) return null;

  const isPDF = document.type === 'application/pdf';
  const isImage = document.type?.startsWith('image/');

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-brand-primary bg-opacity-50 p-4"
      onClick={onClose}>
      <div className="bg-white rounded-lg shadow-2xl max-w-4xl w-full max-h-[90vh] overflow-hidden"
        onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b bg-brand-primary">
          <h3 className="text-lg font-bold text-white flex items-center gap-2">
            <FileText className="h-5 w-5" />
            {document.name}
          </h3>
          <button
            onClick={onClose}
            className="text-white hover:bg-white hover:bg-opacity-20 rounded-full p-2 transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Preview Content */}
        <div className="p-4 overflow-auto max-h-[calc(90vh-80px)]">
          {isPDF && document.previewUrl ? (
            <iframe
              src={document.previewUrl}
              className="w-full h-[70vh] border rounded"
              title={t('ui.pdfPreview')}
            />
          ) : isImage && document.previewUrl ? (
            <img
              src={document.previewUrl}
              alt={document.name}
              className="max-w-full h-auto mx-auto rounded shadow-lg"
            />
          ) : document.base64 ? (
            isImage ? (
              <img
                src={`data:${document.type};base64,${document.base64}`}
                alt={document.name}
                className="max-w-full h-auto mx-auto rounded shadow-lg"
              />
            ) : (
              <iframe
                src={`data:application/pdf;base64,${document.base64}`}
                className="w-full h-[70vh] border rounded"
                title={t('ui.pdfPreview')}
              />
            )
          ) : (
            <div className="flex items-center justify-center h-64 text-gray-500">
              <p>{t('ui.previewNotAvailable')}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

// ============================================================================
// EID (EMIRATES ID) DISPLAY
// ============================================================================

export { DocumentPreviewModal };
