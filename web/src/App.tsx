import { useState, useEffect, useCallback } from 'react';
import {
  fetchHealth, fetchSignals, fetchNews, fetchPositions, fetchConfig,
  type Signal, type NewsItem, type AnalysisResult, type Config,
} from './api';
import Header from './components/Header';
import SignalColumn from './components/SignalColumn';
import NewsColumn from './components/NewsColumn';
import AnalysisColumn from './components/AnalysisColumn';
import ConfigPanel from './components/ConfigPanel';

const MAX_ITEMS = 200;

export default function App() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [news, setNews] = useState<NewsItem[]>([]);
  const [analyses, setAnalyses] = useState<AnalysisResult[]>([]);
  const [selectedSignalId, setSelectedSignalId] = useState<string | null>(null);
  const [configOpen, setConfigOpen] = useState(false);
  const [config, setConfig] = useState<Config | null>(null);
  const [positionsOpen, setPositionsOpen] = useState(0);
  const [totalPnl, setTotalPnl] = useState(0);
  const [health, setHealth] = useState({ rabbitmq: false, llm_configured: false });

  // Initial data load
  useEffect(() => {
    fetchHealth().then(h => setHealth({ rabbitmq: h.rabbitmq, llm_configured: h.llm_configured }));
    fetchConfig().then(c => setConfig(c));
    fetchSignals(100).then(s => setSignals(s.slice(0, MAX_ITEMS)));
    fetchNews(100, 0).then(n => setNews(n.slice(0, MAX_ITEMS)));
    fetchPositions().then(p => {
      setPositionsOpen(p.pnl.open_positions);
      setTotalPnl(p.pnl.total_pnl);
    });
  }, []);

  // SSE stream
  useEffect(() => {
    const es = new EventSource('/api/stream');

    es.addEventListener('signal', (e: MessageEvent) => {
      const signal: Signal = JSON.parse(e.data);
      setSignals(prev => [signal, ...prev].slice(0, MAX_ITEMS));
      // Auto-refresh positions on trade
      fetchPositions().then(p => {
        setPositionsOpen(p.pnl.open_positions);
        setTotalPnl(p.pnl.total_pnl);
      });
    });

    es.addEventListener('news', (e: MessageEvent) => {
      const item: NewsItem = JSON.parse(e.data);
      setNews(prev => [item, ...prev].slice(0, MAX_ITEMS));
    });

    es.addEventListener('analysis', (e: MessageEvent) => {
      const analysis: AnalysisResult = JSON.parse(e.data);
      setAnalyses(prev => [analysis, ...prev].slice(0, MAX_ITEMS));
    });

    es.onerror = () => {
      es.close();
      // Reconnect after 3 seconds
      setTimeout(() => {
        // EventSource will auto-reconnect, but we help by polling health
        fetchHealth().then(h =>
          setHealth({ rabbitmq: h.rabbitmq, llm_configured: h.llm_configured })
        );
      }, 3000);
    };

    return () => es.close();
  }, []);

  // Periodic health + positions refresh
  useEffect(() => {
    const t = setInterval(() => {
      fetchHealth().then(h =>
        setHealth({ rabbitmq: h.rabbitmq, llm_configured: h.llm_configured })
      );
      fetchPositions().then(p => {
        setPositionsOpen(p.pnl.open_positions);
        setTotalPnl(p.pnl.total_pnl);
      });
    }, 10000);
    return () => clearInterval(t);
  }, []);

  const handleSelectSignal = useCallback((id: string) => {
    setSelectedSignalId(prev => (prev === id ? null : id));
  }, []);

  const handleConfigSaved = useCallback((cfg: Config) => {
    setConfig(cfg);
    setHealth(prev => ({ ...prev, llm_configured: true }));
  }, []);

  // Derive highlighted news ID and selected analysis from selectedSignalId
  const selectedSignal = signals.find(s => s.id === selectedSignalId);
  const highlightedNewsId = selectedSignal?.news_id || null;
  const selectedAnalysis = selectedSignal
    ? analyses.find(a => a.news_id === selectedSignal.news_id) || null
    : null;

  return (
    <>
      <Header
        rabbitmqOk={health.rabbitmq}
        llmConfigured={health.llm_configured}
        configOpen={configOpen}
        onToggleConfig={() => setConfigOpen(prev => !prev)}
      />

      <div className="layout">
        {/* Column 1: Trading Signals */}
        <SignalColumn
          signals={signals}
          selectedId={selectedSignalId}
          onSelect={handleSelectSignal}
          positionsOpen={positionsOpen}
          totalPnl={totalPnl}
        />

        {/* Column 2: News Feed */}
        <NewsColumn
          news={news}
          highlightedNewsId={highlightedNewsId}
        />

        {/* Column 3: Analysis Results */}
        <AnalysisColumn
          analysis={selectedSignal
            ? analyses.find(a => a.news_id === selectedSignal.news_id) || null
            : null}
        />
      </div>

      <ConfigPanel
        config={config}
        open={configOpen}
        onClose={() => setConfigOpen(false)}
        onSaved={handleConfigSaved}
      />
    </>
  );
}
