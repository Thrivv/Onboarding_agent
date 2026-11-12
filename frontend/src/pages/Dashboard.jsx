// frontend/src/pages/Dashboard.jsx

import React, { useState, useEffect, useCallback } from 'react';
import { BarChart, Bar, PieChart, Pie, Cell, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
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
import { getAccountTypeSummary, getBedrockStatus, getOnboardingSummary, getPendingVerificationCount, getRegisteredThisWeek, getRegisteredToday, getTotalUsers, getVerifiedUsersCount, listUsers } from '../api/auth';
import toast from 'react-hot-toast';
import logger from '../utils/logger';

const COLORS = ['#eea73b', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899'];

const Dashboard = () => {
  const [isAuthenticated, setIsAuthenticated] = useState(() => {
    return sessionStorage.getItem('admin_authenticated') === 'true';
  });
  const [showPasswordModal, setShowPasswordModal] = useState(() => {
    return sessionStorage.getItem('admin_authenticated') !== 'true';
  });

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
    bedrockConnected: null, // null = not checked yet ("checking...")
    lastUpdated: ''
  });

  const [isLoading, setIsLoading] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');

  // Handle admin password submission
  const handleAdminPasswordSubmit = (password) => {
    if (password === 'Admin@123') {
      setIsAuthenticated(true);
      setShowPasswordModal(false);
      sessionStorage.setItem('admin_authenticated', 'true');
      toast.success('Admin access granted!');
    } else {
      toast.error('Incorrect password');
    }
  };

  // Fetch all dashboard data
  // Independent of the main metrics fetch below on purpose: a slow or
  // unreachable Bedrock call must never block or fail the rest of the
  // dashboard (user counts, charts, etc.) from loading. See
  // backend/app/services/bedrock_client.py::check_connection for why this
  // real ping lives here rather than in the Docker-polled /health endpoint.
  const checkBedrockStatus = useCallback(async () => {
    try {
      const res = await getBedrockStatus();
      setSystemStatus(prev => ({
        ...prev,
        bedrockConnected: !!res.data.bedrock_connected
      }));
    } catch (error) {
      logger.error('Error checking Bedrock status:', error);
      setSystemStatus(prev => ({ ...prev, bedrockConnected: false }));
    }
  }, []);

  const fetchDashboardData = useCallback(async () => {
    try {
      setIsLoading(true);

      // Fire-and-forget — resolves independently, see checkBedrockStatus above.
      checkBedrockStatus();

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
        getTotalUsers(),
        getVerifiedUsersCount(),
        getPendingVerificationCount(),
        getRegisteredToday(),
        getRegisteredThisWeek(),
        listUsers(),
        getAccountTypeSummary(),
        getOnboardingSummary()
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
      logger.error('Error fetching dashboard data:', error);
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

  // ✅ UPDATED: Filter users based on search - NOW INCLUDES PHONE & COMPANY NAME
  const filteredUsers = users.filter(u =>
    u.name?.toLowerCase().includes(searchTerm.toLowerCase()) ||
    u.email?.toLowerCase().includes(searchTerm.toLowerCase()) ||
    u.phone_number?.toLowerCase().includes(searchTerm.toLowerCase()) ||
    u.business_name?.toLowerCase().includes(searchTerm.toLowerCase()) ||
    u.account_type?.toLowerCase().includes(searchTerm.toLowerCase())
  );

  // ✅ UPDATED: Export to CSV - CORRECT ORDER
  const exportToCSV = () => {
    const headers = ['User Name', 'Email Address', 'Phone Number', 'Company Name', 'Account Type', 'Status', 'Registered Date'];
    const rows = users.map(u => [
      u.name || '',
      u.email || '',
      u.phone_number || 'Not provided',
      u.business_name || 'Not provided',
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
    <div className="flex h-screen bg-[#F8FAFC] font-sans selection:bg-blue-100 selection:text-blue-900">
      {/* Admin Password Modal */}
      {showPasswordModal && !isAuthenticated && (
        <AdminPasswordModal
          onSubmit={handleAdminPasswordSubmit}
          onClose={null}
        />
      )}

      {/* Sidebar */}
      <Sidebar />

      {/* Main Content */}
      <div className="flex-1 ml-64 overflow-y-auto overflow-x-hidden custom-scrollbar">
        <div className="p-10 max-w-[1600px] mx-auto">
          {/* Header Section */}
          <div className="flex flex-col lg:flex-row lg:items-end justify-between gap-6 mb-12">
            <div>
              <div className="flex items-center gap-3 mb-2">
                <div className="w-2 h-8 bg-brand-primary rounded-full" />
                <h1 className="text-4xl font-black text-slate-900 tracking-tight">
                  Admin <span className="text-brand-primary">Console</span>
                </h1>
              </div>
              <p className="text-slate-600 font-medium text-lg ml-5">
                Monitoring onboarding velocity and security compliance.
              </p>
            </div>

            <div className="flex items-center gap-4 bg-white p-2 rounded-[22px] shadow-sm border border-slate-100 self-start lg:self-auto">
              <button
                onClick={exportToCSV}
                disabled={users.length === 0}
                className="flex items-center gap-2 px-6 py-3 bg-slate-900 text-white rounded-2xl hover:bg-slate-800 transition-all font-bold text-sm shadow-lg shadow-slate-200 disabled:opacity-50 group active:scale-95"
              >
                <Download className="h-4 w-4 group-hover:translate-y-0.5 transition-transform" />
                Export Data
              </button>
              <button
                onClick={fetchDashboardData}
                disabled={isLoading}
                className="flex items-center gap-2 px-6 py-3 bg-brand-primary rounded-2xl hover:bg-brand-secondary transition-all font-bold text-sm shadow-lg shadow-blue-200 disabled:opacity-50 group active:scale-95"
              >
                <RefreshCw className={`h-4 w-4 ${isLoading ? 'animate-spin' : 'group-hover:rotate-180 transition-transform duration-500'}`} />
                {isLoading ? '' : 'Sync Data'}
              </button>
            </div>
          </div>

          {/* Metrics Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-6 mb-12">
            {[
              // `iconClasses` holds COMPLETE literal class strings on purpose.
              // These used to be built as `bg-${stat.color}-50 text-${stat.color}-600`,
              // but Tailwind's JIT only generates classes it can see as literal
              // text in the source — it cannot resolve a template literal. Those
              // classes therefore existed only when the same string happened to
              // appear literally somewhere else in the app. 'sky' appeared
              // nowhere, so this card's icon rendered with no colour at all, and
              // the other four worked purely by coincidence.
              { label: 'Platform Users', value: metrics.totalUsers, icon: Users, iconClasses: 'bg-indigo-50 text-indigo-600', sub: 'Total growth' },
              { label: 'Verified Keys', value: metrics.verifiedUsers, icon: CheckCircle, iconClasses: 'bg-emerald-50 text-emerald-600', sub: 'Onboarded' },
              { label: 'Awaiting Help', value: metrics.pendingUsers, icon: Clock, iconClasses: 'bg-amber-50 text-amber-600', sub: 'Action needed' },
              { label: 'Today Signup', value: metrics.registeredToday, icon: Calendar, iconClasses: 'bg-sky-50 text-sky-600', sub: 'Daily velocity' },
              { label: 'Active Week', value: metrics.registeredThisWeek, icon: TrendingUp, iconClasses: 'bg-purple-50 text-purple-600', sub: 'W-o-W boost' },
            ].map((stat, i) => (
              <div key={i} className="bg-white rounded-[32px] p-7 shadow-sm border border-slate-100 hover:shadow-xl hover:-translate-y-1 transition-all duration-300">
                <div className={`w-12 h-12 rounded-2xl mb-6 flex items-center justify-center ${stat.iconClasses}`}>
                  <stat.icon size={24} strokeWidth={2.5} />
                </div>
                <div className="text-4xl font-black text-slate-900 mb-1 tracking-tight">{stat.value}</div>
                <div className="text-sm font-bold text-slate-500 uppercase tracking-widest">{stat.label}</div>
              </div>
            ))}
          </div>

          {/* Insight Charts */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 mb-12">
            <div className="lg:col-span-4 bg-white rounded-[36px] shadow-sm border border-slate-100 p-8 flex flex-col">
              <div className="flex items-center justify-between mb-8">
                <h2 className="text-xl font-black text-slate-900 tracking-tight">Account Split</h2>
                <div className="p-2 bg-slate-50 rounded-xl">
                  <TrendingUp size={18} className="text-brand-primary" />
                </div>
              </div>
              <div className="flex-1 min-h-[300px]">
                {accountTypeData.length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={accountTypeData}
                        innerRadius={70}
                        outerRadius={100}
                        paddingAngle={8}
                        dataKey="count"
                      >
                        {accountTypeData.map((e, index) => (
                          <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} cornerRadius={8} />
                        ))}
                      </Pie>
                      <Tooltip
                        contentStyle={{ borderRadius: '16px', border: 'none', boxShadow: '0 20px 25px -5px rgb(0 0 0 / 0.1)' }}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="h-full flex items-center justify-center text-slate-300 italic text-sm">No data available</div>
                )}
              </div>
            </div>

            <div className="lg:col-span-8 bg-white rounded-[36px] shadow-sm border border-slate-100 p-8">
              <div className="flex items-center justify-between mb-8">
                <h2 className="text-xl font-black text-slate-900 tracking-tight">Onboarding Funnel</h2>
                <select className="bg-slate-50 border-none text-[12px] font-bold text-slate-500 rounded-xl px-4 py-2 focus:ring-0">
                  <option>Last 30 Days</option>
                  <option>Last 7 Days</option>
                </select>
              </div>
              <div className="h-[300px]">
                {onboardingData.length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={onboardingData} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#E2E8F0" />
                      <XAxis dataKey="step" axisLine={false} tickLine={false} tick={{ fontSize: 11, fontWeight: 700, fill: '#64748B' }} />
                      <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 11, fontWeight: 700, fill: '#64748B' }} />
                      <Tooltip cursor={{ fill: '#F1F5F9' }} contentStyle={{ borderRadius: '16px', border: 'none', boxShadow: '0 20px 25px -5px rgb(0 0 0 / 0.1)' }} />
                      <Bar dataKey="count" fill="#4F46E5" radius={[10, 10, 0, 0]} barSize={40} />
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="h-full flex items-center justify-center text-slate-500 italic text-sm font-medium">No funnel data available</div>
                )}
              </div>
            </div>
          </div>

          {/* User Directory Table */}
          <div className="bg-white rounded-[40px] shadow-sm border border-slate-100 p-10 mb-12">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 mb-10">
              <div>
                <h2 className="text-2xl font-black text-slate-900 tracking-tight mb-1">User Directory</h2>
                <p className="text-slate-500 font-bold text-sm">Managing {filteredUsers.length} total active registrations</p>
              </div>
              <div className="relative group min-w-[320px]">
                <input
                  type="text"
                  placeholder="Search by name, email, or company..."
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  className="w-full pl-12 pr-6 py-4 bg-slate-50 border border-transparent rounded-[20px] outline-none focus:bg-white focus:border-blue-500 focus:ring-4 focus:ring-indigo-50 transition-all font-medium text-sm"
                />
                <Users className="absolute left-5 top-1/2 -translate-y-1/2 h-5 w-5 text-slate-400 group-focus-within:text-brand-primary" />
              </div>
            </div>

            <div className="overflow-x-auto -mx-10 px-10">
              <table className="w-full border-separate border-spacing-y-4">
                <thead>
                  <tr className="text-left font-bold text-slate-600 text-xs uppercase tracking-[0.15em]">
                    <th className="pb-4 px-6">Identity</th>
                    <th className="pb-4 px-6">Organization</th>
                    <th className="pb-4 px-6">Account Plan</th>
                    <th className="pb-4 px-6">Progress</th>
                    <th className="pb-4 px-6">Enrolled</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredUsers.map((u) => (
                    <tr key={u.id} className="group hover:bg-slate-50 transition-colors">
                      <td className="bg-slate-50 group-hover:bg-transparent transition-colors py-5 px-6 rounded-l-[24px]">
                        <div className="flex items-center gap-4">
                          <div className="w-12 h-12 rounded-[18px] bg-white border border-slate-100 flex items-center justify-center text-brand-primary font-black shadow-sm">
                            {(u.name || u.email)[0].toUpperCase()}
                          </div>
                          <div>
                            <div className="font-black text-slate-900 text-sm whitespace-nowrap">{u.name || 'Anonymous'}</div>
                            <div className="text-xs font-bold text-slate-500 whitespace-nowrap">{u.email}</div>
                          </div>
                        </div>
                      </td>
                      <td className="bg-slate-50 group-hover:bg-transparent transition-colors px-6">
                        <div className="font-bold text-slate-600 text-sm">{u.business_name || 'Individual'}</div>
                        <div className="text-[10px] font-black text-slate-500 uppercase tracking-widest">{u.phone_number || '--'}</div>
                      </td>
                      <td className="bg-slate-50 group-hover:bg-transparent transition-colors px-6">
                        <span className="inline-flex px-3 py-1.5 rounded-xl bg-white text-brand-secondary text-[10px] font-black uppercase tracking-widest border border-indigo-50 shadow-sm">
                          {u.account_type}
                        </span>
                      </td>
                      <td className="bg-slate-50 group-hover:bg-transparent transition-colors px-6">
                        <span className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-[10px] font-black uppercase tracking-widest ${u.onboarding_step === 'verification_complete'
                            ? 'bg-emerald-50 text-emerald-700 border border-emerald-100'
                            : 'bg-amber-50 text-amber-700 border border-amber-100'
                          }`}>
                          {u.onboarding_step === 'verification_complete' ? <CheckCircle size={12} /> : <Clock size={12} />}
                          {u.onboarding_step === 'verification_complete' ? 'Completed' : 'Pending'}
                        </span>
                      </td>
                      <td className="bg-slate-50 group-hover:bg-transparent transition-colors px-6 rounded-r-[24px]">
                        <div className="text-xs font-bold text-slate-600 whitespace-nowrap">
                          {new Date(u.created_at).toLocaleDateString('en-US', { day: 'numeric', month: 'short', year: 'numeric' })}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* System & Global Stats Footer */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 mb-12">
            <div className="bg-slate-900 rounded-[40px] p-10 text-white relative overflow-hidden shadow-2xl shadow-slate-200">
              <div className="absolute top-0 right-0 w-64 h-64 bg-brand-primary rounded-full blur-[120px] opacity-20 -mr-32 -mt-32" />
              <h3 className="text-2xl font-black mb-8 relative z-10 tracking-tight">System Infrastructure</h3>
              <div className="space-y-4 relative z-10">
                {[
                  { label: 'API Gateway', status: systemStatus.backendOnline, text: 'Active & Scaling' },
                  { label: 'Database Cluster', status: systemStatus.databaseConnected, text: 'Transactional' },
                  {
                    label: 'AWS Bedrock (Claude Haiku)',
                    status: systemStatus.bedrockConnected,
                    text: systemStatus.bedrockConnected === null
                      ? 'Checking...'
                      : systemStatus.bedrockConnected
                        ? 'Connected'
                        : 'Unreachable'
                  },
                ].map((s, i) => (
                  <div key={i} className="flex items-center justify-between p-5 bg-white/10 border border-white/20 rounded-2xl backdrop-blur-md">
                    <div>
                      <div className="text-xs font-bold text-slate-300 capitalize mb-1 tracking-wider">{s.label}</div>
                      <div className="text-base font-black text-white">{s.text}</div>
                    </div>
                    <div className={`w-3.5 h-3.5 rounded-full ${s.status === null ? 'bg-slate-400 animate-pulse' : s.status ? 'bg-emerald-400 shadow-[0_0_15px_rgba(52,211,153,0.6)]' : 'bg-red-500'}`} />
                  </div>
                ))}
                <div className="pt-4 text-[10px] font-bold text-slate-400 uppercase tracking-widest text-center">
                  Last Updated: {systemStatus.lastUpdated || 'Initial Session'}
                </div>
              </div>
            </div>

            <div className="bg-brand-primary rounded-[40px] p-10 text-white shadow-2xl shadow-blue-200 flex flex-col justify-between">
              <div>
                <h3 className="text-2xl font-black mb-1 tracking-tight">Growth Metrics</h3>
                <p className="text-blue-100 text-sm font-medium mb-10 opacity-75">Platform-wide aggregate insights.</p>
              </div>
              <div className="grid grid-cols-2 gap-4">
                {[
                  { label: 'Platform Users', val: metrics.totalUsers, p: '+12%', color: 'indigo' },
                  { label: 'Conversion Rate', val: '84%', p: '+3.2%', color: 'emerald' },
                ].map((m, i) => (
                  <div key={i} className="bg-white/10 p-6 rounded-[28px] border border-white/20 backdrop-blur-md">
                    <div className="text-[11px] font-black text-white/90 uppercase tracking-widest mb-3 border-b border-white/10 pb-2">{m.label}</div>
                    <div className="flex items-baseline gap-3">
                      <div className="text-4xl font-black text-white leading-none">{m.val}</div>
                      <div className="text-[12px] font-black text-emerald-300 px-2 py-0.5 bg-emerald-500/20 rounded-full">{m.p}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;