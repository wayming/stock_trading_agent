import { useEffect, useRef } from 'react';
import type { NewsItem } from '../api';

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
  news: NewsItem[];
  highlightedNewsId: string | null;
}

export default function NewsColumn({ news, highlightedNewsId }: Props) {
  const refMap = useRef<Map<string, HTMLDivElement>>(new Map());

  useEffect(() => {
    if (!highlightedNewsId) return;
    const el = refMap.current.get(highlightedNewsId);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }, [highlightedNewsId]);

  const setRef = (id: string) => (el: HTMLDivElement | null) => {
    if (el) refMap.current.set(id, el);
    else refMap.current.delete(id);
  };

  return (
    <div className="col">
      <div className="card" style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
        <h3 style={{ margin: 0, marginBottom: 10 }}>News Feed ({news.length})</h3>

        {news.length === 0 ? (
          <div className="empty">
            <p>No news yet</p>
            <p style={{ fontSize: 12, marginTop: 8 }}>Push news to RabbitMQ queue to see results</p>
          </div>
        ) : (
          <div className="col-scroll" style={{ flex: 1 }}>
            {news.map(item => (
              <div
                key={item.id}
                ref={setRef(item.id)}
                className={`news-item ${highlightedNewsId === item.id ? 'news-highlight' : ''}`}
              >
                <div className="news-header">
                  {item.source && (
                    <span className="badge" style={{ background: '#e0e7ff', color: '#3730a3' }}>
                      {item.source}
                    </span>
                  )}
                  {item.symbol && (
                    <span style={{ fontFamily: 'monospace', fontWeight: 600, fontSize: 13 }}>
                      {item.symbol}
                    </span>
                  )}
                  <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                    {timeAgo(item.timestamp)}
                  </span>
                </div>
                <div className="news-content" title={item.content}>
                  {item.content}
                </div>
                <div className="news-meta">
                  <span>ID: {item.id.slice(0, 8)}...</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
