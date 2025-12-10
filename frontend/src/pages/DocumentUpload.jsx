// frontend/src/pages/DocumentUpload.jsx - WITH DOCUMENT PREVIEW AND EXTRACTED DATA

import React, { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../context/AuthContext';
import Sidebar from '../components/layout/Sidebar';
import api from '../services/api';
import toast from 'react-hot-toast';
import { 
  RefreshCw, Loader, AlertCircle, CheckCircle, XCircle, ExternalLink,
  Eye, X, Download, ZoomIn, ZoomOut, RotateCw, FileText, ImageIcon
} from 'lucide-react';

// Import components
import AccountInfoCards from '../components/documents/AccountInfoCards';
import RequirementsNote from '../components/documents/RequirementsNote';
import MemberProgress from '../components/documents/MemberProgress';
import StageOneUpload from '../components/documents/StageOneUpload';
import StageTwoUpload from '../components/documents/StageTwoUpload';
import BulkUpload from '../components/documents/BulkUpload';
import FinalConfirmation from '../components/documents/FinalConfirmation';
import ExtractedDataDisplay from '../components/documents/ExtractedDataDisplay';

// Document Preview Modal Component
const DocumentPreviewModal = ({ isOpen, onClose, document }) => {
  const [zoom, setZoom] = useState(100);
  const [rotation, setRotation] = useState(0);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (isOpen) {
      setZoom(100);
      setRotation(0);
      setIsLoading(true);
    }
  }, [isOpen, document]);

  if (!isOpen || !document) return null;

  const isPDF = document.file_type === 'application/pdf' || 
                document.filename?.toLowerCase().endsWith('.pdf');
  const isImage = document.file_type?.startsWith('image/') || 
                  /\.(jpg|jpeg|png|gif|bmp|webp)$/i.test(document.filename);

  const handleDownload = () => {
    if (!document) return;
    
    // If preview_url is a data URL (base64), download directly
    if (document.preview_url?.startsWith('data:')) {
      const link = window.document.createElement('a');
      link.href = document.preview_url;
      link.download = document.filename || 'document';
      window.document.body.appendChild(link);
      link.click();
      window.document.body.removeChild(link);
      return;
    }
    
    // Otherwise, use the API download endpoint
    const docType = document.document_type;
    const params = document.member_name ? `?member_name=${encodeURIComponent(document.member_name)}` : '';
    const downloadUrl = `/documentupload/download-document/${document.email}/${encodeURIComponent(docType)}${params}`;
    
    // Create temporary link and trigger download
    const link = window.document.createElement('a');
    link.href = api.defaults.baseURL + downloadUrl;
    link.download = document.filename || 'document';
    window.document.body.appendChild(link);
    link.click();
    window.document.body.removeChild(link);
  };

  const handleZoomIn = () => setZoom(prev => Math.min(prev + 25, 200));
  const handleZoomOut = () => setZoom(prev => Math.max(prev - 25, 50));
  const handleRotate = () => setRotation(prev => (prev + 90) % 360);

  const renderContent = () => {
    const documentUrl = document.preview_url || document.file_url || document.url;

    // ✅ PDF: Use same method as AIAssistant - works perfectly!
    if (isPDF) {
      return (
        <div className="flex-1 overflow-auto bg-gray-100 p-4 relative">
          <iframe
            src={documentUrl}
            className="w-full h-full border-0 rounded-lg shadow-lg bg-white"
            style={{
              minHeight: '70vh'
            }}
            onLoad={() => {
              console.log('[PREVIEW] ✅ PDF loaded');
              setIsLoading(false);
            }}
            onError={(e) => {
              console.error('[PREVIEW] ❌ PDF error:', e);
              setIsLoading(false);
            }}
            title="PDF Preview"
          />
          {isLoading && (
            <div className="absolute inset-0 flex items-center justify-center bg-gray-900 bg-opacity-50 rounded-lg">
              <div className="text-center">
                <Loader className="h-8 w-8 text-white animate-spin mx-auto mb-4" />
                <p className="text-white text-sm">Loading PDF...</p>
              </div>
            </div>
          )}
        </div>
      );
    }

    // ✅ IMAGES: Display with zoom/rotate
    if (isImage) {
      return (
        <div className="flex-1 overflow-auto bg-gray-900 flex items-center justify-center p-4 relative">
          <img
            src={documentUrl}
            alt={document.filename || 'Document'}
            className="max-w-full max-h-full object-contain rounded-lg shadow-2xl"
            style={{
              transform: `scale(${zoom / 100}) rotate(${rotation}deg)`,
              transformOrigin: 'center center',
              transition: 'transform 0.3s ease'
            }}
            onLoad={() => setIsLoading(false)}
            onError={() => setIsLoading(false)}
          />
          {isLoading && (
            <div className="absolute inset-0 flex items-center justify-center">
              <Loader className="h-8 w-8 text-white animate-spin" />
            </div>
          )}
        </div>
      );
    }

    return (
      <div className="flex-1 flex items-center justify-center bg-gray-100">
        <div className="text-center p-8">
          <FileText className="h-16 w-16 text-gray-400 mx-auto mb-4" />
          <p className="text-gray-600 mb-4">Preview not available for this file type</p>
          <button
            onClick={handleDownload}
            className="px-6 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors flex items-center gap-2 mx-auto"
          >
            <Download className="h-4 w-4" />
            Download to View
          </button>
        </div>
      </div>
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black bg-opacity-75">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-6xl h-[90vh] flex flex-col">
        {/* Header */}
        <div className="bg-gradient-to-r from-indigo-600 to-purple-600 text-white p-4 rounded-t-xl flex items-center justify-between">
          <div className="flex items-center gap-3">
            {isPDF ? (
              <FileText className="h-6 w-6" />
            ) : isImage ? (
              <ImageIcon className="h-6 w-6" />
            ) : (
              <FileText className="h-6 w-6" />
            )}
            <div>
              <h2 className="text-xl font-bold">Document Preview</h2>
              <p className="text-sm text-indigo-100">{document.filename || 'Untitled'}</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-white hover:bg-opacity-20 rounded-lg transition-colors"
          >
            <X className="h-6 w-6" />
          </button>
        </div>

        {/* Toolbar */}
        <div className="bg-gray-100 border-b border-gray-200 px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <button
              onClick={handleZoomOut}
              disabled={zoom <= 50}
              className="p-2 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              title="Zoom Out"
            >
              <ZoomOut className="h-4 w-4" />
            </button>
            <span className="px-3 py-1 bg-white border border-gray-300 rounded-lg text-sm font-medium min-w-[80px] text-center">
              {zoom}%
            </span>
            <button
              onClick={handleZoomIn}
              disabled={zoom >= 200}
              className="p-2 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              title="Zoom In"
            >
              <ZoomIn className="h-4 w-4" />
            </button>
            <div className="w-px h-6 bg-gray-300 mx-2" />
            <button
              onClick={handleRotate}
              className="p-2 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
              title="Rotate"
            >
              <RotateCw className="h-4 w-4" />
            </button>
          </div>
          <button
            onClick={handleDownload}
            className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors flex items-center gap-2"
          >
            <Download className="h-4 w-4" />
            Download
          </button>
        </div>

        {/* Content Area */}
        {renderContent()}

        {/* Footer Info */}
        <div className="bg-gray-50 border-t border-gray-200 px-4 py-3 rounded-b-xl">
          <div className="flex items-center justify-between text-sm text-gray-600">
            <div className="flex items-center gap-4">
              {document.document_type && (
                <span>
                  <strong>Type:</strong> {document.document_type}
                </span>
              )}
              {document.file_size && (
                <span>
                  <strong>Size:</strong> {(document.file_size / 1024).toFixed(1)} KB
                </span>
              )}
            </div>
            {document.upload_date && (
              <span>
                <strong>Uploaded:</strong> {new Date(document.upload_date).toLocaleDateString()}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

// Enhanced Submitted Documents List with Preview and Extracted Data
const SubmittedDocumentsList = ({ documents, email }) => {
  const [previewDocument, setPreviewDocument] = useState(null);
  const [isPreviewOpen, setIsPreviewOpen] = useState(false);
  const [expandedDoc, setExpandedDoc] = useState(null);

  const handleViewDocument = async (doc) => {
    try {
      // Use backend endpoint to get document file
      // This handles the proper path: backend/documents/id/{email}/{doc_type}/file
      const docType = doc.document_type;
      const params = doc.member_name ? `?member_name=${encodeURIComponent(doc.member_name)}` : '';
      
      console.log('[PREVIEW] 🔍 Opening document preview');
      console.log('[PREVIEW] 📧 Email:', email);
      console.log('[PREVIEW] 📄 Doc Type:', docType);
      console.log('[PREVIEW] 👤 Member:', doc.member_name);
      console.log('[PREVIEW] 📁 Filename:', doc.filename);
      
      // Construct document URL using the backend endpoint
      const documentUrl = `${api.defaults.baseURL}/documentupload/get-document/${email}/${encodeURIComponent(docType)}${params}`;
      
      console.log('[PREVIEW] 🔗 Full URL:', documentUrl);
      
      setPreviewDocument({
        ...doc,
        preview_url: documentUrl,
        url: documentUrl,
        file_url: documentUrl,
        email: email  // Pass email to modal for download
      });
      setIsPreviewOpen(true);
    } catch (error) {
      console.error('[PREVIEW] ❌ Error preparing document preview:', error);
      toast.error('Failed to load document preview');
    }
  };

  const handleDownloadDocument = async (doc) => {
    try {
      const docType = doc.document_type;
      const params = doc.member_name ? `?member_name=${encodeURIComponent(doc.member_name)}` : '';
      
      // Download using backend endpoint
      const response = await api.get(
        `/documentupload/download-document/${email}/${encodeURIComponent(docType)}${params}`,
        { responseType: 'blob' }
      );
      
      // Create download link
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', doc.filename || `${docType}.pdf`);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
      
      toast.success('Document downloaded successfully!');
    } catch (error) {
      console.error('Error downloading document:', error);
      toast.error('Failed to download document');
    }
  };

  const toggleExpanded = (index) => {
    setExpandedDoc(expandedDoc === index ? null : index);
  };

  return (
    <>
      <div className="bg-white rounded-xl shadow-lg p-6 mb-6">
        <h3 className="text-xl font-bold text-gray-800 mb-4 flex items-center gap-2">
          <span className="text-2xl">📁</span>
          Submitted Documents
        </h3>
        <div className="space-y-3">
          {documents.map((doc, index) => (
            <div
              key={index}
              className="bg-gradient-to-r from-green-50 to-emerald-50 border border-green-200 rounded-lg overflow-hidden hover:shadow-md transition-shadow"
            >
              {/* Document Header */}
              <div className="p-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3 flex-1">
                    <div className="bg-green-500 p-2 rounded-full">
                      <FileText className="h-5 w-5 text-white" />
                    </div>
                    <div className="flex-1">
                      <div className="font-semibold text-gray-800">{doc.display_name || doc.document_type}</div>
                      <div className="text-sm text-gray-600">{doc.filename}</div>
                      {doc.member_name && (
                        <div className="text-xs text-gray-500 mt-1">
                          👤 Member: {doc.member_name}
                        </div>
                      )}
                      {doc.upload_date && (
                        <div className="text-xs text-gray-500 mt-1">
                          📅 Uploaded: {new Date(doc.upload_date).toLocaleDateString()}
                        </div>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => toggleExpanded(index)}
                      className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors flex items-center gap-2"
                    >
                      <FileText className="h-4 w-4" />
                      {expandedDoc === index ? 'Hide' : 'View'} Data
                    </button>
                    <button
                      onClick={() => handleViewDocument(doc)}
                      className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors flex items-center gap-2"
                    >
                      <Eye className="h-4 w-4" />
                      Preview
                    </button>
                    <button
                      onClick={() => handleDownloadDocument(doc)}
                      className="px-4 py-2 bg-gray-600 text-white rounded-lg hover:bg-gray-700 transition-colors flex items-center gap-2"
                    >
                      <Download className="h-4 w-4" />
                      Download
                    </button>
                  </div>
                </div>
              </div>

              {/* Extracted Data Display (Collapsible) */}
              {expandedDoc === index && doc.extracted_data && (
                <div className="border-t border-green-300 bg-white p-6">
                  <div className="flex items-center gap-2 mb-4">
                    <div className="text-2xl">📋</div>
                    <h4 className="text-lg font-bold text-gray-800">
                      Extracted Information
                    </h4>
                  </div>
                  <ExtractedDataDisplay 
                    documentType={doc.document_type}
                    displayName={doc.display_name || doc.document_type}
                    extractedData={doc.extracted_data}
                  />
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      <DocumentPreviewModal
        isOpen={isPreviewOpen}
        onClose={() => setIsPreviewOpen(false)}
        document={previewDocument}
      />
    </>
  );
};

// Main DocumentUpload Component
const DocumentUpload = () => {
  const { user } = useAuth();
  const [documentRequirements, setDocumentRequirements] = useState(null);
  const [documentStatus, setDocumentStatus] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [validationComplete, setValidationComplete] = useState(false);
  const [confirmationSent, setConfirmationSent] = useState(false);
  
  // State for showing verification messages and extracted content
  const [recentVerification, setRecentVerification] = useState(null);
  const [showVerificationBanner, setShowVerificationBanner] = useState(false);

  // Load document requirements and status
  const loadDocumentData = useCallback(async () => {
    if (!user?.email) return;
    
    try {
      setIsLoading(true);
      
      // Load requirements
      const reqResponse = await api.post('/documentupload/get-document-requirements', {
        email: user.email
      });
      setDocumentRequirements(reqResponse.data);
      
      // Load status
      const statusResponse = await api.get(`/documentupload/document-status/${user.email}`);
      setDocumentStatus(statusResponse.data);
      
      // Check if validation already complete
      try {
        const confirmationResponse = await api.get(
          `/documentupload/check-confirmation-status/${user.email}`
        );
        
        if (confirmationResponse.data && confirmationResponse.data.confirmation_sent) {
          setConfirmationSent(true);
          setValidationComplete(true);
        }
      } catch (confirmError) {
        console.log('Confirmation status check failed (non-critical):', confirmError);
      }
      
    } catch (error) {
      console.error('[DOCUMENT UPLOAD] Load error:', error);
      toast.error('Failed to load document information');
    } finally {
      setIsLoading(false);
    }
  }, [user]);

  useEffect(() => {
    loadDocumentData();
  }, [loadDocumentData]);

  const handleRefresh = () => {
    toast.success('Refreshing...');
    loadDocumentData();
  };

  // Handle successful document upload with verification display
  const handleDocumentSuccess = (uploadResponse) => {
    // Show verification banner with extracted content
    if (uploadResponse && uploadResponse.is_valid) {
      setRecentVerification({
        documentType: uploadResponse.document_type,
        extractedData: uploadResponse.extracted_data,
        filename: uploadResponse.filename || 'Document',
        timestamp: new Date().toISOString()
      });
      setShowVerificationBanner(true);
      
      // Auto-hide banner after 30 seconds
      setTimeout(() => {
        setShowVerificationBanner(false);
      }, 30000);
    }
    
    // Reload document data
    loadDocumentData();
  };

  // Dismiss verification banner
  const dismissVerificationBanner = () => {
    setShowVerificationBanner(false);
  };

  // Loading state
  if (isLoading) {
    return (
      <div className="flex h-screen bg-gradient-to-br from-blue-50 to-indigo-100">
        <Sidebar />
        <div className="flex-1 ml-64 flex items-center justify-center">
          <div className="text-center">
            <Loader className="h-12 w-12 text-indigo-600 animate-spin mx-auto mb-4" />
            <p className="text-gray-600 font-medium">Loading document information...</p>
          </div>
        </div>
      </div>
    );
  }

  // Error state
  if (!documentRequirements || !documentStatus) {
    return (
      <div className="flex h-screen bg-gradient-to-br from-blue-50 to-indigo-100">
        <Sidebar />
        <div className="flex-1 ml-64 flex items-center justify-center">
          <div className="text-center bg-white p-8 rounded-xl shadow-lg">
            <AlertCircle className="h-12 w-12 text-red-600 mx-auto mb-4" />
            <h2 className="text-xl font-bold text-gray-800 mb-2">Failed to Load</h2>
            <p className="text-gray-600 mb-4">Unable to load your document information</p>
            <button
              onClick={handleRefresh}
              className="px-6 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors"
            >
              Try Again
            </button>
          </div>
        </div>
      </div>
    );
  }

  const accountType = documentRequirements.account_type;
  const ownershipType = documentRequirements.ownership_type;
  const stage = documentStatus.stage;
  const isComplete = documentStatus.is_complete;
  const submittedDocs = documentStatus.documents || [];
  const remainingDocs = documentStatus.remaining_documents || [];
  const membersInfo = documentStatus.members_info;

  return (
    <div className="flex h-screen bg-gradient-to-br from-blue-50 to-indigo-100 overflow-hidden">
      <Sidebar />
      
      <div className="flex-1 ml-64 overflow-y-auto">
        <div className="p-6 max-w-7xl mx-auto">
          {/* Header */}
          <div className="bg-white rounded-xl shadow-lg p-6 mb-6">
            <div className="flex items-center justify-between">
              <div>
                <h1 className="text-3xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-indigo-600 to-purple-600">
                  📄 Document Upload Center
                </h1>
                <p className="text-gray-600 mt-1">
                  Upload your documents to complete the onboarding process
                </p>
              </div>
              <button
                onClick={handleRefresh}
                className="px-4 py-2 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors flex items-center gap-2"
              >
                <RefreshCw className="h-4 w-4" />
                Refresh
              </button>
            </div>
          </div>

          {/* Final Verification Complete Banner */}
          {(stage === 'complete' || validationComplete || confirmationSent) && isComplete && (
            <div className="mb-6 animate-slideDown">
              <div className="bg-gradient-to-r from-green-50 to-emerald-50 border-2 border-green-400 rounded-xl shadow-xl p-8">
                <div className="text-center mb-6">
                  <div className="text-6xl mb-4">🎉</div>
                  <h2 className="text-3xl font-bold text-gray-800 mb-2">
                    Verification Complete!
                  </h2>
                  <p className="text-lg text-gray-600">
                    All your documents have been verified successfully.
                  </p>
                </div>

                <div className="bg-white border-2 border-green-300 rounded-lg p-6 mb-4">
                  <div className="space-y-3">
                    <div className="flex items-center gap-3 text-green-800">
                      <CheckCircle className="h-5 w-5 text-green-600" />
                      <span className="font-medium">Confirmation email sent to {user?.email}</span>
                    </div>
                    <div className="flex items-center gap-3 text-green-800">
                      <CheckCircle className="h-5 w-5 text-green-600" />
                      <span className="font-medium">Account activation within 3-4 business days</span>
                    </div>
                    <div className="flex items-center gap-3 text-green-800">
                      <CheckCircle className="h-5 w-5 text-green-600" />
                      <span className="font-medium">You will receive account details via email</span>
                    </div>
                  </div>
                </div>

                <div className="bg-blue-50 border border-blue-300 rounded-lg p-4 mb-6">
                  <p className="text-sm text-blue-800">
                    <strong>💡 What's Next?</strong><br />
                    Our team will review your documents and activate your account within 3-4 business days.
                    You'll receive an email with your account details once the activation is complete.
                  </p>
                </div>

                <div className="text-center">
                  <button
                    onClick={() => window.location.href = '/dashboard'}
                    className="inline-flex items-center gap-2 px-8 py-3 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors font-semibold shadow-lg"
                  >
                    Go to Dashboard
                    <ExternalLink className="h-5 w-5" />
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Document Upload Verification Banner */}
          {showVerificationBanner && recentVerification && (
            <div className="mb-6 animate-slideDown">
              <div className="bg-gradient-to-r from-green-50 to-emerald-50 border-l-4 border-green-500 rounded-lg shadow-lg p-6 mb-4">
                <div className="flex items-start justify-between">
                  <div className="flex items-start gap-4 flex-1">
                    <div className="bg-green-500 p-3 rounded-full">
                      <CheckCircle className="h-6 w-6 text-white" />
                    </div>
                    <div className="flex-1">
                      <h3 className="text-lg font-bold text-green-900 mb-1">
                        ✅ Document Verified Successfully!
                      </h3>
                      <p className="text-sm text-green-800 mb-2">
                        Your <span className="font-semibold">{recentVerification.documentType}</span> has been processed and validated.
                      </p>
                      <div className="flex items-center gap-2 text-xs text-green-700">
                        <span className="bg-green-100 px-2 py-1 rounded">
                          {new Date(recentVerification.timestamp).toLocaleTimeString()}
                        </span>
                        <span>•</span>
                        <span>{recentVerification.filename}</span>
                      </div>
                    </div>
                  </div>
                  <button
                    onClick={dismissVerificationBanner}
                    className="text-green-600 hover:text-green-800 transition-colors p-1"
                    title="Dismiss"
                  >
                    <XCircle className="h-5 w-5" />
                  </button>
                </div>
              </div>

              {/* Extracted Content Display */}
              {recentVerification.extractedData && (
                <div className="bg-white rounded-lg shadow-lg p-6 border-2 border-green-200">
                  <div className="flex items-center gap-2 mb-4">
                    <div className="text-2xl">📋</div>
                    <h4 className="text-lg font-bold text-gray-800">
                      Extracted Information
                    </h4>
                  </div>
                  <ExtractedDataDisplay 
                    documentType={recentVerification.documentType}
                    displayName={recentVerification.documentType}
                    extractedData={recentVerification.extractedData}
                  />
                </div>
              )}
            </div>
          )}

          {/* Account Info Cards */}
          <AccountInfoCards
            accountType={accountType}
            ownershipType={ownershipType}
            stage={stage}
          />

          {/* Requirements Note */}
          <RequirementsNote
            accountType={accountType}
            ownershipType={ownershipType}
            stage={stage}
          />

          {/* Status Metrics */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
            <div className="bg-white rounded-lg shadow p-6 text-center">
              <div className="text-4xl mb-2">📄</div>
              <div className="text-3xl font-bold text-blue-600">
                {submittedDocs.length}
              </div>
              <div className="text-sm text-gray-600 mt-1">Submitted</div>
            </div>

            <div className="bg-white rounded-lg shadow p-6 text-center">
              <div className="text-4xl mb-2">⏳</div>
              <div className="text-3xl font-bold text-yellow-600">
                {remainingDocs.length}
              </div>
              <div className="text-sm text-gray-600 mt-1">Remaining</div>
            </div>

            <div className="bg-white rounded-lg shadow p-6 text-center">
              <div className="text-4xl mb-2">
                {validationComplete || confirmationSent ? '✅' : isComplete ? '🎯' : '⏱️'}
              </div>
              <div className={`text-xl font-bold ${
                validationComplete || confirmationSent ? 'text-green-600' : 
                isComplete ? 'text-blue-600' : 
                'text-gray-600'
              }`}>
                {validationComplete || confirmationSent ? 'Verified' : 
                 isComplete ? 'Ready to Verify' : 
                 'In Progress'}
              </div>
              <div className="text-sm text-gray-600 mt-1">Status</div>
            </div>
          </div>

          {/* Submitted Documents with Preview */}
          {submittedDocs.length > 0 && (
            <SubmittedDocumentsList
              documents={submittedDocs}
              email={user.email}
            />
          )}

          {/* Member Progress */}
          {membersInfo && (
            <MemberProgress membersInfo={membersInfo} />
          )}

          {/* Upload Section */}
          {!isComplete && !validationComplete && (
            <>
              {accountType === 'Corporate' && 
               ownershipType === 'Partnership' && 
               stage === 'identification' && (
                <StageOneUpload 
                  email={user.email}
                  onSuccess={handleDocumentSuccess}
                />
              )}

              {accountType === 'Corporate' && 
               ownershipType === 'Partnership' && 
               stage === 'member_eids' && (
                <StageTwoUpload
                  email={user.email}
                  membersInfo={membersInfo}
                  onSuccess={handleDocumentSuccess}
                />
              )}

              {!(accountType === 'Corporate' && ownershipType === 'Partnership') && (
                <BulkUpload
                  email={user.email}
                  requiredDocs={documentRequirements.required_documents || []}
                  onSuccess={handleDocumentSuccess}
                />
              )}
            </>
          )}

          {/* Final Confirmation */}
          {isComplete && !validationComplete && !confirmationSent && (
            <FinalConfirmation
              email={user.email}
              onSuccess={() => {
                setValidationComplete(true);
                setConfirmationSent(true);
                toast.success('Verification complete!');
                setTimeout(() => loadDocumentData(), 2000);
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
};

export default DocumentUpload;