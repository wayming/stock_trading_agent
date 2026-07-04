import type { AnalysisResult } from '../api';

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

interface Props {
  analysis: AnalysisResult | null;
}

export default function AnalysisColumn({ analysis }: Props) {
  if (!analysis) {
    return (
      <div className="col">
        <div className="card" style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
          <h3>Analysis Results</h3>
          <div className="empty">
            <p style={{ fontSize: 14 }}>Select a signal to view analysis</p>
            <p style={{ fontSize: 12, marginTop: 8 }}>Click a trading signal in the first column</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="col">
      <div className="card" style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
        <h3>Analysis Result</h3>

        <div className="analysis-result-header">
          <span className={sentimentClass(analysis.sentiment)} style={{ fontSize: 14, fontWeight: 700 }}>
            {analysis.sentiment}
          </span>
          <span style={{ fontSize: 13, color: '#555' }}>
            Confidence: {(analysis.confidence_score * 100).toFixed(1)}%
          </span>
          {analysis.reasoning && (
            <span style={{ fontSize: 12, color: '#666', flex: '1 0 100%', marginTop: 4 }}>
              {analysis.reasoning}
            </span>
          )}
        </div>

        <div className="col-scroll" style={{ flex: 1 }}>
          <div className="analysis-section">
            <h4>Prompt Sent</h4>
            <pre>{analysis.prompt}</pre>
          </div>

          <div className="analysis-section">
            <h4>LLM Response</h4>
            <pre>{analysis.llm_response}</pre>
          </div>
        </div>
      </div>
    </div>
  );
}
