// frontend/src/services/document.service.js

import api from './api';

class DocumentService {
  /**
   * Get document requirements for user
   */
  async getRequirements(email) {
    try {
      const response = await api.post('/documentupload/get-document-requirements', {
        email,
      });
      return response.data;
    } catch (error) {
      throw this.handleError(error);
    }
  }

  /**
   * Get document upload status
   */
  async getStatus(email) {
    try {
      const response = await api.get(`/documentupload/document-status/${email}`);
      return response.data;
    } catch (error) {
      throw this.handleError(error);
    }
  }

  /**
   * Upload document
   */
  async uploadDocument(email, file, memberName = null) {
    try {
      const formData = new FormData();
      formData.append('files', file);
      formData.append('email', email);
      
      if (memberName) {
        formData.append('member_name', memberName);
      }

      const response = await api.post('/documentupload/upload-document', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      });

      return response.data;
    } catch (error) {
      throw this.handleError(error);
    }
  }

  /**
   * Get document preview
   */
  async getPreview(email, docType, memberName = null) {
    try {
      const params = memberName ? { member_name: memberName } : {};
      const response = await api.get(
        `/documentupload/get-document-preview/${email}/${docType}`,
        { params }
      );
      return response.data;
    } catch (error) {
      throw this.handleError(error);
    }
  }

  /**
   * Download document
   */
  async downloadDocument(email, docType, memberName = null) {
    try {
      const params = memberName ? { member_name: memberName } : {};
      const response = await api.get(
        `/documentupload/download-document/${email}/${docType}`,
        {
          params,
          responseType: 'blob',
        }
      );
      return response.data;
    } catch (error) {
      throw this.handleError(error);
    }
  }

  /**
   * Get member list (for partnerships)
   */
  async getMemberList(email) {
    try {
      const response = await api.get(`/documentupload/member-list/${email}`);
      return response.data;
    } catch (error) {
      throw this.handleError(error);
    }
  }

  /**
   * Check confirmation status
   */
  async checkConfirmation(email) {
    try {
      const response = await api.get(
        `/documentupload/check-confirmation-status/${email}`
      );
      return response.data;
    } catch (error) {
      throw this.handleError(error);
    }
  }

  /**
   * Send completion email (final validation)
   */
  async sendCompletionEmail(email) {
    try {
      const response = await api.post('/documentupload/send-completion-email', {
        email,
      });
      return response.data;
    } catch (error) {
      throw this.handleError(error);
    }
  }

  /**
   * Handle API errors
   */
  handleError(error) {
    if (error.response) {
      return error.response.data.detail || error.response.data.message || 'An error occurred';
    } else if (error.request) {
      return 'No response from server. Please check your connection.';
    } else {
      return error.message || 'An unexpected error occurred';
    }
  }
}

export default new DocumentService();