import React, { useState, useEffect } from 'react';
import { Save, RefreshCcw, CheckCircle2, ShieldAlert, Eye } from 'lucide-react';
import { useApi } from '../hooks/useApi';

export default function Settings() {
  const { request } = useApi();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  
  const [config, setConfig] = useState(null);
  const [testResult, setTestResult] = useState(null);
  
  const [ollamaModels, setOllamaModels] = useState([]);
  const [ollamaLoading, setOllamaLoading] = useState(false);

  useEffect(() => {
    fetchConfig();
  }, []);

  const fetchConfig = async () => {
    setLoading(true);
    try {
      const res = await request('GET', '/config');
      // Sanitize: if provider is ollama but base_url is a non-Ollama URL, reset it
      if (res.model_config.provider === 'ollama') {
        const url = res.model_config.base_url || '';
        if (url && !url.includes('localhost') && !url.includes('127.0.0.1') && !url.includes('ollama')) {
          res.model_config.base_url = 'http://localhost:11434';
        }
        fetchOllamaModels();
      }
      setConfig(res);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const fetchOllamaModels = async () => {
    setOllamaLoading(true);
    try {
      const modelsRes = await request('GET', '/ollama/models');
      setOllamaModels(modelsRes.models || []);
    } catch (e) {
      setOllamaModels([]);
    } finally {
      setOllamaLoading(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await request('PUT', '/config', { config });
      setTestResult({ success: true, message: 'Settings saved successfully.' });
      setTimeout(() => setTestResult(null), 3000);
    } catch (e) {
      setTestResult({ success: false, message: e.message });
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    setSaving(true);
    setTestResult(null);
    try {
      const res = await request('POST', '/config/test-connection', config.model_config);
      setTestResult(res);
    } catch (e) {
      setTestResult({ success: false, message: e.message });
    } finally {
      setSaving(false);
    }
  };

  const updateModelConfig = (field, value) => {
    setConfig(prev => ({
      ...prev,
      model_config: { ...prev.model_config, [field]: value }
    }));
  };

  const updatePref = (field, value) => {
    setConfig(prev => ({
      ...prev,
      user_preferences: { ...prev.user_preferences, [field]: value }
    }));
  };

  if (loading || !config) return <div style={{ padding: '32px' }}>Loading...</div>;

  const mconf = config.model_config;
  const prefs = config.user_preferences;

  return (
    <div style={{ padding: '40px', maxWidth: '800px', margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '32px' }}>
        <h1 style={{ fontSize: '1.8rem', fontWeight: 600 }}>Settings</h1>
        <div style={{ display: 'flex', gap: '12px' }}>
          <button className="btn btn-secondary" onClick={handleTest} disabled={saving}>
            <RefreshCcw size={16} className={saving ? "animate-spin" : ""} /> Test Connection
          </button>
          <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
            <Save size={16} /> Save Changes
          </button>
        </div>
      </div>

      {testResult && (
        <div style={{ 
          padding: '12px 16px', borderRadius: '8px', marginBottom: '24px', display: 'flex', alignItems: 'center', gap: '8px',
          background: testResult.success ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)',
          color: testResult.success ? 'var(--success)' : 'var(--error)',
        }}>
          {testResult.success ? <CheckCircle2 size={18} /> : <ShieldAlert size={18} />}
          {testResult.message}
        </div>
      )}

      {/* Model Settings */}
      <div className="glass-panel" style={{ padding: '24px', marginBottom: '24px' }}>
        <h2 style={{ fontSize: '1.2rem', marginBottom: '24px', color: 'var(--primary)' }}>Model Configuration</h2>
        
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
          <div>
            <label style={{ display: 'block', marginBottom: '8px', fontSize: '0.9rem', color: 'var(--text-muted)' }}>Provider</label>
            <select 
              value={mconf.provider} 
              onChange={e => {
                const newProvider = e.target.value;
                updateModelConfig('provider', newProvider);
                if (newProvider === 'ollama') {
                  // Reset base_url to Ollama default when switching to Ollama
                  updateModelConfig('base_url', 'http://localhost:11434');
                  fetchOllamaModels();
                }
              }}
              style={{ width: '100%', padding: '10px', borderRadius: '8px', background: 'var(--bg-surface)', color: 'var(--text-main)', border: '1px solid var(--border-color)' }}
            >
              <option value="ollama">Local / Cloud (Ollama)</option>
              <option value="gemini">Google Gemini</option>
            </select>
          </div>

          {mconf.provider === 'ollama' && (
            <>
              <div>
                <label style={{ display: 'block', marginBottom: '8px', fontSize: '0.9rem', color: 'var(--text-muted)' }}>
                  Model
                  {ollamaLoading && <span style={{ marginLeft: '8px', fontSize: '0.75rem', color: 'var(--text-muted)', fontStyle: 'italic' }}>fetching…</span>}
                </label>
                {ollamaModels.length > 0 ? (
                  <select
                    value={mconf.model || ''}
                    onChange={e => updateModelConfig('model', e.target.value)}
                    style={{ width: '100%', padding: '10px', borderRadius: '8px', background: 'var(--bg-surface)', color: 'var(--text-main)', border: '1px solid var(--border-color)' }}
                  >
                    {ollamaModels.map(m => <option key={m} value={m}>{m}</option>)}
                  </select>
                ) : (
                  <input
                    type="text"
                    value={mconf.model || ''}
                    onChange={e => updateModelConfig('model', e.target.value)}
                    placeholder={ollamaLoading ? 'Loading models…' : 'e.g. qwen2.5:7b  (Ollama not reachable)'}
                    style={{ width: '100%', padding: '10px', borderRadius: '8px', background: 'var(--bg-surface)', color: 'var(--text-main)', border: '1px solid var(--border-color)' }}
                  />
                )}
              </div>
              <div>
                <label style={{ display: 'block', marginBottom: '8px', fontSize: '0.9rem', color: 'var(--text-muted)' }}>Ollama Base URL</label>
                <input
                  type="text"
                  value={mconf.base_url || 'http://localhost:11434'}
                  onChange={e => updateModelConfig('base_url', e.target.value)}
                  placeholder="http://localhost:11434"
                  style={{ width: '100%', padding: '10px', borderRadius: '8px', background: 'var(--bg-surface)', color: 'var(--text-main)', border: '1px solid var(--border-color)' }}
                />
                <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '6px' }}>
                  Use a remote URL for cloud-hosted Ollama instances.
                </p>
              </div>
            </>
          )}

          {mconf.provider === 'gemini' && (
            <>
              <div>
                <label style={{ display: 'block', marginBottom: '8px', fontSize: '0.9rem', color: 'var(--text-muted)' }}>Gemini API Key</label>
                <input
                  type="password"
                  value={mconf.gemini_api_key || ''}
                  onChange={e => updateModelConfig('gemini_api_key', e.target.value)}
                  placeholder="AIza..."
                  style={{ width: '100%', padding: '10px', borderRadius: '8px', background: 'var(--bg-surface)', color: 'var(--text-main)', border: '1px solid var(--border-color)' }}
                />
                <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '6px' }}>
                  Get a free key at <a href="https://aistudio.google.com/apikey" target="_blank" rel="noreferrer" style={{ color: 'var(--primary)' }}>aistudio.google.com/apikey</a>
                </p>
              </div>
              <div>
                <label style={{ display: 'block', marginBottom: '8px', fontSize: '0.9rem', color: 'var(--text-muted)' }}>Gemini Model</label>
                <select
                  value={mconf.gemini_model || 'gemini-2.0-flash'}
                  onChange={e => { updateModelConfig('gemini_model', e.target.value); updateModelConfig('model', e.target.value); }}
                  style={{ width: '100%', padding: '10px', borderRadius: '8px', background: 'var(--bg-surface)', color: 'var(--text-main)', border: '1px solid var(--border-color)' }}
                >
                  <option value="gemini-2.0-flash">gemini-2.0-flash (recommended)</option>
                  <option value="gemini-2.0-flash-lite">gemini-2.0-flash-lite (fastest)</option>
                  <option value="gemini-2.5-flash-preview-04-17">gemini-2.5-flash-preview (latest)</option>
                  <option value="gemini-2.5-pro-preview-03-25">gemini-2.5-pro-preview (best quality)</option>
                </select>
              </div>
            </>
          )}

        </div>
      </div>

      {/* Vision Model — Phase 2 */}
      <div className="glass-panel" style={{ padding: '24px', marginBottom: '24px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
          <h2 style={{ fontSize: '1.2rem', color: 'var(--primary)' }}>Vision Model</h2>
          <span style={{ fontSize: '0.7rem', background: 'rgba(139,92,246,0.2)', color: '#a78bfa', borderRadius: '4px', padding: '2px 8px', fontWeight: 600 }}>PHASE 2</span>
        </div>
        <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginBottom: '16px' }}>
          Optional: configure a vision-capable model so Oliv can visually verify each step completed correctly.
        </p>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
          <div>
            <label style={{ display: 'block', marginBottom: '8px', fontSize: '0.9rem', color: 'var(--text-muted)' }}>Vision Model</label>
            <input
              type="text"
              value={mconf.vision_model || ''}
              onChange={e => updateModelConfig('vision_model', e.target.value || null)}
              placeholder={mconf.provider === 'gemini' ? 'gemini  (auto — uses your Gemini key)' : 'e.g. ollama:llava'}
              style={{ width: '100%', padding: '10px', borderRadius: '8px', background: 'var(--bg-surface)', color: 'var(--text-main)', border: '1px solid var(--border-color)' }}
            />
          </div>
          <div style={{ display: 'flex', alignItems: 'flex-end', paddingBottom: '2px' }}>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', lineHeight: 1.5 }}>
              <code style={{ color: '#a78bfa' }}>gemini</code> (Google Vision) &nbsp;|&nbsp; <code style={{ color: '#a78bfa' }}>ollama:llava</code><br />
              Leave blank to use code-only reflection.
            </p>
          </div>
        </div>
      </div>

      {/* App Preferences */}
      <div className="glass-panel" style={{ padding: '24px' }}>
        <h2 style={{ fontSize: '1.2rem', marginBottom: '24px', color: 'var(--primary)' }}>Preferences & Safety</h2>
        
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
          <div>
            <label style={{ display: 'block', marginBottom: '8px', fontSize: '0.9rem', color: 'var(--text-muted)' }}>Approval Mode</label>
            <select 
              value={prefs.approval_mode} 
              onChange={e => updatePref('approval_mode', e.target.value)}
              style={{ width: '100%', padding: '10px', borderRadius: '8px', background: 'var(--bg-surface)', color: 'var(--text-main)', border: '1px solid var(--border-color)' }}
            >
              <option value="safe">Safe (Ask for everything)</option>
              <option value="smart">Smart (Ask for risky actions)</option>
              <option value="autonomous">Autonomous (Never ask)</option>
            </select>
          </div>
          
          <div>
            <label style={{ display: 'block', marginBottom: '8px', fontSize: '0.9rem', color: 'var(--text-muted)' }}>Preferred Browser</label>
            <input 
              type="text" 
              value={prefs.browser || ''} 
              onChange={e => updatePref('browser', e.target.value)}
              placeholder="e.g. Chrome, Edge (Optional)"
              style={{ width: '100%', padding: '10px', borderRadius: '8px', background: 'var(--bg-surface)', color: 'var(--text-main)', border: '1px solid var(--border-color)' }}
            />
          </div>
        </div>
      </div>

    </div>
  );
}
