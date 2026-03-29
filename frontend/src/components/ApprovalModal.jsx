import React from 'react';
import { AlertTriangle, ShieldCheck } from 'lucide-react';

export default function ApprovalModal({ event, onConfirm, onDeny }) {
  if (!event) return null;

  return (
    <div style={{
      position: 'fixed',
      top: 0, left: 0, right: 0, bottom: 0,
      background: 'rgba(0,0,0,0.8)',
      backdropFilter: 'blur(4px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 9999,
    }}>
      <div className="glass-panel" style={{
        width: '100%',
        maxWidth: '480px',
        padding: '32px',
        background: 'var(--bg-surface)',
        border: '1px solid rgba(245, 158, 11, 0.3)', // Warning border
        boxShadow: '0 20px 40px rgba(0,0,0,0.5)'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '20px', color: 'var(--warning)' }}>
          <AlertTriangle size={28} />
          <h2 style={{ fontSize: '1.25rem', color: 'var(--text-main)', margin: 0 }}>Approval Required</h2>
        </div>
        
        <p style={{ color: 'var(--text-muted)', marginBottom: '24px' }}>
          Oliv AI needs your permission to execute the following action:
        </p>
        
        <div style={{ 
          background: 'var(--bg-surface)', 
          padding: '16px', 
          borderRadius: '8px',
          marginBottom: '24px',
          border: '1px solid var(--border-color)',
          fontFamily: 'monospace',
          fontSize: '0.9rem'
        }}>
          <div style={{ color: 'var(--primary)', fontWeight: 'bold', marginBottom: '8px' }}>
            {event.tool}
          </div>
          <div style={{ color: 'var(--text-muted)' }}>
            {JSON.stringify(event.args, null, 2)}
          </div>
        </div>
        
        <div style={{ fontSize: '0.9rem', color: 'var(--text-main)', marginBottom: '32px', display: 'flex', gap: '8px', alignItems: 'center' }}>
          <ShieldCheck size={16} color="var(--success)" />
          <span>Reason: {event.message.replace('Confirm action: ', '')}</span>
        </div>

        <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end' }}>
          <button 
            className="btn btn-secondary" 
            onClick={onDeny}
            style={{ padding: '10px 24px' }}
          >
            Deny
          </button>
          <button 
            className="btn btn-primary" 
            onClick={onConfirm}
            style={{ background: 'var(--warning)', padding: '10px 24px' }}
          >
            Allow Action
          </button>
        </div>
      </div>
    </div>
  );
}
