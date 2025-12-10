// frontend/src/components/documents/BulkUpload.jsx

import React, { useState } from 'react';
import { Upload, Loader, X } from 'lucide-react';
import api from '../../services/api';
import toast from 'react-hot-toast';

const BulkUpload = ({ email, requiredDocs, onSuccess }) => {
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [isUploading, setIsUploading] = useState(false);

  const handleFileSelect = (e) => {
    const files = Array.from(e.target.files);
    
    if (files.length === 0) return;

    const validTypes = ['application/pdf', 'image/jpeg', 'image/jpg', 'image/png', 'image/webp'];
    const invalidFiles = files.filter(f => !validTypes.includes(f.type));
    
    if (invalidFiles.length > 0) {
      toast.error('Please upload only PDF, JPG, PNG, or WEBP files');
      return;
    }

    const maxSize = 10 * 1024 * 1024;
    const oversizedFiles = files.filter(f => f.size > maxSize);
    
    if (oversizedFiles.length > 0) {
      toast.error('File size must be less than 10MB');
      return;
    }

    setSelectedFiles(files);
    toast.success(`${files.length} file(s) selected`);
  };

  const removeFile = (index) => {
    setSelectedFiles(prev => prev.filter((_, i) => i !== index));
    toast.info('File removed');
  };

  const handleUpload = async () => {
    if (selectedFiles.length === 0) {
      toast.error('Please select at least one file');
      return;
    }

    setIsUploading(true);
    let successCount = 0;
    let lastSuccessResponse = null; // ✅ Store last response

    try {
      for (let i = 0; i < selectedFiles.length; i++) {
        const file = selectedFiles[i];
        const formData = new FormData();
        formData.append('email', email);
        formData.append('files', file);

        toast.loading(`Uploading ${file.name}...`, { id: `upload-${i}` });

        const response = await api.post('/documentupload/upload-document', formData, {
          headers: { 'Content-Type': 'multipart/form-data' }
        });

        if (response.data.success) {
          successCount++;
          lastSuccessResponse = response.data; // ✅ Save response
          toast.success(`✅ ${file.name} uploaded`, { id: `upload-${i}` });
        } else {
          toast.error(`❌ Failed: ${file.name}`, { id: `upload-${i}` });
        }
      }

      if (successCount > 0) {
        // ✅ REMOVED: Success popup/toast
        setSelectedFiles([]);
        
        // ✅ Pass response to parent
        if (onSuccess) {
          onSuccess(lastSuccessResponse);
        }
      }
    } catch (error) {
      console.error('Upload error:', error);
      toast.error('Upload failed. Please try again.');
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="bg-white rounded-xl shadow-lg p-6 mb-6">
      <h2 className="text-xl font-bold text-gray-800 mb-4 flex items-center gap-2">
        <Upload className="h-6 w-6 text-indigo-600" />
        Upload Documents
      </h2>

      <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 mb-4">
        <p className="text-sm text-yellow-800 font-medium mb-2">
          📋 Required Documents:
        </p>
        <ul className="text-sm text-yellow-800 space-y-1">
          {requiredDocs.map((doc, idx) => (
            <li key={idx}>• {doc}</li>
          ))}
        </ul>
      </div>
      
      <div className="space-y-4">
        <div className="border-2 border-dashed border-gray-300 rounded-lg p-8 text-center hover:border-indigo-500 transition-colors">
          <input
            type="file"
            multiple
            accept=".pdf,.jpg,.jpeg,.png,.webp"
            onChange={handleFileSelect}
            className="hidden"
            id="bulk-upload"
            disabled={isUploading}
          />
          <label
            htmlFor="bulk-upload"
            className="cursor-pointer flex flex-col items-center gap-3"
          >
            <Upload className="h-12 w-12 text-gray-400" />
            <div>
              <p className="text-lg font-semibold text-gray-700">
                Click to select files
              </p>
              <p className="text-sm text-gray-500 mt-1">
                PDF, JPG, PNG (Max 10MB each)
              </p>
            </div>
          </label>
        </div>

        {selectedFiles.length > 0 && (
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
            <p className="font-semibold text-blue-900 mb-2">Selected Files ({selectedFiles.length}):</p>
            <div className="space-y-2">
              {selectedFiles.map((file, idx) => (
                <div key={idx} className="flex items-center justify-between bg-white p-2 rounded">
                  <span className="text-sm text-gray-700">
                    {file.name} ({(file.size / 1024 / 1024).toFixed(2)} MB)
                  </span>
                  <button
                    onClick={() => removeFile(idx)}
                    className="text-red-500 hover:text-red-700"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        <button
          onClick={handleUpload}
          disabled={isUploading || selectedFiles.length === 0}
          className="w-full py-3 bg-gradient-to-r from-indigo-600 to-purple-600 text-white font-semibold rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
        >
          {isUploading ? (
            <>
              <Loader className="h-5 w-5 animate-spin" />
              Uploading {selectedFiles.length} file(s)...
            </>
          ) : (
            <>
              <Upload className="h-5 w-5" />
              Upload All Files
            </>
          )}
        </button>
      </div>
    </div>
  );
};

export default BulkUpload;