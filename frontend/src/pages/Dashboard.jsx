import React, { useState, useEffect, useRef } from 'react';
import { Send, StopCircle, RefreshCcw, Command, Cpu, ThumbsUp, ThumbsDown } from 'lucide-react';
import { useApi } from '../hooks/useApi';
import { useWebSocket } from '../hooks/useWebSocket';

import StepProgress from '../components/StepProgress';
import ApprovalModal from '../components/ApprovalModal';
import PlanConfirmModal from '../components/PlanConfirmModal';

export default function Dashboard() {
  const { request } = useApi();
  const { messages, status: wsStatus, sendMessage } = useWebSocket('ws://localhost:8000/ws/stream');
  
  const [input, setInput] = useState('');
  const [isAgentRunning, setIsAgentRunning] = useState(false);
  const [agentStatus, setAgentStatus] = useState('idle'); // idle, planning, running, waiting, error, done
  const [historyLogs, setHistoryLogs] = useState([]);
  const [modelName, setModelName] = useState(null);
  
  const [currentTask, setCurrentTask] = useState({ id: null, steps: [], currentStep: 0 });
  const [pendingApproval, setPendingApproval] = useState(null);
  const [pendingPlanConfirm, setPendingPlanConfirm] = useState(null);
  const [pendingPrompt, setPendingPrompt] = useState(null);
  const [feedbackState, setFeedbackState] = useState({});
  
  const chatEndRef = useRef(null);
  const activityLogEndRef = useRef(null);

  // Poll for agent status & fetch initial logs on load
  useEffect(() => {
    request('GET', '/health').then(res => {
      if (res.agent?.running) {
        setIsAgentRunning(true);
        setAgentStatus('running');
      }
    }).catch(console.error);

    request('GET', '/logs?last_n=100').then(res => {
      setHistoryLogs(res.logs || []);
    }).catch(console.error);

    request('GET', '/config').then(res => {
      if (res.model_config) {
        const { provider, model } = res.model_config;
        if (provider && model) setModelName(`${provider} / ${model}`);
      }
    }).catch(console.error);
  }, [request]);

  const getLogColor = (level) => {
    switch(level) {
      case 'error': return 'var(--error)';
      case 'warning': return 'var(--warning)';
      case 'success': return 'var(--success)';
      default: return 'var(--text-main)';
    }
  };

  // Use live WS messages once streaming starts, fall back to history logs when idle.
  // This prevents duplication caused by the same events appearing in both sources.
  const allLogs = messages.filter(m => m.message || m.type === 'log').length > 0
    ? messages.filter(m => m.message || m.type === 'log')
    : historyLogs;

  // Handle incoming WS events
  useEffect(() => {
    if (!messages.length) return;

    const latest = messages[messages.length - 1];
    if (!latest.type) return;

    if (latest.type === 'log') {
      if (latest.message.includes('Parsing intent') || latest.message.includes('Generating')) {
        setAgentStatus('planning');
      }
      if (latest.total_steps > 0) {
        // Plan ready
        setCurrentTask(prev => ({ ...prev, totalSteps: latest.total_steps }));
      }
    }
    
    if (latest.type === 'step_start') {
      // Step_start means execution is actually happening now (after any plan confirm)
      setAgentStatus('running');
      setCurrentTask(prev => ({
        ...prev, 
        currentStep: latest.step,
        steps: prev.steps.length === prev.totalSteps ? prev.steps : [...prev.steps, { tool: latest.tool, args: latest.args, reason: latest.message }]
      }));
    }
    
    if (latest.type === 'plan_confirm') {
      setAgentStatus('waiting');
      setPendingPlanConfirm(latest);
      // Pre-fill steps for StepProgress
      setCurrentTask(prev => ({
        ...prev,
        steps: latest.data.steps
      }));
    }
    
    if (latest.type === 'ask_user') {
      setAgentStatus('waiting');
      setPendingApproval(latest);
    }
    
    if (latest.type === 'prompt_user') {
      setAgentStatus('waiting');
      setPendingPrompt(latest);
    }
    
    if (latest.type === 'task_done') {
      setIsAgentRunning(false);
      setAgentStatus(latest.status === 'success' ? 'done' : 'error');
      // Reset only if successful (so users can read errors instead of them disappearing)
      if (latest.status === 'success') {
        setTimeout(() => {
          setAgentStatus('idle');
          setCurrentTask({ id: null, steps: [], currentStep: 0 });
        }, 5000);
      }
    }

  }, [messages]);

  // Scroll chat to bottom
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    activityLogEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, historyLogs]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!input.trim()) return;
    
    if (pendingPrompt) {
      const answer = input;
      const taskId = pendingPrompt.task_id;
      setInput('');
      setPendingPrompt(null);
      setAgentStatus('running');
      try {
        await request('POST', '/answer', { task_id: taskId, answer });
      } catch (err) {
        console.error(err);
      }
      return;
    }

    if (isAgentRunning) return;
    
    const userGoal = input;
    setInput('');
    setIsAgentRunning(true);
    setAgentStatus('planning');
    setCurrentTask({ id: null, steps: [], currentStep: 0 });
    
    try {
      await request('POST', '/chat', { message: userGoal });
    } catch (err) {
      setIsAgentRunning(false);
      setAgentStatus('error');
    }
  };

  const handleStop = async () => {
    await request('POST', '/stop');
    setAgentStatus('waiting'); // waiting to stop
  };

  const handleApproval = async (confirmed) => {
    if (!pendingApproval) return;
    try {
      await request('POST', '/confirm', { 
        task_id: pendingApproval.task_id, 
        confirmed 
      });
      setPendingApproval(null);
      setAgentStatus('running');
    } catch (err) {
      console.error(err);
    }
  };

  const handlePlanApproval = async (confirmed) => {
    if (!pendingPlanConfirm) return;
    try {
      await request('POST', '/confirm', { 
        task_id: pendingPlanConfirm.task_id, 
        confirmed 
      });
      setPendingPlanConfirm(null);
      setAgentStatus(confirmed ? 'running' : 'done');
      if (!confirmed) {
         setIsAgentRunning(false);
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleFeedback = async (taskId, feedback) => {
    if (!taskId) return;
    try {
      await request('POST', '/memory/feedback', { task_id: taskId, feedback });
      setFeedbackState(prev => ({ ...prev, [taskId]: feedback }));
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <div className="page-container" style={{ padding: '0', display: 'flex', flexDirection: 'row', maxWidth: '100%', height: '100%' }}>
      {/* Pending Approval Modal */}
      {pendingApproval && (
        <ApprovalModal 
          event={pendingApproval} 
          onConfirm={() => handleApproval(true)}
          onDeny={() => handleApproval(false)}
        />
      )}

      {/* Pending Plan Confirm Modal */}
      {pendingPlanConfirm && (
        <PlanConfirmModal 
          planEvent={pendingPlanConfirm} 
          onConfirm={() => handlePlanApproval(true)}
          onCancel={() => handlePlanApproval(false)}
        />
      )}

      {/* Main Chat Area */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', position: 'relative' }}>
        
        {/* Header */}
        <div style={{ padding: '24px 32px', borderBottom: '1px solid var(--border-color)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <h2 style={{ margin: 0, fontSize: '1.8rem', fontWeight: 700, color: 'var(--secondary)' }}>Command Center</h2>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '4px', fontSize: '0.9rem', color: 'var(--text-muted)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <div style={{
                  width: 8, height: 8, borderRadius: '50%',
                  background: wsStatus === 'connected' ? 'var(--success)' : 'var(--error)'
                }} />
                {wsStatus === 'connected' ? 'System Online' : 'System Offline'}
              </div>
              
              {modelName && (
                <>
                  <span style={{ opacity: 0.3 }}>•</span>
                  <div style={{ 
                    display: 'flex', alignItems: 'center', gap: '4px', 
                    background: 'var(--bg-surface-elevated)', padding: '2px 8px', 
                    borderRadius: '12px', fontSize: '0.8rem', border: '1px solid var(--border-color)' 
                  }}>
                    <Cpu size={12} /> {modelName}
                  </div>
                </>
              )}
            </div>
          </div>

          {isAgentRunning && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
              <div className="glass-panel" style={{ padding: '8px 16px', display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--primary)' }}>
                <RefreshCcw size={16} className="animate-spin" />
                <span style={{ fontSize: '0.9rem', fontWeight: 500 }}>
                  {agentStatus === 'planning' ? 'Planning task...' : 'Executing steps...'}
                </span>
              </div>
              <button className="btn btn-secondary" onClick={handleStop} style={{ color: 'var(--error)' }}>
                <StopCircle size={18} /> Stop
              </button>
            </div>
          )}
        </div>

        {/* Chat / Events Area */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '32px' }}>
          {messages.length === 0 ? (
            <div style={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)' }}>
              <Cpu size={48} strokeWidth={1} style={{ marginBottom: '16px', opacity: 0.5 }} />
              <p style={{ fontSize: '1.2rem', marginBottom: '8px' }}>What can I help you with today?</p>
              <p style={{ fontSize: '0.9rem', opacity: 0.7 }}>Try "Open notepad and type a random poem" or "Search the web for Vite docs"</p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {messages.filter(m => m.type === 'log' || m.message).map((msg, i) => (
                <div key={i} style={{
                  padding: '12px 16px',
                  borderRadius: '8px',
                  background: msg.type === 'error' ? 'rgba(239, 68, 68, 0.1)' : 'var(--bg-surface)',
                  border: `1px solid ${msg.type === 'error' ? 'var(--error)' : 'var(--border-color)'}`,
                  fontSize: '0.95rem',
                  color: msg.type === 'error' ? 'var(--error)' : 'var(--text-main)',
                  display: 'flex',
                  gap: '12px'
                }}>
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', paddingTop: '2px', minWidth: '70px' }}>
                    {new Date(msg.timestamp || Date.now()).toLocaleTimeString([], { hour12: false })}
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', flex: 1 }}>
                    <div>
                      {msg.message}
                      {msg.status === 'success' && <span style={{ color: 'var(--success)', marginLeft: '8px' }}>✓</span>}
                    </div>
                    {msg.type === 'task_done' && msg.task_id && msg.status === 'success' && (
                      <div style={{ marginTop: '12px', display: 'flex', gap: '8px', alignItems: 'center' }}>
                        <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>Was this plan good?</span>
                        <button
                          onClick={() => handleFeedback(msg.task_id, 'thumbs_up')}
                          disabled={feedbackState[msg.task_id]}
                          style={{
                            background: feedbackState[msg.task_id] === 'thumbs_up' ? 'var(--success)' : 'var(--bg-surface-elevated)',
                            color: feedbackState[msg.task_id] === 'thumbs_up' ? '#fff' : 'var(--text-main)',
                            border: '1px solid var(--border-color)',
                            borderRadius: '6px', padding: '6px 10px', 
                            cursor: feedbackState[msg.task_id] ? 'default' : 'pointer',
                            display: 'flex', alignItems: 'center', transition: 'all 0.2s',
                            opacity: feedbackState[msg.task_id] && feedbackState[msg.task_id] !== 'thumbs_up' ? 0.4 : 1
                          }}
                        >
                         <ThumbsUp size={14} />
                        </button>
                        <button
                          onClick={() => handleFeedback(msg.task_id, 'thumbs_down')}
                          disabled={feedbackState[msg.task_id]}
                          style={{
                            background: feedbackState[msg.task_id] === 'thumbs_down' ? 'var(--error)' : 'var(--bg-surface-elevated)',
                            color: feedbackState[msg.task_id] === 'thumbs_down' ? '#fff' : 'var(--text-main)',
                            border: '1px solid var(--border-color)',
                            borderRadius: '6px', padding: '6px 10px', 
                            cursor: feedbackState[msg.task_id] ? 'default' : 'pointer',
                            display: 'flex', alignItems: 'center', transition: 'all 0.2s',
                            opacity: feedbackState[msg.task_id] && feedbackState[msg.task_id] !== 'thumbs_down' ? 0.4 : 1
                          }}
                        >
                         <ThumbsDown size={14} />
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              ))}
              
              {currentTask.steps.length > 0 && (
                <StepProgress 
                  steps={currentTask.steps} 
                  currentStep={currentTask.currentStep} 
                  status={agentStatus}
                />
              )}
              
              <div ref={chatEndRef} />
            </div>
          )}
        </div>

        {/* Input Area */}
        <div style={{ padding: '32px', borderTop: '1px solid var(--border-color)', background: 'var(--bg-main)' }}>
          <form onSubmit={handleSubmit} style={{ position: 'relative' }}>
            <div style={{
              position: 'absolute', left: '16px', top: '50%', transform: 'translateY(-50%)',
              color: 'var(--primary)'
            }}>
              <Command size={20} />
            </div>
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={(isAgentRunning && !pendingPrompt) || wsStatus !== 'connected'}
              placeholder={pendingPrompt ? "Provide clarification to continue..." : "Tell Oliv what to do..."}
              style={{
                width: '100%',
                padding: '16px 16px 16px 48px',
                borderRadius: '12px',
                border: '1px solid var(--border-color)',
                background: 'var(--bg-surface)',
                color: 'var(--text-main)',
                fontSize: '1rem',
                outline: 'none',
                boxShadow: '0 4px 20px rgba(0,0,0,0.2)',
                transition: 'border-color 0.2s'
              }}
              onFocus={(e) => e.target.style.borderColor = 'var(--primary)'}
              onBlur={(e) => e.target.style.borderColor = 'var(--border-color)'}
            />
            <button 
              type="submit" 
              disabled={!input.trim() || (isAgentRunning && !pendingPrompt) || wsStatus !== 'connected'}
              style={{
                position: 'absolute', right: '12px', top: '50%', transform: 'translateY(-50%)',
                background: input.trim() && (!isAgentRunning || pendingPrompt) ? 'var(--primary)' : 'var(--bg-surface-elevated)',
                color: input.trim() && (!isAgentRunning || pendingPrompt) ? 'white' : 'var(--text-muted)',
                border: 'none',
                borderRadius: '8px',
                padding: '8px',
                cursor: input.trim() && (!isAgentRunning || pendingPrompt) ? 'pointer' : 'not-allowed',
                transition: 'all 0.2s',
                display: 'flex', alignItems: 'center', justifyContent: 'center'
              }}
            >
              <Send size={18} />
            </button>
          </form>
        </div>

      </div>

      {/* Right Sidebar - Activity Log */}
      <div style={{ width: '380px', borderLeft: '1px solid var(--border-color)', display: 'flex', flexDirection: 'column', background: 'var(--bg-main)' }}>
        <div style={{ padding: '24px', borderBottom: '1px solid var(--border-color)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <h3 style={{ margin: 0, fontSize: '1.1rem', fontWeight: 600 }}>Live Activity</h3>
          <Cpu size={16} color="var(--text-muted)" />
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: '24px', display: 'flex', flexDirection: 'column', gap: '24px' }}>
          {React.useMemo(() => {
            const groups = [];
            let currentTaskLogs = [];
            let currentTaskId = null;

            allLogs.forEach(log => {
              const taskId = log.task_id || (log.data && log.data.task_id);
              if (taskId !== currentTaskId) {
                if (currentTaskLogs.length > 0) {
                  groups.push({ taskId: currentTaskId, logs: currentTaskLogs });
                }
                currentTaskId = taskId;
                currentTaskLogs = [log];
              } else {
                currentTaskLogs.push(log);
              }
            });
            if (currentTaskLogs.length > 0) {
              groups.push({ taskId: currentTaskId, logs: currentTaskLogs });
            }
            return groups;
          }, [allLogs]).map((group, groupIdx) => {
            
            const parseLog = group.logs.find(l => l.message?.startsWith('Parsing intent: '));
            const intentLog = group.logs.find(l => l.message?.startsWith('Intent: '));
            
            let userText = `System Task ${group.taskId || ''}`;
            if (parseLog) {
              userText = parseLog.message.replace('Parsing intent: ', '').replace('...', '');
            } else if (intentLog) {
              userText = intentLog.message.replace('Intent: ', '');
            } else if (group.taskId === null) {
              userText = 'System Events';
            }

            return (
              <div key={groupIdx} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                {/* User Message Bubble */}
                {userText !== 'System Events' && (
                  <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                    <div style={{ 
                      background: 'var(--primary)', color: '#fff', padding: '10px 16px', 
                      borderRadius: '16px 16px 0 16px', maxWidth: '85%', fontSize: '0.9rem',
                      lineHeight: '1.4', boxShadow: '0 2px 8px rgba(0,0,0,0.2)'
                    }}>
                      {userText}
                    </div>
                  </div>
                )}

                {/* Agent Activity Bubble */}
                <div style={{ display: 'flex', justifyContent: 'flex-start' }}>
                  <div style={{ 
                    background: 'var(--bg-surface)', border: '1px solid var(--border-color)', 
                    borderRadius: userText !== 'System Events' ? '16px 16px 16px 0' : '16px', 
                    padding: '20px', width: '100%', boxShadow: '0 4px 12px rgba(0,0,0,0.1)'
                  }}>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: '16px', textTransform: 'uppercase', fontWeight: 600, letterSpacing: '0.5px' }}>
                      Activity Feed
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                      {group.logs.map((log, i) => {
                        const timeStr = new Date(log.timestamp || Date.now()).toLocaleTimeString([], { hour12: false });
                        const isError = log.level === 'error' || log.type === 'error';
                        const isSuccess = log.level === 'success' || log.status === 'success';
                        
                        const logData = log.data || {};
                        const logType = log.type || logData.type || 'info';
                        
                        let heading = logType.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
                        if (logType === 'step_start' && (logData.tool || log.tool)) {
                          heading = `Execute: ${logData.tool || log.tool}`;
                        } else if (logType === 'ask_user') {
                          heading = 'User Input Required';
                        } else if (logType === 'task_done') {
                          heading = log.status === 'success' ? 'Task Completed' : 'Task Ended';
                        } else if (logType === 'log') {
                          heading = 'System Log';
                        }
                        
                        let badgeColor = 'var(--text-muted)';
                        let badgeBg = 'transparent';
                        
                        if (isError) {
                          badgeColor = 'var(--error)';
                          badgeBg = 'rgba(239, 68, 68, 0.1)';
                        } else if (isSuccess) {
                          badgeColor = 'var(--success)';
                          badgeBg = 'rgba(16, 185, 129, 0.1)';
                        } else if (log.level === 'warning') {
                          badgeColor = 'var(--warning)';
                          badgeBg = 'rgba(245, 158, 11, 0.1)';
                        } else {
                          badgeColor = 'var(--primary)';
                          badgeBg = 'var(--bg-surface-elevated)';
                        }

                        return (
                          <div key={i} style={{ 
                            display: 'flex', gap: '12px', alignItems: 'flex-start'
                          }}>
                            <div style={{ 
                              marginTop: '6px', width: '8px', height: '8px', borderRadius: '50%', backgroundColor: badgeColor, flexShrink: 0, boxShadow: `0 0 8px ${badgeBg !== 'transparent' ? badgeColor : 'transparent'}`
                            }} />
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', flex: 1 }}>
                              <div style={{ color: 'var(--text-main)', fontSize: '0.95rem', fontWeight: 600, letterSpacing: '0.3px' }}>
                                {heading}
                              </div>
                              {log.message && !log.message.startsWith('Parsing intent: ') && (
                                <div style={{ color: 'var(--text-main)', opacity: 0.85, fontSize: '0.85rem', lineHeight: '1.4', wordBreak: 'break-word' }}>
                                  {log.message}
                                </div>
                              )}
                              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '2px' }}>
                                <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem', fontFamily: 'monospace' }}>
                                  {timeStr}
                                </span>
                                {log.level && log.level !== 'info' && (
                                  <span style={{ 
                                    color: badgeColor, background: badgeBg, padding: '2px 6px', borderRadius: '4px', 
                                    fontSize: '0.65rem', textTransform: 'uppercase', fontWeight: 600, letterSpacing: '0.5px'
                                  }}>
                                    {log.level}
                                  </span>
                                )}
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
          {allLogs.length === 0 && (
            <div style={{ color: 'var(--text-muted)', textAlign: 'center', marginTop: '40px', fontSize: '0.9rem' }}>
              No activity yet.
            </div>
          )}
          <div ref={activityLogEndRef} />
        </div>
      </div>
    </div>
  );
}
