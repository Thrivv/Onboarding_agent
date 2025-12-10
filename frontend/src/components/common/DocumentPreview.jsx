// frontend/src/components/common/DocumentPreview.jsx
import React, { useState, useEffect } from 'react';
import { X, Download, ZoomIn, ZoomOut, RotateCw } from 'lucide-react';

const DocumentPreview = ({ isOpen, onClose, document }) => {
  const [zoom, setZoom] = useState(100);
  const [rotation, setRotation] = useState(0);

  useEffect(() => {
    const body = document.body;
    const originalOverflow = body.style.overflow;
    
    if (isOpen) {
      body.style.overflow = 'hidden';
    } else {
      body.style.overflow = 'unset';
    }
    
    return () => {
      body.style.overflow = originalOverflow;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  if (!isOpen || !document) return null;

  const handleDownload = () => {
    if (document.file_bytes) {
      const blob = new Blob([new Uint8Array(atob(document.file_bytes).split('').map(c => c.charCodeAt(0)))], 
        { type: document.file_type || 'application/octet-stream' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = document.filename || 'document';
      a.click();
      URL.revokeObjectURL(url);
    }
  };

  const renderPreview = () => {
    const fileType = document.file_type || document.filename?.split('.').pop()?.toLowerCase();

    if (fileType?.includes('pdf') || fileType === 'pdf') {
      return (
        <div className="flex items-center justify-center h-full bg-gray-100">
          <div className="text-center p-8">
            <div className="text-6xl mb-4">📄</div>
            <p className="text-gray-700 font-medium mb-4">PDF Document</p>
            <p className="text-gray-500 text-sm mb-4">{document.filename}</p>
            <button
              onClick={handleDownload}
              className="px-6 py-2 bg-gradient-to-r from-indigo-600 to-purple-600 text-white rounded-lg hover:opacity-90 transition-opacity flex items-center gap-2 mx-auto"
            >
              <Download className="h-4 w-4" />
              Download PDF
            </button>
          </div>
        </div>
      );
    }

    if (fileType?.includes('image') || ['jpg', 'jpeg', 'png', 'webp'].includes(fileType)) {
      const imageSrc = document.file_bytes 
        ? `data:${document.file_type || 'image/jpeg'};base64,${document.file_bytes}`
        : document.file_url;

      return (
        <div className="flex items-center justify-center h-full overflow-auto bg-gray-900 p-4">
          <img
            src={imageSrc}
            alt={document.filename}
            style={{
              transform: `scale(${zoom / 100}) rotate(${rotation}deg)`,
              transition: 'transform 0.3s ease',
              maxWidth: '100%',
              maxHeight: '100%',
              objectFit: 'contain',
            }}
            className="shadow-2xl"
          />
        </div>
      );
    }

    return (
      <div className="flex items-center justify-center h-full bg-gray-100">
        <div className="text-center p-8">
          <div className="text-6xl mb-4">📎</div>
          <p className="text-gray-700 font-medium mb-2">Document Preview Not Available</p>
          <p className="text-gray-500 text-sm">{document.filename}</p>
        </div>
      </div>
    );
  };

  const isImage = document.file_type?.includes('image') || 
    ['jpg', 'jpeg', 'png', 'webp'].includes(document.filename?.split('.').pop()?.toLowerCase());

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-75 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-6xl h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b bg-gradient-to-r from-indigo-600 to-purple-600 text-white rounded-t-2xl">
          <div className="flex-1">
            <h2 className="text-lg font-bold truncate">{document.filename || 'Document Preview'}</h2>
            <p className="text-sm text-indigo-100">{document.document_type?.toUpperCase()}</p>
          </div>
          
          {/* Controls */}
          {isImage && (
            <div className="flex items-center gap-2 mx-4">
              <button
                onClick={() => setZoom(Math.max(50, zoom - 25))}
                className="p-2 hover:bg-white/20 rounded-lg transition-colors"
                title="Zoom Out"
              >
                <ZoomOut className="h-5 w-5" />
              </button>
              <span className="text-sm font-medium w-16 text-center">{zoom}%</span>
              <button
                onClick={() => setZoom(Math.min(200, zoom + 25))}
                className="p-2 hover:bg-white/20 rounded-lg transition-colors"
                title="Zoom In"
              >
                <ZoomIn className="h-5 w-5" />
              </button>
              <button
                onClick={() => setRotation((rotation + 90) % 360)}
                className="p-2 hover:bg-white/20 rounded-lg transition-colors"
                title="Rotate"
              >
                <RotateCw className="h-5 w-5" />
              </button>
            </div>
          )}
          
          <button
            onClick={onClose}
            className="p-2 hover:bg-white/20 rounded-lg transition-colors"
            title="Close"
          >
            <X className="h-6 w-6" />
          </button>
        </div>

        {/* Preview Area */}
        <div className="flex-1 overflow-hidden">
          {renderPreview()}
        </div>

        {/* Footer with Extracted Data */}
        {document.extracted_data && Object.keys(document.extracted_data).length > 0 && (
          <div className="p-4 border-t bg-gray-50 max-h-48 overflow-y-auto">
            <h3 className="font-semibold text-gray-800 mb-2 flex items-center gap-2">
              <span className="text-lg">📋</span>
              Extracted Information
            </h3>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              {Object.entries(document.extracted_data).map(([key, value]) => (
                <div key={key} className="bg-white p-2 rounded border border-gray-200">
                  <div className="text-xs text-gray-500 font-medium">{key}</div>
                  <div className="text-sm text-gray-900 truncate" title={value}>
                    {value || 'N/A'}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default DocumentPreview;