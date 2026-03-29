import React, { useState, useEffect } from 'react';
import { useApi } from '../hooks/useApi';
import { Activity } from 'lucide-react';

export default function ActivityLog() {
  const { request } = useApi();
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchLogs();
    const interval = setInterval(fetchLogs, 5000);
    return () => clearInterval(interval);
  }, []);

  const fetchLogs = async () => {
    try {
      const res = await request('GET', '/logs?last_n=100');
      setLogs(res.logs || []);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const getLogColor = (level) => {
    switch(level) {
      case 'error': return 'var(--error)';
      case 'warning': return 'var(--warning)';
      case 'success': return 'var(--success)';
      default: return 'var(--text-main)';
    }
  };

  if (loading && logs.length === 0) return <div style={{ padding: '32px' }}>Loading logs...</div>;

  return (
    <div style={{ padding: '40px', maxWidth: '1000px', margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '32px' }}>
        <Activity size={28} color="var(--primary)" />
        <h1 style={{ fontSize: '1.8rem', fontWeight: 600, margin: 0 }}>System Logs</h1>
      </div>

      <div className="glass-panel" style={{ overflow: 'hidden' }}>
        <div style={{ background: 'var(--bg-surface-elevated)', padding: '16px', fontFamily: 'monospace', fontSize: '0.85rem', height: 'calc(100vh - 200px)', overflowY: 'auto' }}>
          {logs.map((log, i) => (
            <div key={i} style={{ 
              marginBottom: '8px', borderBottom: '1px solid var(--border-color)', paddingBottom: '8px',
              display: 'flex', gap: '16px'
            }}>
              <div style={{ color: 'var(--text-muted)', minWidth: '180px' }}>
                {new Date(log.timestamp).toISOString().replace('T', ' ').substring(0, 19)}
              </div>
              <div style={{ color: getLogColor(log.level), minWidth: '80px', textTransform: 'uppercase' }}>
                [{log.level}]
              </div>
              <div style={{ color: 'var(--text-main)', flex: 1 }}>
                {log.message}
                {log.data && Object.keys(log.data).length > 0 && (
                  <div style={{ marginTop: '8px', color: 'var(--text-muted)', fontSize: '0.8rem', whiteSpace: 'pre-wrap' }}>
                    {JSON.stringify(log.data, null, 2)}
                  </div>
                )}
              </div>
            </div>
          ))}
          {logs.length === 0 && <div style={{ color: 'var(--text-muted)' }}>No logs recorded yet.</div>}
        </div>
      </div>
    </div>
  );
}
