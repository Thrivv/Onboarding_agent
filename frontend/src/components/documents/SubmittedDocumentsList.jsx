// frontend/src/components/documents/SubmittedDocumentsList.jsx

import React, { useState } from 'react';
import { ChevronDown, ChevronUp, Eye, Download, CheckCircle, XCircle } from 'lucide-react';
import ExtractedDataDisplay from './ExtractedDataDisplay';
import DocumentPreviewModal from './DocumentPreviewModal';
import api from '../../services/api';
import toast from 'react-hot-toast';

const SubmittedDocumentsList = ({ documents, email }) => {
  const [expandedDocs, setExpandedDocs] = useState({});
  const [showPreview, setShowPreview] = useState(null);

  const toggleExpand = (docId) => {
    setExpandedDocs(prev => ({
      ...prev,
      [docId]: !prev[docId]
    }));
  };

  const handleDownload = async (docType, memberName, filename) => {
    try {
      const response = await api.get(
        `/documentupload/download-document/${email}/${docType.toLowerCase()}`,
        {
          params: memberName ? { member_name: memberName } : {},
          responseType: 'blob'
        }
      );
      
      // Create download link
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', filename || `${docType}.pdf`);
      document.body.appendChild(link);
      link.click();
      link.remove();
      
      toast.success('Document downloaded successfully');
    } catch (error) {
      console.error('Download error:', error);
      toast.error('Failed to download document');
    }
  };

  return (
    <div className="bg-white rounded-xl shadow-lg p-6 mb-6">
      <h2 className="text-2xl font-bold text-gray-800 mb-4 flex items-center gap-2">
        📊 Submitted Documents
      </h2>

      <div className="space-y-4">
        {documents.map((doc, index) => {
          const docId = `${doc.document_type}-${index}`;
          const isExpanded = expandedDocs[docId];
          const displayName = doc.display_name || doc.document_type.toUpperCase();

          return (
            <div key={docId} className="border-2 border-gray-200 rounded-lg overflow-hidden hover:border-indigo-300 transition-colors">
              {/* Document Header */}
              <div className="bg-gradient-to-r from-gray-50 to-gray-100 p-4">
                <div className="flex items-center justify-between">
                  <div className="flex-1">
                    <div className="flex items-center gap-3">
                      <h3 className="text-lg font-bold text-gray-800">
                        📄 {displayName}
                      </h3>
                      {doc.is_valid ? (
                        <span className="flex items-center gap-1 px-3 py-1 bg-green-100 text-green-800 rounded-full text-sm font-medium">
                          <CheckCircle className="h-4 w-4" />
                          Valid
                        </span>
                      ) : (
                        <span className="flex items-center gap-1 px-3 py-1 bg-red-100 text-red-800 rounded-full text-sm font-medium">
                          <XCircle className="h-4 w-4" />
                          Invalid
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-gray-600 mt-1">📎 {doc.filename}</p>
                    {doc.member_name && (
                      <p className="text-sm text-gray-600">👤 Member: {doc.member_name}</p>
                    )}
                  </div>
                  
                  <button
                    onClick={() => toggleExpand(docId)}
                    className="p-2 hover:bg-gray-200 rounded-lg transition-colors"
                  >
                    {isExpanded ? (
                      <ChevronUp className="h-5 w-5 text-gray-600" />
                    ) : (
                      <ChevronDown className="h-5 w-5 text-gray-600" />
                    )}
                  </button>
                </div>
              </div>

              {/* Expanded Content */}
              {isExpanded && (
                <div className="p-4 bg-white">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    {/* Left: Extracted Data */}
                    <div>
                      <h4 className="text-sm font-bold text-gray-700 mb-3 flex items-center gap-2">
                        📋 Extracted Information
                      </h4>
                      <ExtractedDataDisplay
                        documentType={doc.document_type}
                        displayName={displayName}
                        extractedData={doc.extracted_data}
                      />
                    </div>

                    {/* Right: Actions */}
                    <div>
                      <h4 className="text-sm font-bold text-gray-700 mb-3 flex items-center gap-2">
                        🔧 Actions
                      </h4>
                      <div className="space-y-3">
                        <button
                          onClick={() => setShowPreview({ 
                            docType: doc.document_type, 
                            memberName: doc.member_name 
                          })}
                          className="w-full px-4 py-3 bg-indigo-100 hover:bg-indigo-200 text-indigo-800 rounded-lg font-medium transition-colors flex items-center justify-center gap-2"
                        >
                          <Eye className="h-5 w-5" />
                          View Document
                        </button>
                        
                        <button
                          onClick={() => handleDownload(doc.document_type, doc.member_name, doc.filename)}
                          className="w-full px-4 py-3 bg-green-100 hover:bg-green-200 text-green-800 rounded-lg font-medium transition-colors flex items-center justify-center gap-2"
                        >
                          <Download className="h-5 w-5" />
                          Download Document
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Preview Modal */}
      {showPreview && (
        <DocumentPreviewModal
          email={email}
          docType={showPreview.docType}
          memberName={showPreview.memberName}
          onClose={() => setShowPreview(null)}
        />
      )}
    </div>
  );
};

export default SubmittedDocumentsList;