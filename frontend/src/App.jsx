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
          background: 'linear-gradient(135deg, var(--primary), #d946ef)',
          borderRadius: '8px',
          boxShadow: '0 0 15px var(--primary-glow)'
        }}></div>
        <h1 style={{ fontSize: '1.2rem', fontWeight: 600, letterSpacing: '-0.5px' }}>Oliv AI</h1>
      </div>

      {links.map(({ path, label, icon: Icon }) => (
        <button
          key={path}
          onClick={() => navigate(path)}
          style={{
            display: 'flex', alignItems: 'center', gap: '12px',
            padding: '12px',
            borderRadius: '8px',
            background: location.pathname === path ? 'rgba(255,255,255,0.1)' : 'transparent',
            color: location.pathname === path ? 'white' : 'var(--text-muted)',
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
    <div style={{ display: 'flex', minHeight: '100vh', background: 'var(--bg-dark)' }}>
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
