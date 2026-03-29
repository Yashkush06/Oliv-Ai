import React from 'react';
import { CheckCircle2, Circle, AlertCircle, Loader2 } from 'lucide-react';

export default function StepProgress({ steps, currentStep, status }) {
  if (!steps || steps.length === 0) return null;

  return (
    <div style={{
      padding: '20px',
      background: 'var(--bg-surface)',
      borderRadius: '12px',
      border: '1px solid var(--border-color)',
      marginTop: '20px'
    }}>
      <h3 style={{ fontSize: '0.9rem', color: 'var(--text-muted)', marginBottom: '16px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
        Execution Plan
      </h3>
      
      <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        {steps.map((step, idx) => {
          const stepNum = idx + 1;
          const isPast = stepNum < currentStep;
          const isCurrent = stepNum === currentStep;
          const isFuture = stepNum > currentStep;
          
          let Icon = Circle;
          let color = 'var(--text-muted)';
          
          if (isPast) {
            Icon = CheckCircle2;
            color = 'var(--success)';
          } else if (isCurrent) {
            if (status === 'error' || status === 'failure') {
              Icon = AlertCircle;
              color = 'var(--error)';
            } else if (status === 'pending') {
              Icon = Loader2;
              color = 'var(--warning)';
            } else {
              Icon = CheckCircle2;
              color = 'var(--primary)';
            }
          }

          return (
            <div key={idx} style={{ display: 'flex', gap: '12px', opacity: isFuture ? 0.5 : 1 }}>
              <div style={{ marginTop: '2px' }}>
                <Icon 
                  size={18} 
                  color={color} 
                  className={isCurrent && status === 'pending' ? 'animate-spin' : ''} 
                />
              </div>
              <div>
                <div style={{ 
                  fontWeight: 500, 
                  color: isCurrent ? 'var(--text-main)' : 'var(--text-muted)',
                  fontSize: '0.95rem'
                }}>
                  {step.tool || 'Action'}
                </div>
                <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginTop: '4px' }}>
                  {step.reason || step.message || JSON.stringify(step.args || {})}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
