import React, { useState, useEffect } from 'react';
import { Server, Sparkles, ShieldAlert, ShieldCheck, Shield, ChevronRight, CheckCircle2, Loader2 } from 'lucide-react';
import { useApi } from '../hooks/useApi';

export default function SetupWizard({ onComplete }) {
  const { request } = useApi();
  const [step, setStep] = useState(1);
  const [loading, setLoading] = useState(false);
  
  // Config state
  const [provider, setProvider] = useState('ollama'); // ollama | gemini
  
  // Ollama specific
  const [ollamaModels, setOllamaModels] = useState([]);
  const [selectedModel, setSelectedModel] = useState('');
  
  // Gemini specific
  const [geminiKey, setGeminiKey] = useState('');
  const [geminiModel, setGeminiModel] = useState('gemini-2.0-flash');
  
  // Approval
  const [approvalMode, setApprovalMode] = useState('smart'); // safe | smart | autonomous
  
  const [testResult, setTestResult] = useState(null); // {success: bool, message: str}

  // Fetch Ollama models if local chosen
  useEffect(() => {
    if (provider === 'ollama' && step === 2) {
      request('GET', '/ollama/models')
        .then(res => {
          setOllamaModels(res.models || []);
          if (res.models && res.models.length > 0) setSelectedModel(res.models[0]);
        })
        .catch(() => setOllamaModels([]));
    }
  }, [provider, step, request]);

  const handleTestConnection = async () => {
    setLoading(true);
    setTestResult(null);
    try {
      const payload = provider === 'ollama'
        ? { provider: 'ollama', model: selectedModel }
        : { provider: 'gemini', gemini_api_key: geminiKey, gemini_model: geminiModel };
        
      const res = await request('POST', '/config/test-connection', payload);
      setTestResult(res);
      if (res.success) setTimeout(() => setStep(3), 1000);
    } catch (e) {
      setTestResult({ success: false, message: e.message });
    } finally {
      setLoading(false);
    }
  };

  const handleFinish = async () => {
    setLoading(true);
    try {
      const modelConfig = provider === 'ollama'
        ? { provider: 'ollama', model: selectedModel, base_url: 'http://localhost:11434' }
        : { provider: 'gemini', gemini_api_key: geminiKey, gemini_model: geminiModel, model: geminiModel };

      await request('POST', '/config/complete-setup', {
        model_config_data: modelConfig,
        user_preferences: { approval_mode: approvalMode, browser: null, editor: null, terminal: null }
      });
      onComplete();
    } catch (e) {
      alert("Failed to save config: " + e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', background: 'var(--bg-dark)' }}>
      
      <div style={{ marginBottom: '40px', textAlign: 'center' }}>
        <h1 style={{ fontSize: '2.5rem', fontWeight: 700, background: 'linear-gradient(to right, #8b5cf6, #d946ef)', WebkitBackgroundClip: 'text', color: 'transparent', marginBottom: '8px' }}>
          Welcome to Oliv AI
        </h1>
        <p style={{ color: 'var(--text-muted)', fontSize: '1.1rem' }}>Let's configure your autonomous Windows assistant.</p>
      </div>

      <div className="glass-panel" style={{ width: '100%', maxWidth: '600px', minHeight: '400px', display: 'flex', flexDirection: 'column' }}>
        
        {/* Progress Bar */}
        <div style={{ display: 'flex', padding: '24px 32px', borderBottom: '1px solid var(--border-color)' }}>
          {[1, 2, 3].map(s => (
            <div key={s} style={{ flex: 1, height: '4px', background: s <= step ? 'var(--primary)' : 'var(--bg-surface-elevated)', borderRadius: '2px', margin: '0 4px', transition: 'background 0.3s' }} />
          ))}
        </div>

        <div style={{ flex: 1, padding: '32px' }}>
          
          {/* STEP 1: Provider selection */}
          {step === 1 && (
            <div className="fade-in">
              <h2 style={{ fontSize: '1.3rem', marginBottom: '24px' }}>Choose your Brain</h2>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                <div 
                  onClick={() => setProvider('ollama')}
                  style={{ 
                    padding: '24px', borderRadius: '12px', cursor: 'pointer', transition: 'all 0.2s',
                    background: provider === 'ollama' ? 'rgba(139, 92, 246, 0.1)' : 'var(--bg-surface)',
                    border: `2px solid ${provider === 'ollama' ? 'var(--primary)' : 'var(--border-color)'}`
                  }}
                >
                  <Server size={32} color={provider === 'ollama' ? 'var(--primary)' : 'var(--text-muted)'} style={{ marginBottom: '16px' }} />
                  <h3 style={{ fontSize: '1.1rem', marginBottom: '8px' }}>Ollama</h3>
                  <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>Local or cloud Ollama models. Private, free, and fully customizable. (e.g. qwen2.5, llama3)</p>
                </div>

                <div 
                  onClick={() => setProvider('gemini')}
                  style={{ 
                    padding: '24px', borderRadius: '12px', cursor: 'pointer', transition: 'all 0.2s',
                    background: provider === 'gemini' ? 'rgba(139, 92, 246, 0.1)' : 'var(--bg-surface)',
                    border: `2px solid ${provider === 'gemini' ? 'var(--primary)' : 'var(--border-color)'}`
                  }}
                >
                  <Sparkles size={32} color={provider === 'gemini' ? 'var(--primary)' : 'var(--text-muted)'} style={{ marginBottom: '16px' }} />
                  <h3 style={{ fontSize: '1.1rem', marginBottom: '8px' }}>Google Gemini</h3>
                  <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>Gemini Flash / Pro via Google AI API. Best multimodal vision support. Free tier available.</p>
                </div>
              </div>
            </div>
          )}

          {/* STEP 2: Configure Brain */}
          {step === 2 && (
            <div className="fade-in">
              <h2 style={{ fontSize: '1.3rem', marginBottom: '24px' }}>Configure {provider === 'ollama' ? 'Ollama' : 'Google Gemini'}</h2>
              
              {provider === 'ollama' ? (
                <div>
                  <label style={{ display: 'block', marginBottom: '8px', fontSize: '0.9rem', color: 'var(--text-muted)' }}>Select Installed Model</label>
                  {ollamaModels.length === 0 ? (
                    <div style={{ padding: '16px', background: 'rgba(239, 68, 68, 0.1)', color: 'var(--error)', borderRadius: '8px', fontSize: '0.9rem' }}>
                      No models found. Make sure Ollama is running (<code>http://localhost:11434</code>) and you have pulled a model (e.g., <code>ollama pull qwen2.5:7b</code>).
                    </div>
                  ) : (
                    <select 
                      value={selectedModel} 
                      onChange={(e) => setSelectedModel(e.target.value)}
                      style={{ width: '100%', padding: '12px', borderRadius: '8px', background: 'var(--bg-surface)', color: 'var(--text-main)', border: '1px solid var(--border-color)' }}
                    >
                      {ollamaModels.map(m => <option key={m} value={m}>{m}</option>)}
                    </select>
                  )}
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                  <div>
                    <label style={{ display: 'block', marginBottom: '8px', fontSize: '0.9rem', color: 'var(--text-muted)' }}>Gemini API Key</label>
                    <input
                      type="password"
                      value={geminiKey}
                      onChange={(e) => setGeminiKey(e.target.value)}
                      placeholder="AIza..."
                      style={{ width: '100%', padding: '12px', borderRadius: '8px', background: 'var(--bg-surface)', color: 'var(--text-main)', border: '1px solid var(--border-color)' }}
                    />
                    <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '6px' }}>
                      Get a free key at <a href="https://aistudio.google.com/apikey" target="_blank" rel="noreferrer" style={{ color: 'var(--primary)' }}>aistudio.google.com/apikey</a>
                    </p>
                  </div>
                  <div>
                    <label style={{ display: 'block', marginBottom: '8px', fontSize: '0.9rem', color: 'var(--text-muted)' }}>Gemini Model</label>
                    <select
                      value={geminiModel}
                      onChange={(e) => setGeminiModel(e.target.value)}
                      style={{ width: '100%', padding: '12px', borderRadius: '8px', background: 'var(--bg-surface)', color: 'var(--text-main)', border: '1px solid var(--border-color)' }}
                    >
                      <option value="gemini-2.0-flash">gemini-2.0-flash (recommended)</option>
                      <option value="gemini-2.0-flash-lite">gemini-2.0-flash-lite (fastest)</option>
                      <option value="gemini-2.5-flash-preview-04-17">gemini-2.5-flash-preview (latest)</option>
                      <option value="gemini-2.5-pro-preview-03-25">gemini-2.5-pro-preview (best quality)</option>
                    </select>
                  </div>
                </div>
              )}

              {testResult && (
                <div style={{ marginTop: '16px', padding: '12px', borderRadius: '8px', background: testResult.success ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)', color: testResult.success ? 'var(--success)' : 'var(--error)', display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.9rem' }}>
                  {testResult.success ? <CheckCircle2 size={16} /> : <ShieldAlert size={16} />}
                  {testResult.message}
                </div>
              )}
            </div>
          )}

          {/* STEP 3: Approval Mode */}
          {step === 3 && (
            <div className="fade-in">
              <h2 style={{ fontSize: '1.3rem', marginBottom: '8px' }}>Safety & Approval Mode</h2>
              <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem', marginBottom: '24px' }}>How much autonomy should Oliv have?</p>
              
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {[
                  { id: 'safe', title: 'Safe Mode', desc: 'Asks for permission before EVERY action (clicks, typing, browsing).', icon: ShieldCheck, color: 'var(--success)' },
                  { id: 'smart', title: 'Smart Mode (Recommended)', desc: 'Acts autonomously for safe tasks (read, browse), but asks before risky actions (terminals, shell).', icon: Shield, color: 'var(--primary)' },
                  { id: 'autonomous', title: 'Full Autonomous Mode', desc: 'Never asks for permission. Only use if you completely trust the model.', icon: ShieldAlert, color: 'var(--error)' }
                ].map(mode => (
                  <div 
                    key={mode.id}
                    onClick={() => setApprovalMode(mode.id)}
                    style={{ 
                      display: 'flex', gap: '16px', padding: '20px', borderRadius: '12px', cursor: 'pointer', transition: 'all 0.2s',
                      background: approvalMode === mode.id ? 'rgba(255,255,255,0.05)' : 'var(--bg-surface)',
                      border: `1px solid ${approvalMode === mode.id ? mode.color : 'var(--border-color)'}`
                    }}
                  >
                    <mode.icon size={24} color={mode.color} style={{ marginTop: '2px' }} />
                    <div>
                      <h3 style={{ fontSize: '1rem', color: approvalMode === mode.id ? 'var(--text-main)' : 'var(--text-muted)', marginBottom: '4px' }}>{mode.title}</h3>
                      <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>{mode.desc}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

        </div>

        {/* Footer actions */}
        <div style={{ padding: '24px 32px', borderTop: '1px solid var(--border-color)', display: 'flex', justifyContent: 'space-between' }}>
          {step > 1 ? (
            <button className="btn btn-secondary" onClick={() => setStep(s => s - 1)}>Back</button>
          ) : <div />}

          {step === 1 && <button className="btn btn-primary" onClick={() => setStep(2)}>Continue <ChevronRight size={16}/></button>}
          {step === 2 && (
            <button className="btn btn-primary" onClick={handleTestConnection} disabled={loading || (provider === 'ollama' && !selectedModel) || (provider === 'gemini' && !geminiKey)}
              style={{ opacity: (loading || (provider === 'ollama' && !selectedModel) || (provider === 'gemini' && !geminiKey)) ? 0.6 : 1 }}>
              {loading ? (
                <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} /> Testing connection...
                </span>
              ) : 'Test & Continue'}
            </button>
          )}
          {step === 3 && (
            <button className="btn btn-primary" onClick={handleFinish} disabled={loading}>
              {loading ? <Loader2 size={16} className="animate-spin" /> : 'Complete Setup'} <CheckCircle2 size={16}/>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
