const BASE = '/api';

// ── Types ────────────────────────────────────────────

export interface HealthStatus {
  rabbitmq: boolean;
  database: boolean;
  llm_configured: boolean;
  llm_enabled: boolean;
}

export interface NewsItem {
  id: string;
  content: string;
  source: string;
  symbol: string;
  timestamp: string;
}

export interface Signal {
  id: string;
  news_id: string;
  sentiment: string;
  confidence_score: number;
  reasoning: string;
  trade_action: string;
  symbol: string;
  timestamp: string;
  trade_id: string | null;
}

export interface ConversationRound {
  round: number;
  prompt: string;
  response: string;
  type: 'tool_call' | 'final';
}

export interface AnalysisResult {
  id: string;
  news_id: string;
  prompt: string;
  llm_response: string;
  conversation: ConversationRound[];
  sentiment: string;
  confidence_score: number;
  reasoning: string;
  timestamp: string;
}

export interface Position {
  id: string;
  news_id: string;
  sentiment_result_id: string;
  action: string;
  symbol: string;
  entry_price: number;
  status: string;
  pnl: number;
  created_at: string;
  closed_at: string | null;
}

export interface PnLSummary {
  unrealized_pnl: number;
  realized_pnl: number;
  total_pnl: number;
  open_positions: number;
  total_trades: number;
}

export interface Config {
  llm_api_url: string;
  llm_api_key_masked: string;
  llm_model: string;
  llm_enabled: boolean;
  mcp_server_url: string;
}

export interface ConfigUpdate {
  llm_api_url: string;
  llm_api_key: string;
  llm_model: string;
  llm_enabled: boolean;
  mcp_server_url: string;
}

// ── API functions ─────────────────────────────────────

export async function fetchHealth(): Promise<HealthStatus> {
  const res = await fetch(`${BASE}/health`);
  return res.json();
}

export async function fetchSignals(limit = 100): Promise<Signal[]> {
  const res = await fetch(`${BASE}/signals?limit=${limit}`);
  const data = await res.json();
  return data.signals || [];
}

export async function fetchSignal(id: string): Promise<AnalysisResult> {
  const res = await fetch(`${BASE}/signals/${id}`);
  return res.json();
}

export async function fetchNews(limit = 100, offset = 0): Promise<NewsItem[]> {
  const res = await fetch(`${BASE}/news?limit=${limit}&offset=${offset}`);
  const data = await res.json();
  return data.news || [];
}

export async function fetchNewsItem(id: string): Promise<NewsItem> {
  const res = await fetch(`${BASE}/news/${id}`);
  return res.json();
}

export async function fetchPositions(): Promise<{ positions: Position[]; pnl: PnLSummary }> {
  const res = await fetch(`${BASE}/positions`);
  return res.json();
}

export async function fetchTrades(limit = 50): Promise<{ trades: Position[] }> {
  const res = await fetch(`${BASE}/trades?limit=${limit}`);
  return res.json();
}

export async function fetchConfig(): Promise<Config> {
  const res = await fetch(`${BASE}/config`);
  return res.json();
}

export async function updateConfig(cfg: ConfigUpdate): Promise<Config> {
  const res = await fetch(`${BASE}/config`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(cfg),
  });
  return res.json();
}

export async function toggleLlm(): Promise<{ llm_enabled: boolean }> {
  const res = await fetch(`${BASE}/config/toggle-llm`, { method: 'POST' });
  return res.json();
}
