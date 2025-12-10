// frontend/src/components/documents/DocumentPreviewModal.jsx - FIXED DEPENDENCIES

import React, { useState, useEffect, useCallback } from 'react';
import { X, Loader } from 'lucide-react';
import api from '../../services/api';
import toast from 'react-hot-toast';

const DocumentPreviewModal = ({ email, docType, memberName, onClose }) => {
  const [previewData, setPreviewData] = useState(null);
  const [isLoading, setIsLoading] = useState(true);

  // ✅ FIX: Wrap loadPreview in useCallback
  const loadPreview = useCallback(async () => {
    try {
      setIsLoading(true);
      const response = await api.get(
        `/documentupload/get-document-preview/${email}/${docType.toLowerCase()}`,
        { params: memberName ? { member_name: memberName } : {} }
      );
      setPreviewData(response.data);
    } catch (error) {
      console.error('Preview error:', error);
      toast.error('Failed to load document preview');
    } finally {
      setIsLoading(false);
    }
  }, [email, docType, memberName]);

  // ✅ FIX: Add loadPreview to dependency array
  useEffect(() => {
    loadPreview();
  }, [loadPreview]);

  const renderPreview = () => {
    if (!previewData) return null;

    // PDF Preview
    if (previewData.mime_type === 'application/pdf') {
      const pdfMeta = previewData.pdf_metadata || {};
      return (
        <div className="text-center p-12">
          <div className="text-8xl mb-6">📄</div>
          <h3 className="text-2xl font-bold text-gray-800 mb-2">
            {previewData.filename}
          </h3>
          <p className="text-gray-600 mb-4">
            📊 {pdfMeta.num_pages || 'N/A'} pages • PDF Document
          </p>
          
          <button
            onClick={() => {
              const link = document.createElement('a');
              link.href = `/documentupload/download-document/${email}/${docType.toLowerCase()}${memberName ? `?member_name=${memberName}` : ''}`;
              link.download = previewData.filename;
              document.body.appendChild(link);
              link.click();
              link.remove();
            }}
            className="inline-block px-6 py-3 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors font-medium cursor-pointer"
          >
            📥 Download PDF
          </button>
        </div>
      );
    }

    // Image Preview
    if (previewData.mime_type?.startsWith('image/')) {
      return (
        <div className="p-4">
          <img
            src={`data:${previewData.mime_type};base64,${previewData.file_bytes}`}
            alt={previewData.filename}
            className="max-w-full h-auto mx-auto rounded-lg shadow-lg"
          />
          <p className="text-center text-gray-600 mt-4 font-medium">
            {previewData.filename}
          </p>
        </div>
      );
    }

    // Email upload
    if (previewData.is_email_upload) {
      return (
        <div className="text-center p-12">
          <div className="text-8xl mb-6">📧</div>
          <h3 className="text-xl font-bold text-gray-800 mb-2">
            Email Upload
          </h3>
          <p className="text-gray-600">
            Document uploaded via email - preview not available
          </p>
        </div>
      );
    }

    return (
      <div className="text-center p-12">
        <p className="text-gray-600">Preview not available</p>
      </div>
    );
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl max-w-4xl w-full max-h-[90vh] overflow-hidden flex flex-col">
        {/* Header */}
        <div className="bg-gradient-to-r from-indigo-600 to-purple-600 text-white p-4 flex items-center justify-between">
          <h2 className="text-xl font-bold">📄 Document Preview</h2>
          <button
            onClick={onClose}
            className="p-2 hover:bg-white hover:bg-opacity-20 rounded-lg transition-colors"
          >
            <X className="h-6 w-6" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto">
          {isLoading ? (
            <div className="flex items-center justify-center h-64">
              <Loader className="h-12 w-12 text-indigo-600 animate-spin" />
            </div>
          ) : (
            renderPreview()
          )}
        </div>
      </div>
    </div>
  );
};

export default DocumentPreviewModal;