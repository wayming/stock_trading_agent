interface Props {
  rabbitmqOk: boolean;
  llmConfigured: boolean;
  llmEnabled: boolean;
  configOpen: boolean;
  onToggleConfig: () => void;
}

export default function Header({ rabbitmqOk, llmConfigured, llmEnabled, configOpen, onToggleConfig }: Props) {
  const llmLabel = llmConfigured
    ? (llmEnabled ? 'LLM On' : 'LLM Off')
    : 'LLM Not set';
  const llmDotClass = llmConfigured && llmEnabled ? 'ok' : 'err';

  return (
    <header>
      <h1>Stock Trading Agent</h1>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
        <span style={{ fontSize: 13, display: 'flex', alignItems: 'center', marginRight: 12 }}>
          <span className={`dot ${llmDotClass}`} />
          {llmLabel}
        </span>
        <button className="header-btn" onClick={onToggleConfig}>
          {configOpen ? '✕ Close' : '⚙ Config'}
        </button>
      </div>
    </header>
  );
}
