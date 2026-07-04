interface Props {
  rabbitmqOk: boolean;
  llmConfigured: boolean;
  configOpen: boolean;
  onToggleConfig: () => void;
}

export default function Header({ rabbitmqOk, llmConfigured, configOpen, onToggleConfig }: Props) {
  return (
    <header>
      <h1>Stock Trading Agent</h1>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
        <span style={{ fontSize: 13, display: 'flex', alignItems: 'center', marginRight: 12 }}>
          <span className={`dot ${llmConfigured ? 'ok' : 'err'}`} />
          LLM {llmConfigured ? 'Configured' : 'Not set'}
        </span>
        <button className="header-btn" onClick={onToggleConfig}>
          {configOpen ? '✕ Close' : '⚙ Config'}
        </button>
      </div>
    </header>
  );
}
