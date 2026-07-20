import { useState } from 'react';
import { runTestAnalysis, type TestResult, type ConversationMessage } from '../api';

export default function TestPanel() {
  const [exchange, setExchange] = useState('');
  const [symbol, setSymbol] = useState('');
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<TestResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setResult(null);

    if (!content.trim()) {
      setError('Please enter a news message.');
      return;
    }

    setLoading(true);
    try {
      const res = await runTestAnalysis({
        exchange: exchange,
        symbol: symbol.trim() || '',
        content: content.trim(),
        source: 'manual-test',
      });
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Analysis failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ display: 'flex', height: '100%', gap: 12, padding: 12 }}>
      {/* Left: input form */}
      <div className="card" style={{ width: 380, flexShrink: 0, display: 'flex', flexDirection: 'column' }}>
        <h3>Test Analysis</h3>
        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', flex: 1 }}>
          <div className="form-group">
            <label>Exchange</label>
            <select value={exchange} onChange={e => setExchange(e.target.value)} style={{ width: '100%' }}>
              <option value="">— Auto / None —</option>
              <option value="AU">AU — Australia (ASX)</option>
              <option value="US">US — United States</option>
              <option value="HK">HK — Hong Kong</option>
              <option value="SZ">SZ — Shenzhen</option>
              <option value="SH">SH — Shanghai</option>
              <option value="NL">NL — Netherlands</option>
            </select>
          </div>

          <div className="form-group">
            <label>Symbol (optional)</label>
            <input
              type="text"
              value={symbol}
              onChange={e => setSymbol(e.target.value)}
              placeholder="e.g. AAPL"
              style={{ width: '100%', textTransform: 'uppercase' }}
            />
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>
              Leave empty if Exchange is set — model will auto-pick the most impacted stock.
            </div>
          </div>

          <div className="form-group" style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
            <label>News Content</label>
            <textarea
              value={content}
              onChange={e => setContent(e.target.value)}
              placeholder="Enter any news or message to analyze..."
              style={{
                width: '100%',
                flex: 1,
                minHeight: 120,
                fontFamily: 'inherit',
                fontSize: 13,
                padding: 8,
                resize: 'vertical',
              }}
            />
          </div>

          <button type="submit" className="btn btn-primary" disabled={loading}>
            {loading ? 'Analyzing...' : 'Run Analysis'}
          </button>

          {error && <div className="alert alert-error" style={{ marginTop: 8 }}>{error}</div>}
        </form>
      </div>

      {/* Right: results */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 12, overflow: 'auto' }}>
        {result ? (
          <>
            {/* Mode banner */}
            <div className="card" style={{
              background: result.mode === 'llm' ? '#e8f5e9' : '#fff8e1',
              border: `1px solid ${result.mode === 'llm' ? '#4caf50' : '#ff9800'}`,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 18 }}>{result.mode === 'llm' ? '🤖' : '🔑'}</span>
                <div>
                  <strong>{result.mode === 'llm' ? 'LLM Analysis' : 'Keyword Fallback'}</strong>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                    {result.mode === 'llm'
                      ? 'Sentiment from LLM via API call'
                      : 'LLM disabled — using keyword matching. Configure LLM in Settings to enable AI analysis.'}
                  </div>
                </div>
              </div>
            </div>

            {/* Signal result */}
            <div className="card">
              <h3>Signal</h3>
              <div className="stats" style={{ marginBottom: 12 }}>
                <div className="stat">
                  <div className="val" style={{ fontSize: 18, color: result.trade_action === 'BUY' ? 'var(--success)' : result.trade_action === 'SHORT' ? 'var(--danger)' : 'var(--text-muted)' }}>
                    {result.trade_action}
                  </div>
                  <div className="lbl">Trade Action</div>
                </div>
                <div className="stat">
                  <div className="val">{result.sentiment}</div>
                  <div className="lbl">Sentiment</div>
                </div>
                <div className="stat">
                  <div className="val">{(result.confidence_score * 100).toFixed(0)}%</div>
                  <div className="lbl">Confidence</div>
                </div>
                {result.selected_symbol && (
                  <div className="stat">
                    <div className="val" style={{ fontSize: 14, fontFamily: 'monospace' }}>{result.selected_symbol}</div>
                    <div className="lbl">Selected Stock</div>
                  </div>
                )}
                {result.trade_id && (
                  <div className="stat">
                    <div className="val" style={{ fontSize: 12, fontFamily: 'monospace' }}>{result.trade_id.slice(0, 8)}</div>
                    <div className="lbl">Trade ID</div>
                  </div>
                )}
              </div>
              <div style={{ fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.6 }}>
                {result.reasoning}
              </div>
            </div>

            {/* Raw output */}
            <div className="card">
              <h3>Raw Analysis Output</h3>
              <pre style={{
                fontSize: 12,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
                maxHeight: 200,
                overflow: 'auto',
                background: 'var(--bg)',
                padding: 8,
                borderRadius: 4,
              }}>
                {result.llm_response || '(empty)'}
              </pre>
            </div>

            {/* Conversation */}
            {result.conversation && result.conversation.length > 0 && (
              <div className="card">
                <h3>Conversation ({result.conversation.length} messages)</h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 400, overflow: 'auto' }}>
                  {result.conversation.map((msg: ConversationMessage, i: number) => (
                    <div key={i} style={{
                      padding: 8,
                      borderRadius: 4,
                      background: msg.role === 'system' ? '#f0f4ff' :
                                  msg.role === 'tool' ? '#fff8e1' :
                                  msg.role === 'assistant' ? '#f5f5f5' : '#fff',
                      border: '1px solid var(--border)',
                      fontSize: 12,
                    }}>
                      <div style={{ fontWeight: 600, marginBottom: 4, color: 'var(--text-muted)', fontSize: 10, textTransform: 'uppercase' }}>
                        {msg.label || msg.role}
                      </div>
                      <pre style={{
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word',
                        margin: 0,
                        fontFamily: 'inherit',
                      }}>
                        {msg.content}
                      </pre>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        ) : (
          <div className="card" style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <div className="empty">
              <p>Enter a news message and click "Run Analysis"</p>
              <p style={{ fontSize: 12, marginTop: 8, color: 'var(--text-muted)' }}>
                The analysis bypasses RabbitMQ — results appear here directly.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
