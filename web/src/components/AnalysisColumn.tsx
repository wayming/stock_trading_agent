import { useMemo } from 'react';
import type { AnalysisResult, ConversationMessage, NewsItem } from '../api';

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

// ── styling per role ─────────────────────────────────

const ROLE_STYLE: Record<string, { bg: string; border: string; labelColor: string; contentBg: string }> = {
  system:  { bg: '#f0f4ff', border: '#c4d7f7', labelColor: '#3b5998', contentBg: '#f8faff' },
  user:    { bg: '#f0fff4', border: '#b7e4c7', labelColor: '#1e7e34', contentBg: '#f8fff8' },
  assistant: { bg: '#fffbe6', border: '#e6d87e', labelColor: '#8a6d00', contentBg: '#fffef5' },
  tool:    { bg: '#fff0f5', border: '#f0c4d8', labelColor: '#9b1d5a', contentBg: '#fffafc' },
};

// ── conversation chat log ────────────────────────────

function ConversationLog({ messages }: { messages: ConversationMessage[] }) {
  if (!messages || messages.length === 0) return null;

  return (
    <>
      <h4 style={{ marginTop: 16, marginBottom: 8, color: '#333', fontWeight: 700, fontSize: 13 }}>
        LLM Conversation ({messages.length} message{messages.length > 1 ? 's' : ''})
      </h4>
      {messages.map((msg, idx) => {
        const style = ROLE_STYLE[msg.role] || ROLE_STYLE.system;
        return (
          <div key={idx} style={{
            marginBottom: 8,
            border: `1px solid ${style.border}`,
            borderRadius: 6,
            overflow: 'hidden',
          }}>
            {/* Label bar */}
            <div style={{
              padding: '6px 12px',
              background: style.bg,
              fontSize: 11,
              fontWeight: 700,
              color: style.labelColor,
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
            }}>
              <span>{msg.label}</span>
              <span style={{ fontSize: 9, opacity: 0.5 }}>#{idx + 1}</span>
            </div>
            {/* Content */}
            <pre style={{
              background: style.contentBg,
              padding: 10,
              borderRadius: 0,
              fontSize: 12,
              lineHeight: 1.6,
              color: '#222',
              maxHeight: 300,
              overflow: 'auto',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              margin: 0,
            }}>{msg.content}</pre>
          </div>
        );
      })}
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

          {/* ── Conversation (chat log) ── */}
          {hasConversation ? (
            <ConversationLog messages={analysis.conversation} />
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
