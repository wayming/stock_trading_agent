import type { Signal } from '../api';

function sentimentClass(sentiment: string): string {
  const map: Record<string, string> = {
    '超级利好': 'sentiment-super-bullish',
    '普通利好': 'sentiment-bullish',
    'neutral': 'sentiment-neutral',
    '普通利空': 'sentiment-bearish',
    '超级利空': 'sentiment-super-bearish',
  };
  return map[sentiment] || '';
}

function tradeBadge(action: string) {
  if (action === 'BUY') return <span className="badge badge-buy">BUY</span>;
  if (action === 'SHORT') return <span className="badge badge-short">SHORT</span>;
  return null;
}

function timeAgo(ts: string): string {
  if (!ts) return '';
  const diff = Date.now() - new Date(ts).getTime();
  const sec = Math.floor(diff / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  return `${hr}h ago`;
}

interface Props {
  signals: Signal[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  positionsOpen: number;
  totalPnl: number;
  mqListening: boolean;
  onStartMq: () => void;
  onStopMq: () => void;
}

export default function SignalColumn({ signals, selectedId, onSelect, positionsOpen, totalPnl, mqListening, onStartMq, onStopMq }: Props) {
  return (
    <div className="col">
      <div className="card" style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
          <h3 style={{ margin: 0 }}>Trading Signals ({signals.length})</h3>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span
              className={`dot ${mqListening ? 'ok' : 'err'}`}
              title={mqListening ? 'MQ Listening' : 'MQ Stopped'}
            />
            <span style={{ fontSize: 11, color: 'var(--text-muted)', marginRight: 4 }}>
              {mqListening ? 'Listening' : 'Stopped'}
            </span>
            {mqListening ? (
              <button
                className="header-btn"
                onClick={onStopMq}
                style={{ background: 'var(--danger)', color: '#fff', border: 'none', borderRadius: 4, padding: '3px 10px', fontSize: 11, cursor: 'pointer', fontWeight: 600 }}
              >
                Stop
              </button>
            ) : (
              <button
                className="header-btn"
                onClick={onStartMq}
                style={{ background: 'var(--success)', color: '#fff', border: 'none', borderRadius: 4, padding: '3px 10px', fontSize: 11, cursor: 'pointer', fontWeight: 600 }}
              >
                Start
              </button>
            )}
          </div>
        </div>

        {/* P&L mini summary */}
        <div className="stats" style={{ marginBottom: 10 }}>
          <div className="stat">
            <div className="val">{positionsOpen}</div>
            <div className="lbl">Open Positions</div>
          </div>
          <div className="stat">
            <div className={`val ${totalPnl >= 0 ? 'ok' : 'err'}`}>{totalPnl >= 0 ? '+' : ''}{totalPnl.toFixed(1)}</div>
            <div className="lbl">Total P&L</div>
          </div>
        </div>

        {signals.length === 0 ? (
          <div className="empty">
            <p>No signals yet</p>
            <p style={{ fontSize: 12, marginTop: 8 }}>Waiting for news via RabbitMQ...</p>
          </div>
        ) : (
          <div className="col-scroll" style={{ flex: 1 }}>
            {signals.map(s => (
              <div
                key={s.id}
                className={`signal-item ${selectedId === s.id ? 'selected' : ''}`}
                onClick={() => onSelect(s.id)}
              >
                <div className="signal-header">
                  <span className={sentimentClass(s.sentiment)} style={{ fontSize: 13 }}>
                    {s.sentiment}
                  </span>
                  {tradeBadge(s.trade_action)}
                </div>
                <div className="signal-meta">
                  {s.symbol && <span style={{ fontFamily: 'monospace', fontWeight: 600 }}>{s.symbol}</span>}
                  <span>{(s.confidence_score * 100).toFixed(0)}% confidence</span>
                  <span>{timeAgo(s.timestamp)}</span>
                </div>
                <div className="confidence-bar">
                  <div
                    className={`confidence-fill ${s.confidence_score >= 0.7 ? 'high' : 'low'}`}
                    style={{ width: `${s.confidence_score * 100}%` }}
                  />
                </div>
                {s.reasoning && (
                  <div style={{ fontSize: 12, color: '#666', marginTop: 4, lineHeight: 1.4 }}>
                    {s.reasoning.length > 80 ? s.reasoning.slice(0, 80) + '...' : s.reasoning}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
