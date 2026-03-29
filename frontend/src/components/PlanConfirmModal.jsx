import React from 'react';
import { ClipboardList, ShieldCheck } from 'lucide-react';

export default function PlanConfirmModal({ planEvent, onConfirm, onCancel }) {
  if (!planEvent || !planEvent.data || !planEvent.data.steps) return null;

  const steps = planEvent.data.steps;

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
        maxWidth: '560px',
        maxHeight: '80vh',
        display: 'flex',
        flexDirection: 'column',
        padding: '32px',
        background: 'var(--bg-surface)',
        border: '1px solid rgba(16, 185, 129, 0.3)', // Green successish border
        boxShadow: '0 20px 40px rgba(0,0,0,0.5)'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '8px', color: 'var(--primary)' }}>
          <ClipboardList size={28} />
          <h2 style={{ fontSize: '1.25rem', color: 'var(--text-main)', margin: 0 }}>Review Task Plan</h2>
        </div>
        
        <p style={{ color: 'var(--text-muted)', marginBottom: '20px', fontSize: '0.9rem' }}>
          Oliv AI has generated the following steps to complete your goal. Please review and confirm before execution.
        </p>

        <div style={{ 
          background: 'var(--bg-dark)', 
          padding: '16px', 
          borderRadius: '8px',
          marginBottom: '24px',
          border: '1px solid var(--border-color)',
          overflowY: 'auto',
          flex: 1
        }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {steps.map((step, index) => (
              <div key={index} style={{ display: 'flex', gap: '12px' }}>
                <div style={{ 
                  background: 'var(--bg-surface-elevated)', 
                  color: 'var(--primary)',
                  width: '24px', height: '24px', 
                  borderRadius: '50%', 
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: '0.8rem', fontWeight: 'bold', flexShrink: 0
                }}>
                  {index + 1}
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ color: 'var(--text-main)', fontWeight: 600, fontSize: '0.95rem' }}>
                    {step.tool}
                  </div>
                  <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem', marginTop: '2px', lineHeight: 1.4 }}>
                    {step.reason}
                  </div>
                  {Object.keys(step.args || {}).length > 0 && (
                    <div style={{ 
                      marginTop: '6px', 
                      background: 'rgba(0,0,0,0.2)', 
                      padding: '8px', 
                      borderRadius: '4px',
                      fontFamily: 'monospace', fontSize: '0.8rem',
                      color: 'var(--text-muted)',
                      wordBreak: 'break-all'
                    }}>
                      {JSON.stringify(step.args)}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
        
        <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginBottom: '24px', display: 'flex', gap: '8px', alignItems: 'center' }}>
          <ShieldCheck size={16} color="var(--success)" />
          <span>You can stop the task at any time using the Stop button on the dashboard.</span>
        </div>

        <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end', marginTop: 'auto' }}>
          <button 
            className="btn btn-secondary" 
            onClick={onCancel}
            style={{ padding: '10px 24px' }}
          >
            Cancel Task
          </button>
          <button 
            className="btn btn-primary" 
            onClick={onConfirm}
            style={{ padding: '10px 24px', display: 'flex', alignItems: 'center', gap: '8px' }}
          >
            Run Plan
          </button>
        </div>
      </div>
    </div>
  );
}
