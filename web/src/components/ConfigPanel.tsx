import { useState } from 'react';
import type { Config, ConfigUpdate } from '../api';
import { updateConfig } from '../api';

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
  const [saving, setSaving] = useState(false);

  if (!open) return null;

  const handleSave = async () => {
    setSaving(true);
    try {
      const cfg: ConfigUpdate = {
        llm_api_url: url,
        llm_api_key: key || '',
        llm_model: model,
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
          <label>Model</label>
          <input
            type="text"
            value={model}
            onChange={e => setModel(e.target.value)}
            placeholder="gpt-4o"
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
