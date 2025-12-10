// frontend/src/components/documents/StageTwoUpload.jsx

import React, { useState } from 'react';
import { Upload, Loader, User } from 'lucide-react';
import api from '../../services/api';
import toast from 'react-hot-toast';

const StageTwoUpload = ({ email, membersInfo, onSuccess }) => {
  const [selectedFile, setSelectedFile] = useState(null);
  const [isUploading, setIsUploading] = useState(false);

  if (!membersInfo || !membersInfo.current_member) {
    return null;
  }

  const currentMember = membersInfo.current_member;

  const handleFileSelect = (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const validTypes = ['application/pdf', 'image/jpeg', 'image/jpg', 'image/png', 'image/webp'];
    if (!validTypes.includes(file.type)) {
      toast.error('Please upload only PDF, JPG, PNG, or WEBP files');
      return;
    }

    const maxSize = 10 * 1024 * 1024;
    if (file.size > maxSize) {
      toast.error('File size must be less than 10MB');
      return;
    }

    setSelectedFile(file);
    toast.success('File selected');
  };

  const handleUpload = async () => {
    if (!selectedFile) {
      toast.error('Please select a file');
      return;
    }

    setIsUploading(true);

    try {
      const formData = new FormData();
      formData.append('email', email);
      formData.append('files', selectedFile);
      formData.append('member_name', currentMember);

      toast.loading('Uploading EID...', { id: 'member-upload' });

      const response = await api.post('/documentupload/upload-document', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });

      if (response.data.success) {
        // ✅ REMOVED: toast.success
        toast.dismiss('member-upload');
        setSelectedFile(null);
        
        // ✅ Pass response to parent
        if (onSuccess) {
          onSuccess(response.data);
        }
      } else {
        toast.error('Upload failed', { id: 'member-upload' });
      }
    } catch (error) {
      console.error('Upload error:', error);
      toast.error('Upload failed. Please try again.', { id: 'member-upload' });
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="bg-white rounded-xl shadow-lg p-6 mb-6">
      <h2 className="text-xl font-bold text-gray-800 mb-4 flex items-center gap-2">
        <User className="h-6 w-6 text-indigo-600" />
        Stage 2: Upload EID for {currentMember}
      </h2>

      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-4">
        <p className="text-sm text-blue-800">
          <strong>Current Member:</strong> {currentMember}
          <br />
          <strong>Progress:</strong> {membersInfo.completed_count} / {membersInfo.total_members} completed
        </p>
      </div>
      
      <div className="space-y-4">
        <div className="border-2 border-dashed border-gray-300 rounded-lg p-8 text-center hover:border-indigo-500 transition-colors">
          <input
            type="file"
            accept=".pdf,.jpg,.jpeg,.png,.webp"
            onChange={handleFileSelect}
            className="hidden"
            id="stage-two-upload"
            disabled={isUploading}
          />
          <label
            htmlFor="stage-two-upload"
            className="cursor-pointer flex flex-col items-center gap-3"
          >
            <Upload className="h-12 w-12 text-gray-400" />
            <div>
              <p className="text-lg font-semibold text-gray-700">
                Click to select Emirates ID
              </p>
              <p className="text-sm text-gray-500 mt-1">
                PDF, JPG, PNG (Max 10MB)
              </p>
            </div>
          </label>
        </div>

        {selectedFile && (
          <div className="bg-green-50 border border-green-200 rounded-lg p-4">
            <p className="font-semibold text-green-900 mb-1">Selected File:</p>
            <p className="text-sm text-green-800">
              {selectedFile.name} ({(selectedFile.size / 1024 / 1024).toFixed(2)} MB)
            </p>
          </div>
        )}

        <button
          onClick={handleUpload}
          disabled={isUploading || !selectedFile}
          className="w-full py-3 bg-gradient-to-r from-indigo-600 to-purple-600 text-white font-semibold rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
        >
          {isUploading ? (
            <>
              <Loader className="h-5 w-5 animate-spin" />
              Uploading...
            </>
          ) : (
            <>
              <Upload className="h-5 w-5" />
              Upload EID
            </>
          )}
        </button>
      </div>
    </div>
  );
};

export default StageTwoUpload;