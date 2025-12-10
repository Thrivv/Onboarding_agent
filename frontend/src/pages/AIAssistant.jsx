// frontend/src/pages/AIAssistant.jsx - COMPLETE FIXED VERSION

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useAuth } from '../context/AuthContext';
import Sidebar from '../components/layout/Sidebar';
import api from '../services/api';
import toast from 'react-hot-toast';
import { 
  Send, Paperclip, X, RefreshCw, 
  Loader, Upload, User, Bot, FileText,
  Building, Home, Users, Eye, RotateCcw
} from 'lucide-react';

// ============================================================================
// HELPER COMPONENTS
// ============================================================================

const InfoRow = ({ label, value }) => {
  if (!value || value === 'N/A' || value === 'null' || value === 'undefined') {
    return null;
  }

  return (
    <div className="flex justify-between items-start py-1 border-b border-gray-100 last:border-0">
      <span className="font-medium text-gray-600 text-xs">{label}:</span>
      <span className="text-gray-800 text-xs text-right ml-2">{String(value)}</span>
    </div>
  );
};

const formatLabel = (key) => {
  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
};

// ============================================================================
// DOCUMENT PREVIEW MODAL
// ============================================================================

const DocumentPreviewModal = ({ isOpen, onClose, document }) => {
  if (!isOpen || !document) return null;

  const isPDF = document.type === 'application/pdf';
  const isImage = document.type?.startsWith('image/');

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50 p-4"
         onClick={onClose}>
      <div className="bg-white rounded-lg shadow-2xl max-w-4xl w-full max-h-[90vh] overflow-hidden"
           onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b bg-gradient-to-r from-purple-600 to-indigo-600">
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
              title="PDF Preview"
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
                title="PDF Preview"
              />
            )
          ) : (
            <div className="flex items-center justify-center h-64 text-gray-500">
              <p>Preview not available</p>
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

const EIDExtractedData = ({ data }) => (
  <div className="space-y-3 text-sm">
    {/* Personal Information */}
    <div className="bg-white p-3 rounded-lg">
      <p className="font-semibold text-indigo-900 mb-2 flex items-center gap-2">
        <User className="h-4 w-4" />
        Personal Information
      </p>
      <div className="space-y-1 text-gray-700">
        <InfoRow label="Name" value={data.Name || data.name} />
        <InfoRow label="ID Number" value={data['ID Number'] || data.id_number} />
        <InfoRow label="Nationality" value={data.Nationality || data.nationality} />
        <InfoRow label="Sex" value={data.Sex || data.sex} />
      </div>
    </div>

    {/* Date Information */}
    <div className="bg-white p-3 rounded-lg">
      <p className="font-semibold text-indigo-900 mb-2">📅 Date Information</p>
      <div className="space-y-1 text-gray-700">
        <InfoRow label="Date of Birth" value={data['Date of Birth'] || data.date_of_birth} />
        <InfoRow label="Issuing Date" value={data['Issuing Date'] || data.issuing_date} />
        <InfoRow label="Expiry Date" value={data['Expiry Date'] || data.expiry_date} />
      </div>
    </div>
  </div>
);

// ============================================================================
// EJARI (TENANCY CONTRACT) DISPLAY
// ============================================================================

const EjariExtractedData = ({ data }) => (
  <div className="space-y-3 text-sm">
    {/* Contract Information */}
    <div className="bg-white p-3 rounded-lg">
      <p className="font-semibold text-indigo-900 mb-2 flex items-center gap-2">
        <FileText className="h-4 w-4" />
        Contract Information
      </p>
      <div className="space-y-1 text-gray-700">
        <InfoRow label="Contract Number" value={data.contract_number} />
        <InfoRow label="Registration Date" value={data.registration_date} />
        <InfoRow label="Start Date" value={data.start_date} />
        <InfoRow label="End Date" value={data.end_date} />
        <InfoRow label="Contract Value" value={data.contract_value} />
        <InfoRow label="Payment Method" value={data.payment_method} />
      </div>
    </div>

    {/* Property Information */}
    <div className="bg-white p-3 rounded-lg">
      <p className="font-semibold text-indigo-900 mb-2 flex items-center gap-2">
        <Home className="h-4 w-4" />
        Property Information
      </p>
      <div className="space-y-1 text-gray-700">
        <InfoRow label="Property Type" value={data.property_type} />
        <InfoRow label="Property Subtype" value={data.property_subtype} />
        <InfoRow label="Size" value={data.size} />
        <InfoRow label="Usage" value={data.usage} />
        <InfoRow label="Building Name" value={data.building_name} />
        <InfoRow label="Area" value={data.area || data.community} />
        <InfoRow label="Emirates" value={data.emirates} />
      </div>
    </div>

    {/* Parties */}
    <div className="bg-white p-3 rounded-lg">
      <p className="font-semibold text-indigo-900 mb-2">👥 Parties</p>
      <div className="space-y-2">
        <div>
          <p className="font-medium text-gray-800 text-xs">Lessor (Owner):</p>
          <div className="ml-3 space-y-1 text-gray-700">
            <InfoRow label="Name" value={data.owner_name || data.lessor_name} />
            <InfoRow label="Company" value={data.lessor_company} />
            <InfoRow label="License" value={data.lessor_license_number} />
          </div>
        </div>
        <div>
          <p className="font-medium text-gray-800 text-xs">Tenant:</p>
          <div className="ml-3 space-y-1 text-gray-700">
            <InfoRow label="Company" value={data.tenant_company} />
            <InfoRow label="License" value={data.tenant_license} />
          </div>
        </div>
      </div>
    </div>
  </div>
);

// ============================================================================
// COMMERCIAL LICENSE DISPLAY
// ============================================================================

const CommercialExtractedData = ({ data }) => {
  const englishData = data.english || {};
  const managers = data.managers || [];
  const partners = data.partners || [];
  const activities = data.activities || [];

  return (
    <div className="space-y-3 text-sm">
      {/* Company Information */}
      <div className="bg-white p-3 rounded-lg">
        <p className="font-semibold text-indigo-900 mb-2 flex items-center gap-2">
          <Building className="h-4 w-4" />
          Company Information
        </p>
        <div className="space-y-1 text-gray-700">
          <InfoRow label="Company Name" value={englishData.company_name_english || englishData['Company Name']} />
          <InfoRow label="Trade Name" value={englishData.trade_name_english || englishData['Trade Name']} />
          <InfoRow label="License Number" value={englishData.license_number || englishData['License Number']} />
          <InfoRow label="Legal Type" value={englishData.legal_type || englishData['Legal Type']} />
          <InfoRow label="Status" value={englishData.status || englishData['Status']} />
          <InfoRow label="Issue Date" value={englishData.issue_date || englishData['Issue Date']} />
          <InfoRow label="Expiry Date" value={englishData.expiry_date || englishData['Expiry Date']} />
        </div>
      </div>

      {/* Business Activities */}
      {activities.length > 0 && (
        <div className="bg-white p-3 rounded-lg">
          <p className="font-semibold text-indigo-900 mb-2">📊 Business Activities</p>
          <ul className="list-disc list-inside space-y-1 text-gray-700 text-xs">
            {activities.slice(0, 5).map((activity, idx) => (
              <li key={idx}>{activity}</li>
            ))}
            {activities.length > 5 && (
              <li className="text-indigo-600">+ {activities.length - 5} more...</li>
            )}
          </ul>
        </div>
      )}

      {/* Managers */}
      {managers.length > 0 && (
        <div className="bg-white p-3 rounded-lg">
          <p className="font-semibold text-indigo-900 mb-2 flex items-center gap-2">
            <Users className="h-4 w-4" />
            Managers
          </p>
          <div className="space-y-2">
            {managers.slice(0, 3).map((mgr, idx) => (
              <div key={idx} className="text-gray-700 text-xs">
                <span className="font-medium">
                  {mgr.name_english || mgr['Name (EN)']}
                </span>
                {' - '}
                <span className="text-gray-600">
                  {mgr.role || mgr['Role']} ({mgr.nationality_english || mgr['Nationality (EN)']})
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Partners/Shareholders */}
      {partners.length > 0 && (
        <div className="bg-white p-3 rounded-lg">
          <p className="font-semibold text-indigo-900 mb-2">💼 Partners/Shareholders</p>
          <div className="space-y-2">
            {partners.slice(0, 3).map((partner, idx) => (
              <div key={idx} className="text-gray-700 text-xs">
                <span className="font-medium">
                  {partner.name_english || partner['Name (EN)']}
                </span>
                {' - '}
                <span className="text-gray-600">
                  Share: {partner.share || partner['Share']} ({partner.share_percentage || partner['Share Percentage']}%)
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

// ============================================================================
// MOA (MEMORANDUM OF ASSOCIATION) DISPLAY
// ============================================================================

const MOAExtractedData = ({ data }) => (
  <div className="space-y-3 text-sm">
    {/* Company Details */}
    <div className="bg-white p-3 rounded-lg">
      <p className="font-semibold text-indigo-900 mb-2 flex items-center gap-2">
        <Building className="h-4 w-4" />
        Company Details
      </p>
      <div className="space-y-1 text-gray-700">
        <InfoRow label="Company Name (EN)" value={data.company_name || data['Company Name (EN)']} />
        <InfoRow label="Owner Name (EN)" value={data.owner_name || data['Owner Name (EN)']} />
        <InfoRow label="Manager Name (EN)" value={data.manager_name || data['Manager Name (EN)']} />
        <InfoRow label="Execution Date" value={data.execution_date || data['Execution Date']} />
      </div>
    </div>

    {/* Share Information */}
    <div className="bg-white p-3 rounded-lg">
      <p className="font-semibold text-indigo-900 mb-2">📊 Share Information</p>
      <div className="space-y-1 text-gray-700">
        <InfoRow label="Number of Shares" value={data.number_of_shares || data['Number of Shares']} />
        <InfoRow label="Value per Share" value={data.value_per_share || data['Value per Share']} />
        <InfoRow label="Share Type" value={data.share_type || data['Share Type']} />
        <InfoRow label="Capital" value={data.capital || data['Capital']} />
      </div>
    </div>
  </div>
);

// ============================================================================
// GENERIC DISPLAY (FALLBACK)
// ============================================================================

const GenericExtractedData = ({ data }) => {
  if (!data || typeof data !== 'object') {
    return <p className="text-sm text-gray-600">No extracted data available</p>;
  }

  return (
    <div className="bg-white p-3 rounded-lg">
      <div className="space-y-1 text-sm text-gray-700">
        {Object.entries(data).slice(0, 8).map(([key, value]) => {
          if (value === null || value === undefined) return null;
          if (typeof value === 'object') return null;
          
          return <InfoRow key={key} label={formatLabel(key)} value={value} />;
        })}
      </div>
    </div>
  );
};

// ============================================================================
// EXTRACTED DATA DISPLAY COMPONENT
// ============================================================================

const ExtractedDataDisplay = ({ data, documentType }) => {
  if (!data) return null;

  const englishData = data.english || data;

  const renderContent = () => {
    switch (documentType?.toLowerCase()) {
      case 'eid':
        return <EIDExtractedData data={englishData} />;
      case 'ejari':
      case 'tenancy':
        return <EjariExtractedData data={englishData} />;
      case 'commercial':
        return <CommercialExtractedData data={data} />;
      case 'moa':
      case 'memorandum':
        return <MOAExtractedData data={englishData} />;
      default:
        return <GenericExtractedData data={englishData} />;
    }
  };

  return (
    <div className="mt-3 p-4 bg-gradient-to-br from-indigo-50 to-purple-50 rounded-lg border-2 border-indigo-200">
      <div className="flex items-center gap-2 mb-3">
        <FileText className="h-4 w-4 text-indigo-600" />
        <p className="text-sm font-bold text-indigo-900">📋 Extracted Information</p>
      </div>
      {renderContent()}
    </div>
  );
};

// ============================================================================
// MAIN COMPONENT
// ============================================================================

const AIAssistant = () => {
  const { user } = useAuth();
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [uploadedFile, setUploadedFile] = useState(null);
  const [memberName, setMemberName] = useState('');
  const [showMemberInput, setShowMemberInput] = useState(false);
  const [onboardingStatus, setOnboardingStatus] = useState(null);
  const [conversationStarted, setConversationStarted] = useState(false);
  
  // Document preview modal
  const [previewDocument, setPreviewDocument] = useState(null);
  const [showPreview, setShowPreview] = useState(false);
  
  // Retry state
  const [retryContext, setRetryContext] = useState(null);
  
  const messagesEndRef = useRef(null);
  const fileInputRef = useRef(null);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  // Convert file to base64
  const fileToBase64 = (file) => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.readAsDataURL(file);
      reader.onload = () => {
        const base64 = reader.result.split(',')[1];
        resolve(base64);
      };
      reader.onerror = error => reject(error);
    });
  };

  // Initialize conversation
  const initializeChat = useCallback(async () => {
    if (!user?.email || conversationStarted) return;
    
    try {
      setIsLoading(true);
      
      // Load conversation history
      const historyResp = await api.get(`/chatupload/conversation-logs/${user.email}`, {
        params: { limit: 50, channel: 'chat' }
      });

      if (historyResp.data && historyResp.data.logs) {
        const logs = historyResp.data.logs;
        const loadedMessages = logs.reverse().map(log => {
          // Parse extracted_data and document_metadata if available
          let extractedData = null;
          let documentMetadata = null;
          
          try {
            if (log.extracted_data) {
              extractedData = typeof log.extracted_data === 'string' 
                ? JSON.parse(log.extracted_data) 
                : log.extracted_data;
            }
            if (log.document_metadata) {
              documentMetadata = typeof log.document_metadata === 'string'
                ? JSON.parse(log.document_metadata)
                : log.document_metadata;
            }
          } catch (e) {
            console.error('[INIT] Parse error:', e);
          }
          
          return {
            role: log.role === 'agent' ? 'assistant' : 'user',
            content: log.message,
            timestamp: log.timestamp,
            documentType: log.document_type,
            extractedData: extractedData,
            documentMetadata: documentMetadata
          };
        });
        setMessages(loadedMessages);
      }

      // Start conversation
      const response = await api.post('/chatupload/start-conversation', {
        email: user.email
      });

      if (response.data) {
        const welcomeMsg = response.data.welcome_message || 
                          response.data.status?.ai_message || 
                          `Welcome ${user.name}! I'm here to help you with your document onboarding.`;
        
        // Only add welcome if no history loaded
        if (!historyResp.data?.logs || historyResp.data.logs.length === 0) {
          setMessages([{
            role: 'assistant',
            content: welcomeMsg,
            timestamp: new Date().toISOString()
          }]);
        }
        
        if (response.data.status) {
          setOnboardingStatus(response.data.status);
          
          const ownershipType = response.data.status?.ownership_type;
          const stage = response.data.status?.stage;
          if ((ownershipType === 'Partnership' || ownershipType === 'Multiple Owners') && 
              stage === 'member_eids') {
            setShowMemberInput(true);
          }
        }
        
        setConversationStarted(true);
      }
    } catch (error) {
      console.error('[AI ASSISTANT] Init error:', error);
      
      // Fallback welcome message
      setMessages([{
        role: 'assistant',
        content: `Welcome ${user?.name || 'there'}! I'm here to help you with your document onboarding. Please upload your documents or ask me any questions.`,
        timestamp: new Date().toISOString()
      }]);
      setConversationStarted(true);
    } finally {
      setIsLoading(false);
    }
  }, [user, conversationStarted]);

  useEffect(() => {
    if (user?.email) {
      initializeChat();
    }
  }, [user, initializeChat]);

  // Handle file selection
  const handleFileSelect = (e) => {
    const file = e.target.files[0];
    if (file) {
      const validTypes = ['application/pdf', 'image/jpeg', 'image/jpg', 'image/png', 'image/webp'];
      const maxSize = 10 * 1024 * 1024; // 10MB
      
      if (!validTypes.includes(file.type)) {
        toast.error('Please upload PDF, JPG, PNG, or WEBP files only');
        e.target.value = '';
        return;
      }
      
      if (file.size > maxSize) {
        toast.error('File size must be less than 10MB');
        e.target.value = '';
        return;
      }
      
      setUploadedFile(file);
      toast.success(`File selected: ${file.name}`);
    }
  };

  // Handle document upload - FIXED VERSION
  const handleUploadDocument = async () => {
    if (!uploadedFile) {
      toast.error('Please select a file first');
      return;
    }

    // Check member name for partnerships
    if (showMemberInput && !memberName.trim()) {
      toast.error('Please enter the member name before uploading');
      return;
    }

    // Create preview URL for current file
    const previewUrl = URL.createObjectURL(uploadedFile);
    
    // Convert to base64 for storage
    let base64Data = null;
    try {
      base64Data = await fileToBase64(uploadedFile);
    } catch (error) {
      console.error('[UPLOAD] Base64 conversion error:', error);
    }

    const userMessage = {
      role: 'user',
      content: `📎 Uploaded: ${uploadedFile.name}${memberName ? ` (for ${memberName})` : ''}`,
      timestamp: new Date().toISOString(),
      isUpload: true,
      documentMetadata: {
        name: uploadedFile.name,
        type: uploadedFile.type,
        size: uploadedFile.size,
        previewUrl: previewUrl,
        base64: base64Data
      }
    };

    setMessages(prev => [...prev, userMessage]);
    setIsLoading(true);

    try {
      const formData = new FormData();
      formData.append('email', user.email);
      formData.append('files', uploadedFile);
      
      if (memberName.trim()) {
        formData.append('member_name', memberName.trim());
      }

      console.log('[UPLOAD] Sending request...');
      
      const response = await api.post('/chatupload/upload-conversational', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });

      console.log('[UPLOAD] Response received:', response.data);

      if (response.data) {
        // Check if wrong document type
        if (response.data.wrong_document_type) {
          const errorMessage = response.data.message || 'Wrong document type uploaded';
          
          setMessages(prev => [...prev, {
            role: 'assistant',
            content: errorMessage,
            timestamp: new Date().toISOString(),
            isError: true
          }]);
          
          toast.error(`Wrong document type: ${response.data.document_type?.toUpperCase()}`);
          
          // Store retry context
          setRetryContext({
            file: uploadedFile,
            memberName: memberName
          });
        } else {
          // Success case
          const acknowledgment = response.data.acknowledgment || response.data.message || 'Document uploaded successfully!';
          
          console.log('[UPLOAD] Extracted data:', response.data.extracted_data);
          
          setMessages(prev => [...prev, {
            role: 'assistant',
            content: acknowledgment,
            timestamp: new Date().toISOString(),
            documentType: response.data.document_type,
            extractedData: response.data.extracted_data
          }]);
          
          toast.success('Document uploaded and processed successfully!');
          
          // Reset member name after successful upload
          if (showMemberInput) {
            setMemberName('');
          }
          
          // Clear retry context on success
          setRetryContext(null);
        }
      }
      
      // Clear file
      setUploadedFile(null);
      if (fileInputRef.current) fileInputRef.current.value = '';
      
    } catch (error) {
      console.error('[AI ASSISTANT] Upload error:', error);
      
      const errorMsg = error.response?.data?.detail || 'Failed to upload document. Please try again.';
      toast.error(errorMsg);
      
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: `❌ ${errorMsg}`,
        timestamp: new Date().toISOString(),
        isError: true,
        canRetry: true
      }]);
      
      // Store retry context
      setRetryContext({
        file: uploadedFile,
        memberName: memberName
      });
      
    } finally {
      setIsLoading(false);
    }
  };

  // Handle retry
  const handleRetry = async () => {
    if (!retryContext) return;
    
    setUploadedFile(retryContext.file);
    setMemberName(retryContext.memberName || '');
    
    // Wait for state to update, then trigger upload
    setTimeout(() => {
      handleUploadDocument();
    }, 100);
  };

  // Handle text message
  const handleSendMessage = async () => {
    if (!input.trim()) {
      toast.error('Please enter a message');
      return;
    }

    const userMessage = {
      role: 'user',
      content: input,
      timestamp: new Date().toISOString()
    };

    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);

    try {
      const response = await api.post('/chatupload/chat-conversational', {
        email: user.email,
        message: input,
        chat_history: messages.slice(-10).map(msg => ({
          role: msg.role,
          content: msg.content,
          timestamp: msg.timestamp
        }))
      });

      if (response.data && response.data.response) {
        const agentMessage = {
          role: 'assistant',
          content: response.data.response,
          timestamp: new Date().toISOString()
        };
        
        setMessages(prev => [...prev, agentMessage]);
      }
    } catch (error) {
      console.error('[AI ASSISTANT] Chat error:', error);
      toast.error('Failed to send message');
      
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: 'Sorry, I encountered an error. Please try again.',
        timestamp: new Date().toISOString(),
        isError: true
      }]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (uploadedFile) {
        handleUploadDocument();
      } else {
        handleSendMessage();
      }
    }
  };

  const handleClearChat = () => {
    if (window.confirm('Are you sure you want to clear the chat history?')) {
      setMessages([]);
      setConversationStarted(false);
      initializeChat();
    }
  };

  const removeFile = () => {
    setUploadedFile(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const openPreview = (doc) => {
    setPreviewDocument(doc);
    setShowPreview(true);
  };

  const closePreview = () => {
    setShowPreview(false);
    setPreviewDocument(null);
  };

  return (
    <div className="flex h-screen bg-gradient-to-br from-purple-50 to-indigo-100">
      <Sidebar />
      
      {/* Document Preview Modal */}
      <DocumentPreviewModal 
        isOpen={showPreview}
        onClose={closePreview}
        document={previewDocument}
      />
      
      {/* Main Chat Area */}
      <div className="flex-1 ml-64 flex flex-col">
        {/* Header */}
        <div className="bg-white border-b shadow-sm p-4">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-purple-600 to-indigo-600">
                🤖 AI Onboarding Assistant
              </h1>
              <p className="text-sm text-gray-600 mt-1">
                Upload documents and ask questions - I'm here to help!
              </p>
            </div>
            <button
              onClick={handleClearChat}
              className="px-4 py-2 text-gray-600 hover:text-gray-800 hover:bg-gray-100 rounded-lg transition-colors flex items-center gap-2"
              title="Clear Chat"
            >
              <RefreshCw className="h-4 w-4" />
              Clear
            </button>
          </div>
          
          {/* Account Info */}
          {onboardingStatus && (
            <div className="mt-3 flex gap-3">
              <div className="px-3 py-1 bg-blue-100 text-blue-800 rounded-full text-sm font-medium">
                💼 {onboardingStatus?.account_type || 'Not Set'}
              </div>
              <div className="px-3 py-1 bg-purple-100 text-purple-800 rounded-full text-sm font-medium">
                👥 {onboardingStatus?.ownership_type || 'Not Set'}
              </div>
              <div className="px-3 py-1 bg-green-100 text-green-800 rounded-full text-sm font-medium">
                📋 {onboardingStatus?.stage || 'Identification'}
              </div>
            </div>
          )}
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4">
          <div className="max-w-4xl mx-auto space-y-4">
            {messages.map((msg, index) => (
              <div
                key={index}
                className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'} animate-fadeIn`}
              >
                <div className={`
                  max-w-[80%] rounded-2xl px-4 py-3 shadow-sm
                  ${msg.role === 'user' 
                    ? 'bg-gradient-to-r from-purple-600 to-indigo-600 text-white' 
                    : msg.isError
                    ? 'bg-red-50 text-red-800 border-2 border-red-300'
                    : 'bg-white text-gray-800 border border-gray-200'
                  }
                `}>
                  {/* Message Header */}
                  <div className="flex items-center gap-2 mb-2">
                    {msg.role === 'user' ? (
                      <User className="h-4 w-4" />
                    ) : (
                      <Bot className="h-4 w-4" />
                    )}
                    <span className="text-xs opacity-75">
                      {new Date(msg.timestamp).toLocaleTimeString()}
                    </span>
                  </div>
                  
                  {/* Message Content */}
                  <div className="whitespace-pre-wrap break-words">
                    {msg.content}
                  </div>
                  
                  {/* Document Preview Button for User Messages */}
                  {msg.documentMetadata && (
                    <button
                      onClick={() => openPreview(msg.documentMetadata)}
                      className="mt-2 flex items-center gap-2 px-3 py-1 bg-white bg-opacity-20 hover:bg-opacity-30 rounded-lg transition-colors text-sm"
                    >
                      <Eye className="h-4 w-4" />
                      View Document
                    </button>
                  )}
                  
                  {/* Extracted Data Display */}
                  {msg.extractedData && (
                    <ExtractedDataDisplay 
                      data={msg.extractedData} 
                      documentType={msg.documentType}
                    />
                  )}
                  
                  {/* Retry Button for Errors */}
                  {msg.isError && msg.canRetry && retryContext && (
                    <button
                      onClick={handleRetry}
                      disabled={isLoading}
                      className="mt-2 flex items-center gap-2 px-3 py-1 bg-red-600 hover:bg-red-700 text-white rounded-lg transition-colors text-sm disabled:opacity-50"
                    >
                      <RotateCcw className="h-4 w-4" />
                      Retry Upload
                    </button>
                  )}
                </div>
              </div>
            ))}
            
            {/* Loading Indicator */}
            {isLoading && (
              <div className="flex justify-start">
                <div className="bg-white rounded-2xl px-4 py-3 shadow-sm border border-gray-200">
                  <div className="flex items-center gap-2">
                    <Loader className="h-4 w-4 animate-spin text-purple-600" />
                    <span className="text-sm text-gray-600">
                      {uploadedFile ? 'Processing document...' : 'Thinking...'}
                    </span>
                  </div>
                </div>
              </div>
            )}
            
            <div ref={messagesEndRef} />
          </div>
        </div>

        {/* Input Area */}
        <div className="bg-white border-t shadow-lg p-4">
          <div className="max-w-4xl mx-auto">
            {/* Member Name Input (Conditional) */}
            {showMemberInput && (
              <div className="mb-3 p-3 bg-yellow-50 border-2 border-yellow-300 rounded-lg">
                <label className="block text-sm font-semibold text-yellow-900 mb-2">
                  👥 Member Name (as shown in documents):
                </label>
                <input
                  type="text"
                  value={memberName}
                  onChange={(e) => setMemberName(e.target.value)}
                  placeholder="e.g., John Doe"
                  className="w-full px-3 py-2 border border-yellow-300 rounded-lg focus:ring-2 focus:ring-yellow-500 focus:border-transparent"
                />
                {memberName && (
                  <p className="text-xs text-yellow-800 mt-1">✅ Member name set: {memberName}</p>
                )}
              </div>
            )}
            
            {/* File Preview */}
            {uploadedFile && (
              <div className="mb-3 p-3 bg-blue-50 border-2 border-blue-300 rounded-lg flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Paperclip className="h-5 w-5 text-blue-600" />
                  <span className="text-sm font-medium text-blue-900">{uploadedFile.name}</span>
                  <span className="text-xs text-blue-600">
                    ({(uploadedFile.size / 1024 / 1024).toFixed(2)} MB)
                  </span>
                </div>
                <button
                  onClick={removeFile}
                  className="text-red-600 hover:text-red-800 p-1"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
            )}
            
            {/* Input Row */}
            <div className="flex gap-2">
              {/* File Upload Button */}
              <input
                ref={fileInputRef}
                type="file"
                onChange={handleFileSelect}
                accept=".pdf,.jpg,.jpeg,.png,.webp"
                className="hidden"
                disabled={isLoading}
              />
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={isLoading}
                className="px-4 py-3 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors disabled:opacity-50"
                title="Upload Document"
              >
                <Paperclip className="h-5 w-5 text-gray-600" />
              </button>
              
              {/* Text Input */}
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyPress={handleKeyPress}
                placeholder="Ask me anything about your documents..."
                disabled={isLoading}
                className="flex-1 px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent disabled:opacity-50"
              />
              
              {/* Send/Upload Button */}
              <button
                onClick={uploadedFile ? handleUploadDocument : handleSendMessage}
                disabled={isLoading || (!input.trim() && !uploadedFile)}
                className="px-6 py-3 bg-gradient-to-r from-purple-600 to-indigo-600 text-white rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50 flex items-center gap-2"
              >
                {uploadedFile ? (
                  <>
                    <Upload className="h-5 w-5" />
                    Upload
                  </>
                ) : (
                  <>
                    <Send className="h-5 w-5" />
                    Send
                  </>
                )}
              </button>
            </div>
            
            <p className="text-xs text-gray-500 mt-2">
              💡 Tip: Upload documents (PDF, JPG, PNG) or ask questions about your onboarding
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default AIAssistant;