import { Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { Settings, Activity, LayoutDashboard } from 'lucide-react';

import { useApi } from './hooks/useApi';
import Dashboard from './pages/Dashboard';
import SetupWizard from './pages/SetupWizard';
import SettingsPage from './pages/Settings';
import ActivityLog from './pages/ActivityLog';

function Navigation() {
  const location = useLocation();
  const navigate = useNavigate();
  
  // Don't show nav during setup
  if (location.pathname === '/setup') return null;

  const links = [
    { path: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
    { path: '/logs', label: 'Activity Log', icon: Activity },
    { path: '/settings', label: 'Settings', icon: Settings },
  ];

  return (
    <nav style={{
      width: '240px',
      borderRight: '1px solid var(--border-color)',
      padding: '24px',
      display: 'flex',
      flexDirection: 'column',
      gap: '8px'
    }}>
      <div style={{ marginBottom: '32px', display: 'flex', alignItems: 'center', gap: '12px' }}>
        <div style={{ 
          width: '32px', height: '32px', 
          background: 'var(--primary)',
          borderRadius: '50%',
          boxShadow: '0 4px 10px var(--primary-glow)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '16px'
        }}>🫒</div>
        <h1 style={{ fontSize: '1.2rem', fontWeight: 700, letterSpacing: '-0.5px', color: 'var(--text-main)' }}>Oliv AI</h1>
      </div>

      {links.map(({ path, label, icon: Icon }) => (
        <button
          key={path}
          onClick={() => navigate(path)}
          style={{
            display: 'flex', alignItems: 'center', gap: '12px',
            padding: '12px',
            borderRadius: '8px',
            background: location.pathname === path ? 'var(--bg-surface)' : 'transparent',
            color: location.pathname === path ? 'var(--primary)' : 'var(--text-muted)',
            boxShadow: location.pathname === path ? '0 2px 8px rgba(0,0,0,0.05)' : 'none',
            fontWeight: location.pathname === path ? 600 : 500,
            border: 'none',
            cursor: 'pointer',
            textAlign: 'left',
            fontFamily: 'inherit',
            fontSize: '0.95rem',
            transition: 'all 0.2s'
          }}
        >
          <Icon size={18} />
          {label}
        </button>
      ))}
    </nav>
  );
}

export default function App() {
  const { request } = useApi();
  const [setupChecked, setSetupChecked] = useState(false);
  const [needsSetup, setNeedsSetup] = useState(false);

  useEffect(() => {
    request('GET', '/config/setup-status')
      .then(res => {
        setNeedsSetup(!res.setup_complete);
        setSetupChecked(true);
      })
      .catch(() => {
        // Assume needs setup if API fails
        setNeedsSetup(true);
        setSetupChecked(true);
      });
  }, [request]);

  if (!setupChecked) {
    return <div style={{ height: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>Loading...</div>;
  }

  return (
    <div style={{ display: 'flex', minHeight: '100vh', background: 'var(--bg-main)' }}>
      <Navigation />
      <main style={{ flex: 1, height: '100vh', overflowY: 'auto' }}>
        <Routes>
          <Route path="/" element={<Navigate to={needsSetup ? "/setup" : "/dashboard"} replace />} />
          <Route path="/setup" element={needsSetup ? <SetupWizard onComplete={() => setNeedsSetup(false)} /> : <Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={!needsSetup ? <Dashboard /> : <Navigate to="/setup" replace />} />
          <Route path="/settings" element={!needsSetup ? <SettingsPage /> : <Navigate to="/setup" replace />} />
          <Route path="/logs" element={!needsSetup ? <ActivityLog /> : <Navigate to="/setup" replace />} />
        </Routes>
      </main>
    </div>
  );
}
