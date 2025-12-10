// frontend/src/pages/Dashboard.jsx

import React, { useState, useEffect, useCallback } from 'react';
import { BarChart, Bar, PieChart, Pie, Cell, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { useAuth } from '../context/AuthContext';
import Sidebar from '../components/layout/Sidebar';
import AdminPasswordModal from '../components/common/AdminPasswordModal';
import { 
  Users, 
  CheckCircle, 
  Clock, 
  Calendar,
  TrendingUp,
  RefreshCw,
  Download
} from 'lucide-react';
import api from '../services/api';
import toast from 'react-hot-toast';

const COLORS = ['#3B82F6', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899'];

const Dashboard = () => {
  const { user } = useAuth();
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [showPasswordModal, setShowPasswordModal] = useState(true);
  // Removed isCollapsed state - sidebar is now fixed width
  
  const [metrics, setMetrics] = useState({
    totalUsers: 0,
    verifiedUsers: 0,
    pendingUsers: 0,
    registeredToday: 0,
    registeredThisWeek: 0
  });
  
  const [users, setUsers] = useState([]);
  const [accountTypeData, setAccountTypeData] = useState([]);
  const [onboardingData, setOnboardingData] = useState([]);
  
  const [systemStatus, setSystemStatus] = useState({
    backendOnline: true,
    databaseConnected: true,
    lastUpdated: ''
  });
  
  const [isLoading, setIsLoading] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');

  // Handle admin password submission
  const handleAdminPasswordSubmit = (password) => {
    if (password === 'Admin@123') {
      setIsAuthenticated(true);
      setShowPasswordModal(false);
      toast.success('Admin access granted!');
    } else {
      toast.error('Incorrect password');
    }
  };

  // Fetch all dashboard data
  const fetchDashboardData = useCallback(async () => {
    try {
      setIsLoading(true);

      const [
        totalRes,
        verifiedRes,
        pendingRes,
        todayRes,
        weekRes,
        usersRes,
        accountTypesRes,
        onboardingRes
      ] = await Promise.all([
        api.get('/register/get-total-users'),
        api.get('/register/get-verified-users-count'),
        api.get('/register/get-pending-verification-count'),
        api.get('/register/registered-today'),
        api.get('/register/regisetered-this-week'),
        api.get('/register/list-users'),
        api.get('/register/account-type-summary'),
        api.get('/register/onboarding-summary')
      ]);

      setMetrics({
        totalUsers: totalRes.data.total_users || 0,
        verifiedUsers: verifiedRes.data.verified_users_count || 0,
        pendingUsers: pendingRes.data.pending_verification_count || 0,
        registeredToday: todayRes.data.users_registered_today || 0,
        registeredThisWeek: weekRes.data.users_registered_this_week || 0
      });

      setUsers(usersRes.data.users || []);
      setAccountTypeData(accountTypesRes.data.account_types || []);
      setOnboardingData(onboardingRes.data.onboarding_steps || []);

      setSystemStatus({
        backendOnline: true,
        databaseConnected: true,
        lastUpdated: new Date().toLocaleTimeString()
      });

      toast.success('Dashboard data refreshed');
    } catch (error) {
      console.error('Error fetching dashboard data:', error);
      toast.error('Failed to load dashboard data');
      setSystemStatus(prev => ({
        ...prev,
        backendOnline: false,
        lastUpdated: new Date().toLocaleTimeString()
      }));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isAuthenticated) {
      fetchDashboardData();
    }
  }, [fetchDashboardData, isAuthenticated]);

  // Filter users based on search
  const filteredUsers = users.filter(u =>
    u.name?.toLowerCase().includes(searchTerm.toLowerCase()) ||
    u.email?.toLowerCase().includes(searchTerm.toLowerCase()) ||
    u.account_type?.toLowerCase().includes(searchTerm.toLowerCase())
  );

  // Export to CSV
  const exportToCSV = () => {
    const headers = ['Name', 'Email', 'Account Type', 'Status', 'Registered Date'];
    const rows = users.map(u => [
      u.name || '',
      u.email || '',
      u.account_type || 'N/A',
      u.onboarding_step === 'verification_complete' ? 'Verified' : 'Pending',
      new Date(u.created_at).toLocaleDateString()
    ]);

    const csvContent = [
      headers.join(','),
      ...rows.map(row => row.join(','))
    ].join('\n');

    const blob = new Blob([csvContent], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `thrivv_users_${new Date().toISOString().split('T')[0]}.csv`;
    a.click();
    toast.success('CSV exported successfully');
  };

  return (
    <div className="flex h-screen bg-gradient-to-br from-gray-50 to-gray-100">
      {/* Admin Password Modal */}
      {showPasswordModal && !isAuthenticated && (
        <AdminPasswordModal 
          onSubmit={handleAdminPasswordSubmit}
          onClose={null}
        />
      )}

      {/* Sidebar */}
      <Sidebar />

      {/* Main Content - Fixed margin for sidebar */}
      <div className="flex-1 ml-64 overflow-y-auto"
      >
        <div className="p-8">
          {/* Header */}
          <div className="mb-8">
            <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
              <div>
                <h1 className="text-3xl font-bold text-gray-800">Admin Dashboard</h1>
                <p className="text-gray-600 mt-2">Welcome back, {user?.name || 'Admin'}!</p>
              </div>
              <div className="flex gap-3">
                <button
                  onClick={exportToCSV}
                  disabled={users.length === 0}
                  className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors shadow-lg disabled:opacity-50"
                >
                  <Download className="h-5 w-5" />
                  Export CSV
                </button>
                <button
                  onClick={fetchDashboardData}
                  disabled={isLoading}
                  className="flex items-center gap-2 px-6 py-2 bg-gradient-to-r from-purple-600 to-indigo-600 text-white rounded-lg hover:opacity-90 transition-opacity shadow-lg disabled:opacity-50"
                >
                  <RefreshCw className={`h-5 w-5 ${isLoading ? 'animate-spin' : ''}`} />
                  {isLoading ? 'Refreshing...' : 'Refresh'}
                </button>
              </div>
            </div>
          </div>

          {/* Metrics Cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4 mb-6">
            <div className="bg-gradient-to-br from-blue-500 to-indigo-600 text-white rounded-xl p-6 shadow-lg hover:shadow-xl transition-shadow">
              <div className="flex items-center justify-between mb-3">
                <span className="text-sm font-medium opacity-90">Total Users</span>
                <Users className="h-8 w-8 opacity-75" />
              </div>
              <div className="text-3xl font-bold mb-1">{metrics.totalUsers}</div>
              <div className="text-xs opacity-75">All registered users</div>
            </div>

            <div className="bg-gradient-to-br from-green-500 to-emerald-600 text-white rounded-xl p-6 shadow-lg hover:shadow-xl transition-shadow">
              <div className="flex items-center justify-between mb-3">
                <span className="text-sm font-medium opacity-90">Verified</span>
                <CheckCircle className="h-8 w-8 opacity-75" />
              </div>
              <div className="text-3xl font-bold mb-1">{metrics.verifiedUsers}</div>
              <div className="text-xs opacity-75">Onboarding complete</div>
            </div>

            <div className="bg-gradient-to-br from-yellow-500 to-orange-500 text-white rounded-xl p-6 shadow-lg hover:shadow-xl transition-shadow">
              <div className="flex items-center justify-between mb-3">
                <span className="text-sm font-medium opacity-90">Pending</span>
                <Clock className="h-8 w-8 opacity-75" />
              </div>
              <div className="text-3xl font-bold mb-1">{metrics.pendingUsers}</div>
              <div className="text-xs opacity-75">In verification</div>
            </div>

            <div className="bg-gradient-to-br from-cyan-500 to-teal-600 text-white rounded-xl p-6 shadow-lg hover:shadow-xl transition-shadow">
              <div className="flex items-center justify-between mb-3">
                <span className="text-sm font-medium opacity-90">Today</span>
                <Calendar className="h-8 w-8 opacity-75" />
              </div>
              <div className="text-3xl font-bold mb-1">{metrics.registeredToday}</div>
              <div className="text-xs opacity-75">New registrations</div>
            </div>

            <div className="bg-gradient-to-br from-purple-500 to-pink-600 text-white rounded-xl p-6 shadow-lg hover:shadow-xl transition-shadow">
              <div className="flex items-center justify-between mb-3">
                <span className="text-sm font-medium opacity-90">This Week</span>
                <TrendingUp className="h-8 w-8 opacity-75" />
              </div>
              <div className="text-3xl font-bold mb-1">{metrics.registeredThisWeek}</div>
              <div className="text-xs opacity-75">Weekly growth</div>
            </div>
          </div>

          {/* Charts */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
            {/* Account Type Chart */}
            <div className="bg-white rounded-xl shadow-lg p-6 hover:shadow-xl transition-shadow">
              <h2 className="text-lg font-bold text-gray-800 mb-4">📈 Account Type Distribution</h2>
              {accountTypeData.length > 0 ? (
                <ResponsiveContainer width="100%" height={280}>
                  <PieChart>
                    <Pie
                      data={accountTypeData}
                      cx="50%"
                      cy="50%"
                      labelLine={false}
                      label={entry => `${entry.name}: ${entry.count}`}
                      outerRadius={90}
                      fill="#8884d8"
                      dataKey="count"
                    >
                      {accountTypeData.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip />
                  </PieChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-64 flex flex-col items-center justify-center text-gray-400">
                  <div className="text-5xl mb-3">📊</div>
                  <p>No data available</p>
                </div>
              )}
            </div>

            {/* Onboarding Status Chart */}
            <div className="bg-white rounded-xl shadow-lg p-6 hover:shadow-xl transition-shadow">
              <h2 className="text-lg font-bold text-gray-800 mb-4">📉 Onboarding Status</h2>
              {onboardingData.length > 0 ? (
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart data={onboardingData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                    <XAxis dataKey="step" tick={{ fontSize: 12 }} />
                    <YAxis />
                    <Tooltip />
                    <Legend />
                    <Bar dataKey="count" fill="#8B5CF6" radius={[8, 8, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-64 flex flex-col items-center justify-center text-gray-400">
                  <div className="text-5xl mb-3">📊</div>
                  <p>No data available</p>
                </div>
              )}
            </div>
          </div>

          {/* Users Table */}
          <div className="bg-white rounded-xl shadow-lg p-6 mb-6">
            <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 mb-4">
              <h2 className="text-lg font-bold text-gray-800">👥 Recent Users</h2>
              <input
                type="text"
                placeholder="Search users..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent"
              />
            </div>
            
            {filteredUsers.length === 0 ? (
              <div className="text-center py-12">
                <Users className="h-16 w-16 text-gray-300 mx-auto mb-4" />
                <p className="text-gray-500">No users found</p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-gray-200">
                      <th className="text-left p-4 text-gray-600 font-semibold">Name</th>
                      <th className="text-left p-4 text-gray-600 font-semibold">Email</th>
                      <th className="text-left p-4 text-gray-600 font-semibold">Account Type</th>
                      <th className="text-left p-4 text-gray-600 font-semibold">Status</th>
                      <th className="text-left p-4 text-gray-600 font-semibold">Registered</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredUsers.map((u) => (
                      <tr key={u.id} className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
                        <td className="p-4 font-medium text-gray-800">{u.name || '—'}</td>
                        <td className="p-4 text-gray-600">{u.email}</td>
                        <td className="p-4">
                          <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-bold bg-blue-100 text-blue-700">
                            {u.account_type || 'N/A'}
                          </span>
                        </td>
                        <td className="p-4">
                          <span className={`inline-flex items-center px-3 py-1 rounded-full text-xs font-bold ${
                            u.onboarding_step === 'verification_complete' 
                              ? 'bg-green-100 text-green-700' 
                              : 'bg-yellow-100 text-yellow-700'
                          }`}>
                            {u.onboarding_step === 'verification_complete' ? '✓ Verified' : '⏳ Pending'}
                          </span>
                        </td>
                        <td className="p-4 text-gray-600">{new Date(u.created_at).toLocaleDateString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* System Status and Quick Stats */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* System Status */}
            <div className="bg-white rounded-xl shadow-lg p-6">
              <h2 className="text-lg font-bold text-gray-800 mb-4">⚙️ System Status</h2>
              <div className="space-y-3">
                <div className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                  <span className="text-gray-700 font-medium">Backend API</span>
                  <span className={`inline-flex items-center px-3 py-1 rounded-full text-xs font-bold ${
                    systemStatus.backendOnline ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
                  }`}>
                    {systemStatus.backendOnline ? '✅ Online' : '❌ Offline'}
                  </span>
                </div>
                <div className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                  <span className="text-gray-700 font-medium">Database</span>
                  <span className={`inline-flex items-center px-3 py-1 rounded-full text-xs font-bold ${
                    systemStatus.databaseConnected ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
                  }`}>
                    {systemStatus.databaseConnected ? '✅ Connected' : '❌ Disconnected'}
                  </span>
                </div>
                <div className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                  <span className="text-gray-700 font-medium">Last Updated</span>
                  <span className="text-gray-600 font-medium">{systemStatus.lastUpdated || '—'}</span>
                </div>
              </div>
            </div>

            {/* Quick Stats */}
            <div className="bg-white rounded-xl shadow-lg p-6">
              <h2 className="text-lg font-bold text-gray-800 mb-4">📊 Quick Stats</h2>
              <div className="space-y-3">
                <div className="flex items-center justify-between p-3 bg-gradient-to-r from-blue-50 to-indigo-50 rounded-lg">
                  <span className="text-gray-700 font-medium">Total Users</span>
                  <span className="text-2xl font-bold text-blue-600">{metrics.totalUsers}</span>
                </div>
                <div className="flex items-center justify-between p-3 bg-gradient-to-r from-green-50 to-emerald-50 rounded-lg">
                  <span className="text-gray-700 font-medium">Verified Users</span>
                  <span className="text-2xl font-bold text-green-600">{metrics.verifiedUsers}</span>
                </div>
                <div className="flex items-center justify-between p-3 bg-gradient-to-r from-yellow-50 to-orange-50 rounded-lg">
                  <span className="text-gray-700 font-medium">Pending Verification</span>
                  <span className="text-2xl font-bold text-yellow-600">{metrics.pendingUsers}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;