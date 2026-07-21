import { useState, useEffect } from 'react';
import type { Config, ConfigUpdate } from '../api';
import { updateConfig, toggleLlm } from '../api';

interface Props {
  config: Config | null;
  open: boolean;
  onClose: () => void;
  onSaved: (cfg: Config) => void;
}

export default function ConfigPanel({ config, open, onClose, onSaved }: Props) {
  const [url, setUrl] = useState(config?.llm_api_url || '');
  const [key, setKey] = useState('');
  const [model, setModel] = useState(config?.llm_model || 'gpt-4o');
  const [flashModel, setFlashModel] = useState(config?.llm_flash_model || '');
  const [llmEnabled, setLlmEnabled] = useState(config?.llm_enabled ?? true);
  const [mcpUrl, setMcpUrl] = useState(config?.mcp_server_url || '');
  const [ctxUrl, setCtxUrl] = useState(config?.context_llm_url || '');
  const [ctxKey, setCtxKey] = useState('');
  const [ctxModel, setCtxModel] = useState(config?.context_llm_model || '');
  const [toggling, setToggling] = useState(false);
  const [saving, setSaving] = useState(false);

  // Sync state when config prop changes or panel opens
  useEffect(() => {
    if (open && config) {
      setUrl(config.llm_api_url || '');
      setModel(config.llm_model || 'gpt-4o');
      setFlashModel(config.llm_flash_model || '');
      setLlmEnabled(config.llm_enabled ?? true);
      setMcpUrl(config.mcp_server_url || '');
      setCtxUrl(config.context_llm_url || '');
      setCtxModel(config.context_llm_model || '');
      setKey('');
      setCtxKey('');
    }
  }, [open, config]);

  if (!open) return null;

  const handleToggleLlm = async () => {
    setToggling(true);
    try {
      const result = await toggleLlm();
      setLlmEnabled(result.llm_enabled);
      // Update the parent config state optimistically
      if (config) {
        onSaved({ ...config, llm_enabled: result.llm_enabled });
      }
    } catch (e) {
      console.error('Failed to toggle LLM:', e);
    } finally {
      setToggling(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const cfg: ConfigUpdate = {
        llm_api_url: url,
        llm_api_key: key || '',
        llm_model: model,
        llm_flash_model: flashModel,
        llm_enabled: llmEnabled,
        mcp_server_url: mcpUrl,
        context_llm_url: ctxUrl,
        context_llm_key: ctxKey || '',
        context_llm_model: ctxModel,
      };
      // If key is empty, don't overwrite the stored one
      if (!key && config?.llm_api_key_masked) {
        cfg.llm_api_key = ''; // backend should preserve existing
      }
      const updated = await updateConfig(cfg);
      onSaved(updated);
      setKey('');
      onClose();
    } catch (e) {
      console.error('Failed to save config:', e);
    } finally {
      setSaving(false);
    }
  };

  const handleOverlayClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) onClose();
  };

  return (
    <div className="config-overlay" onClick={handleOverlayClick}>
      <div className="config-card">
        <h2>⚙ LLM Configuration</h2>

        {/* ── LLM Enable / Disable toggle ── */}
        <div className="form-group" style={{
          background: llmEnabled ? '#f0fdf4' : '#fef2f2',
          border: `1px solid ${llmEnabled ? '#bbf7d0' : '#fecaca'}`,
          borderRadius: 8,
          padding: '12px 16px',
          marginBottom: 20,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 2 }}>
                {llmEnabled ? '🟢 LLM Enabled' : '🔴 LLM Disabled'}
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                {llmEnabled
                  ? 'News analysis uses the configured LLM API.'
                  : 'Using keyword-based fallback — no API calls.'}
              </div>
            </div>
            <button
              className={`toggle-switch ${llmEnabled ? 'on' : 'off'}`}
              onClick={handleToggleLlm}
              disabled={toggling}
              style={{
                width: 52,
                height: 28,
                borderRadius: 14,
                border: 'none',
                background: llmEnabled ? '#22c55e' : '#d1d5db',
                cursor: 'pointer',
                position: 'relative',
                transition: 'background 0.2s',
                flexShrink: 0,
              }}
              title={llmEnabled ? 'Click to disable LLM' : 'Click to enable LLM'}
            >
              <span style={{
                position: 'absolute',
                top: 3,
                left: llmEnabled ? 27 : 3,
                width: 22,
                height: 22,
                borderRadius: '50%',
                background: '#fff',
                transition: 'left 0.2s',
                boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
              }} />
            </button>
          </div>
          {toggling && (
            <div style={{ fontSize: 12, marginTop: 6, opacity: 0.7 }}>Toggling...</div>
          )}
        </div>

        <div className="form-group">
          <label>API Endpoint URL</label>
          <input
            type="text"
            value={url}
            onChange={e => setUrl(e.target.value)}
            placeholder="https://api.openai.com/v1"
            style={{ width: '100%' }}
          />
        </div>

        <div className="form-group">
          <label>API Key</label>
          <input
            type="password"
            value={key}
            onChange={e => setKey(e.target.value)}
            placeholder={config?.llm_api_key_masked || 'sk-...'}
            style={{ width: '100%' }}
          />
          {config?.llm_api_key_masked && !key && (
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
              Current: {config.llm_api_key_masked} (leave blank to keep)
            </div>
          )}
        </div>

        <div className="form-group">
          <label>Model (Pro)</label>
          <input
            type="text"
            value={model}
            onChange={e => setModel(e.target.value)}
            placeholder="gpt-4o"
            style={{ width: '100%' }}
          />
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
            Used for main analysis and financial tool-calling
          </div>
        </div>

        <div className="form-group">
          <label>Model (Flash)</label>
          <input
            type="text"
            value={flashModel}
            onChange={e => setFlashModel(e.target.value)}
            placeholder="deepseek-chat (leave empty to use Pro model)"
            style={{ width: '100%' }}
          />
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
            Used for quick tasks: stock identification, news context search. Falls back to Pro model if empty.
          </div>
        </div>

        <hr style={{ border: 'none', borderTop: '1px solid var(--border)', margin: '16px 0' }} />
        <h3 style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 12 }}>MCP Financial Data</h3>

        <div className="form-group">
          <label>MCP Server URL</label>
          <input
            type="text"
            value={mcpUrl}
            onChange={e => setMcpUrl(e.target.value)}
            placeholder="http://sacollector-mcp:8081"
            style={{ width: '100%' }}
          />
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
            sacollector MCP server — provides stock financial data for enrichment
          </div>
        </div>

        <hr style={{ border: 'none', borderTop: '1px solid var(--border)', margin: '16px 0' }} />
        <h3 style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 12 }}>Context LLM (News Search)</h3>
        <p style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 12 }}>
          Used to search recent positive/negative news about the stock. Falls back to main LLM if not configured.
        </p>

        <div className="form-group">
          <label>Context LLM URL</label>
          <input
            type="text"
            value={ctxUrl}
            onChange={e => setCtxUrl(e.target.value)}
            placeholder="https://api.deepseek.com (leave empty to use main LLM)"
            style={{ width: '100%' }}
          />
        </div>

        <div className="form-group">
          <label>Context LLM Key</label>
          <input
            type="password"
            value={ctxKey}
            onChange={e => setCtxKey(e.target.value)}
            placeholder={config?.context_llm_key_masked || 'sk-...'}
            style={{ width: '100%' }}
          />
        </div>

        <div className="form-group">
          <label>Context LLM Model</label>
          <input
            type="text"
            value={ctxModel}
            onChange={e => setCtxModel(e.target.value)}
            placeholder="deepseek-v4-pro"
            style={{ width: '100%' }}
          />
        </div>

        <div className="btn-row">
          <button className="btn" onClick={onClose} style={{ background: '#f3f4f6', color: '#555' }}>
            Cancel
          </button>
          <button className="btn btn-primary" onClick={handleSave} disabled={saving || !url}>
            {saving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}
