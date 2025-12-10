// frontend/src/services/auth.service.js

import api from './api';

class AuthService {
  async login(email, password) {
    try {
      const response = await api.post('/auth/login', {
        email,
        password,
      });

      if (response.data.access_token) {
        const userData = {
          token: response.data.access_token,
          email: response.data.email,
          name: response.data.name,
          role: response.data.role || 'user',
        };

        localStorage.setItem('user', JSON.stringify(userData));
        return { success: true, user: userData };
      }

      return { success: false, error: 'Invalid response from server' };
    } catch (error) {
      console.error('Login error:', error);
      return {
        success: false,
        error: error.response?.data?.detail || 'Login failed',
      };
    }
  }

  async signup(userData) {
    try {
      const response = await api.post('/auth/signup', userData);

      if (response.data) {
        return {
          success: true,
          message: response.data.message || 'Account created successfully',
        };
      }

      return { success: false, error: 'Invalid response from server' };
    } catch (error) {
      console.error('Signup error:', error);
      return {
        success: false,
        error: error.response?.data?.detail || 'Signup failed',
      };
    }
  }

  logout() {
    localStorage.removeItem('user');
  }

  getCurrentUser() {
    try {
      const userStr = localStorage.getItem('user');
      if (userStr) {
        const user = JSON.parse(userStr);
        
        // Check if token exists
        if (user.token) {
          return user;
        }
      }
      return null;
    } catch (error) {
      console.error('Error getting current user:', error);
      return null;
    }
  }

  getToken() {
    const user = this.getCurrentUser();
    return user?.token || null;
  }

  isAuthenticated() {
    const user = this.getCurrentUser();
    return !!user && !!user.token;
  }

  isAdmin() {
    const user = this.getCurrentUser();
    return user?.role === 'admin';
  }

  updateUser(userData) {
    try {
      const currentUser = this.getCurrentUser();
      if (currentUser) {
        const updatedUser = { ...currentUser, ...userData };
        localStorage.setItem('user', JSON.stringify(updatedUser));
        return updatedUser;
      }
      return null;
    } catch (error) {
      console.error('Error updating user:', error);
      return null;
    }
  }

  async refreshToken() {
    try {
      const response = await api.post('/auth/refresh');
      
      if (response.data.access_token) {
        const currentUser = this.getCurrentUser();
        if (currentUser) {
          currentUser.token = response.data.access_token;
          localStorage.setItem('user', JSON.stringify(currentUser));
          return { success: true, token: response.data.access_token };
        }
      }
      
      return { success: false, error: 'No current user found' };
    } catch (error) {
      console.error('Token refresh error:', error);
      return {
        success: false,
        error: error.response?.data?.detail || 'Token refresh failed',
      };
    }
  }

  async verifyToken() {
    try {
      const response = await api.get('/auth/verify');
      return { success: true, data: response.data };
    } catch (error) {
      console.error('Token verification error:', error);
      return { success: false, error: 'Token verification failed' };
    }
  }

  clearAllData() {
    localStorage.clear();
    sessionStorage.clear();
  }
}

const authService = new AuthService();
export default authService;