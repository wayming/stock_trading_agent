import { useMemo } from 'react';
import type { AnalysisResult, ConversationRound, NewsItem } from '../api';

// ── helpers ──────────────────────────────────────────

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

function extractField(llmResponse: string, field: string): string | null {
  try {
    const obj = JSON.parse(llmResponse);
    if (obj && typeof obj === 'object' && obj[field]) {
      return String(obj[field]);
    }
  } catch {
    const match = llmResponse.match(/\{[\s\S]*\}/);
    if (match) {
      try {
        const obj = JSON.parse(match[0]);
        if (obj && typeof obj === 'object' && obj[field]) {
          return String(obj[field]);
        }
      } catch { /* ignore */ }
    }
  }
  return null;
}

// ── conversation round display ───────────────────────

function ConversationRounds({ rounds }: { rounds: ConversationRound[] }) {
  if (!rounds || rounds.length === 0) return null;

  return (
    <>
      <h4 style={{ marginTop: 16, marginBottom: 8, color: '#333', fontWeight: 700, fontSize: 13 }}>
        LLM Conversation ({rounds.length} round{rounds.length > 1 ? 's' : ''})
      </h4>
      {rounds.map((r) => (
        <div key={r.round} style={{
          marginBottom: 12,
          border: '1px solid #ccc',
          borderRadius: 6,
          overflow: 'hidden',
        }}>
          {/* Round header */}
          <div style={{
            padding: '8px 12px',
            background: r.type === 'tool_call' ? '#fff3cd' : '#d4edda',
            fontSize: 12,
            fontWeight: 700,
            color: '#333',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}>
            <span>Round {r.round}</span>
            <span style={{
              padding: '2px 10px',
              borderRadius: 8,
              fontSize: 11,
              fontWeight: 700,
              background: r.type === 'tool_call' ? '#e6a700' : '#1e7e34',
              color: '#fff',
            }}>
              {r.type === 'tool_call' ? 'Tool Call' : 'Final'}
            </span>
          </div>

          {/* Prompt sent to LLM */}
          <div style={{ padding: '8px 12px' }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: '#555', marginBottom: 4, textTransform: 'uppercase', letterSpacing: 0.5 }}>
              Prompt Sent
            </div>
            <pre style={{
              background: '#f5f5f5',
              padding: 10,
              borderRadius: 4,
              fontSize: 12,
              lineHeight: 1.6,
              color: '#222',
              maxHeight: 250,
              overflow: 'auto',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              margin: 0,
              border: '1px solid #e0e0e0',
            }}>{r.prompt}</pre>
          </div>

          {/* Response from LLM */}
          <div style={{
            padding: '8px 12px',
            borderTop: '1px solid #ddd',
          }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: '#555', marginBottom: 4, textTransform: 'uppercase', letterSpacing: 0.5 }}>
              Response
            </div>
            <pre style={{
              background: r.type === 'tool_call' ? '#fffbe6' : '#f0fdf4',
              padding: 10,
              borderRadius: 4,
              fontSize: 12,
              lineHeight: 1.6,
              color: '#222',
              maxHeight: 250,
              overflow: 'auto',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              margin: 0,
              border: '1px solid #e0e0e0',
            }}>{r.response}</pre>
          </div>
        </div>
      ))}
    </>
  );
}

// ── main component ──────────────────────────────────

interface Props {
  analysis: AnalysisResult | null;
  newsItem: NewsItem | null;
}

export default function AnalysisColumn({ analysis, newsItem }: Props) {
  const translate = useMemo(
    () => (analysis ? extractField(analysis.llm_response, 'translate') : null),
    [analysis],
  );

  if (!analysis) {
    return (
      <div className="col">
        <div className="card" style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
          <h3>Analysis Results</h3>
          <div className="empty">
            <p style={{ fontSize: 14 }}>Analysis pending…</p>
            <p style={{ fontSize: 12, marginTop: 8 }}>Waiting for LLM response via SSE stream</p>
          </div>
        </div>
      </div>
    );
  }

  const hasConversation = analysis.conversation && analysis.conversation.length > 0;

  return (
    <div className="col">
      <div className="card" style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
        <h3>Analysis Result</h3>

        {/* ── Summary header ── */}
        <div className="analysis-result-header">
          <span className={sentimentClass(analysis.sentiment)} style={{ fontSize: 14, fontWeight: 700 }}>
            {analysis.sentiment}
          </span>
          <span style={{ fontSize: 13, color: '#555' }}>
            Confidence: {(analysis.confidence_score * 100).toFixed(1)}%
          </span>
          {analysis.reasoning && (
            <span style={{ fontSize: 12, color: '#444', flex: '1 0 100%', marginTop: 4 }}>
              {analysis.reasoning}
            </span>
          )}
        </div>

        <div className="col-scroll" style={{ flex: 1 }}>
          {/* ── Original News ── */}
          {newsItem && (
            <div className="analysis-section">
              <h4>Original News</h4>
              <div style={{
                background: '#f0f7ff',
                border: '1px solid #c4ddf7',
                borderRadius: 6,
                padding: 10,
                fontSize: 13,
                lineHeight: 1.6,
                color: '#222',
                marginBottom: 8,
              }}>
                {newsItem.source && (
                  <span style={{ fontSize: 11, color: '#555', marginRight: 8 }}>
                    [{newsItem.source}]
                  </span>
                )}
                {newsItem.symbol && (
                  <span style={{ fontFamily: 'monospace', fontWeight: 600, marginRight: 8 }}>
                    {newsItem.symbol}
                  </span>
                )}
                <span style={{ fontSize: 11, color: '#888' }}>
                  {newsItem.timestamp ? new Date(newsItem.timestamp).toLocaleString() : ''}
                </span>
                <div style={{ marginTop: 8, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                  {newsItem.content}
                </div>
              </div>
            </div>
          )}

          {/* ── Translate ── */}
          {translate && (
            <div className="analysis-section">
              <h4>Translate</h4>
              <pre style={{
                background: '#f5f5f5',
                color: '#222',
                border: '1px solid #e0e0e0',
              }}>{translate}</pre>
            </div>
          )}

          {/* ── Conversation Rounds (MCP tool-calling) ── */}
          {hasConversation ? (
            <ConversationRounds rounds={analysis.conversation} />
          ) : (
            <div className="analysis-section">
              <h4>Prompt Sent</h4>
              <pre style={{
                background: '#f5f5f5',
                color: '#222',
                border: '1px solid #e0e0e0',
              }}>{analysis.prompt}</pre>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
