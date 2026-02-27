import { useState, useEffect, useRef, useCallback } from 'react';
import {
  Shield, Globe, Activity, Cpu, Terminal, TrendingUp,
  BarChart2, Radio, Wifi, WifiOff, RefreshCw, Zap,
  AlertTriangle, ChevronRight, Sparkles, BookOpen, DollarSign, X
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

// ─────────────────────────────────────  Types
interface LogEntry {
  id: number;
  time: string;
  level: 'INFO' | 'WARN' | 'ERROR' | 'OK';
  domain: string;
  msg: string;
}

interface StatItem {
  label: string;
  value: string;
  delta?: string;
  positive?: boolean;
}
const DOMAIN_TABS = [
  { id: 'all', label: '全览', icon: Globe },
  { id: 'global', label: '全球监控', icon: Shield },
  { id: 'economy', label: '经济', icon: DollarSign },
  { id: 'technology', label: '技术', icon: Cpu },
  { id: 'academic', label: '学术', icon: BookOpen },
];

const DOMAIN_STATS_FALLBACK: StatItem[] = [
  { label: '地缘事件', value: '—', delta: '', positive: true },
  { label: '经济信号', value: '—', delta: '', positive: true },
  { label: '科技热搜', value: '—', delta: '', positive: true },
  { label: '学术论文', value: '—', delta: '', positive: true },
];



// ─────────────────────────────────────  Helpers
function now() {
  return new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function domainColor(d: string) {
  const map: Record<string, string> = {
    'global': '#ff5c00', 'economy': '#3357FF', 'technology': '#33FF57', 'academic': '#c084fc'
  };
  return map[d] ?? '#6b7280';
}

function levelColor(l: string) {
  return l === 'ERROR' ? '#ff4444' : l === 'WARN' ? '#fbbf24' : l === 'OK' ? '#34d399' : '#6ee7f7';
}

// ─────────────────────────────────────  Sub components
function HeatBar({ value }: { value: number }) {
  return (
    <div style={{ flex: 1, height: 6, background: 'rgba(255,255,255,0.08)', border: '1px solid #333', borderRadius: 2, overflow: 'hidden' }}>
      <div style={{ height: '100%', width: `${value}%`, background: `linear-gradient(90deg,#ff5c00,#ffaa00)`, transition: 'width 0.6s ease' }} />
    </div>
  );
}

function SourceBadge({ status }: { status: string }) {
  const cfg = {
    live: { bg: '#052e16', color: '#34d399', label: '● 实时' },
    cached: { bg: '#1c1a07', color: '#fbbf24', label: '○ 缓存' },
    unavailable: { bg: '#1f0707', color: '#f87171', label: '✕ 离线' },
  }[status] ?? { bg: '#111', color: '#888', label: '？' };
  return (
    <span style={{ padding: '1px 7px', borderRadius: 2, background: cfg.bg, color: cfg.color, fontSize: 11, fontWeight: 700, border: `1px solid ${cfg.color}` }}>
      {cfg.label}
    </span>
  );
}

// ─────────────────────────────────────  Panels
function StatBar({ stats }: { stats: StatItem[] }) {
  return (
    <div style={{ display: 'flex', gap: 12, padding: '0 0 16px' }}>
      {stats.map(s => (
        <div key={s.label} style={{ flex: 1, background: 'rgba(255,255,255,0.03)', border: '1.5px solid #2a2a2a', padding: '12px 14px' }}>
          <div style={{ fontSize: 11, color: '#888', marginBottom: 4, fontWeight: 600, letterSpacing: 1 }}>{s.label}</div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
            <span style={{ fontSize: 28, fontWeight: 900, lineHeight: 1 }}>{s.value}</span>
            {s.delta && <span style={{ fontSize: 12, fontWeight: 700, color: s.positive ? '#34d399' : '#f87171' }}>{s.delta}</span>}
          </div>
        </div>
      ))}
    </div>
  );
}

function HotPanelItems({ items }: { items: any[] }) {
  const filtered = items;
  return (
    <div>
      {filtered.map(item => (
        <a
          key={item.rank}
          href={item.url}
          target="_blank"
          rel="noopener noreferrer"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            padding: '9px 0',
            borderBottom: '1px solid #1a1a1a',
            textDecoration: 'none',
            color: 'inherit',
            cursor: item.url ? 'pointer' : 'default',
            transition: 'background 0.2s'
          }}
          onMouseEnter={(e) => { if (item.url) e.currentTarget.style.background = 'rgba(255,255,255,0.03)'; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
        >
          <span style={{ width: 22, textAlign: 'center', fontWeight: 900, fontSize: 13, color: item.rank <= 3 ? '#ff5c00' : '#555' }}>
            {item.rank}
          </span>
          <span style={{ flex: 1, fontSize: 13, fontWeight: 600, lineHeight: 1.3 }}>{item.title}</span>
          <span style={{ fontSize: 11, color: domainColor(item.raw_domain), fontWeight: 700, minWidth: 32 }}>{item.domain}</span>
          <HeatBar value={item.heat} />
          <span style={{ fontSize: 11, color: '#666', minWidth: 28, textAlign: 'right' }}>{item.heat}</span>
        </a>
      ))}
      {filtered.length === 0 && <div style={{ padding: '20px 0', color: '#555', textAlign: 'center' }}>暂无数据</div>}
    </div>
  );
}

function SourcePanelSources({ sources }: { sources: any[] }) {
  return (
    <div>
      {sources.map(s => (
        <div key={s.source_id || s.name} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid #1a1a1a' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <SourceBadge status={s.status} />
            <span style={{ fontSize: 13, color: '#e0e0e0' }}>{s.name}</span>
          </div>
          <span style={{ fontSize: 12, color: '#666' }}>{s.last_latency_ms ? `${s.last_latency_ms}ms` : '—'}</span>
        </div>
      ))}
      {sources.length === 0 && <div style={{ padding: '20px 0', color: '#555', textAlign: 'center' }}>暂无源</div>}
    </div>
  );
}

// ─────────────────────────────────────  Panel container with header
interface PanelBoxProps {
  title: string;
  icon: React.ReactNode;
  badge?: string;
  badgeColor?: string;
  count?: number;
  children: React.ReactNode;
  style?: React.CSSProperties;
  actions?: React.ReactNode;
}

function PanelBox({ title, icon, badge, badgeColor = '#34d399', count, children, style, actions }: PanelBoxProps) {
  return (
    <div style={{ background: '#0c0c0c', border: '2px solid #222', display: 'flex', flexDirection: 'column', ...style }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 14px', borderBottom: '2px solid #222', background: '#111' }}>
        <span style={{ color: '#aaa', display: 'flex' }}>{icon}</span>
        <span style={{ fontWeight: 800, fontSize: 13, letterSpacing: 0.5, flex: 1 }}>{title}</span>
        {badge && (
          <span style={{ fontSize: 10, fontWeight: 700, color: badgeColor, border: `1px solid ${badgeColor}`, padding: '1px 6px', letterSpacing: 0.5 }}>
            {badge}
          </span>
        )}
        {count !== undefined && (
          <span style={{ fontSize: 12, color: '#666', fontWeight: 700 }}>{count}</span>
        )}
        {actions}
      </div>
      <div style={{ flex: 1, overflow: 'auto', padding: '0 14px 12px' }}>
        {children}
      </div>
    </div>
  );
}

// ── AI Summary Panel ───────────────────────────────────
function AISummaryPanel({ summary, loading, onRefresh }: { summary: string, loading: boolean, onRefresh: () => void }) {
  const [displayText, setDisplayText] = useState('');
  const [index, setIndex] = useState(0);

  useEffect(() => {
    if (loading) {
      setDisplayText('');
      setIndex(0);
      return;
    }
    if (index < summary.length) {
      const timer = setTimeout(() => {
        setDisplayText(prev => prev + summary[index]);
        setIndex(prev => prev + 1);
      }, 15);
      return () => clearTimeout(timer);
    }
  }, [index, summary, loading]);

  return (
    <div style={{
      background: 'rgba(255, 92, 0, 0.03)',
      border: '1.5px solid rgba(255, 92, 0, 0.2)',
      padding: '16px',
      marginBottom: '20px',
      position: 'relative',
      overflow: 'hidden'
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <Sparkles size={16} style={{ color: '#ff5c00' }} />
        <span style={{ fontWeight: 900, fontSize: 13, letterSpacing: 1, color: '#ff5c00' }}>AI 智能情报综述</span>
        <div style={{ flex: 1 }} />
        <button
          onClick={onRefresh}
          disabled={loading}
          style={{
            background: 'none', border: '1px solid #333', color: '#888',
            fontSize: 10, padding: '2px 8px', cursor: 'pointer',
            display: 'flex', alignItems: 'center', gap: 4
          }}
        >
          <RefreshCw size={10} className={loading ? 'animate-spin' : ''} />
          {loading ? '分析中...' : '重新生成'}
        </button>
      </div>

      <div style={{
        fontSize: 13, color: '#c9d1d9', lineHeight: 1.6, minHeight: '60px',
        fontFamily: 'var(--font-main)',
      }} className="markdown-content">
        {loading ? (
          <div style={{ display: 'flex', gap: 4, alignItems: 'center', color: '#555' }}>
            <div className="pulse-dot" style={{ width: 4, height: 4, background: '#ff5c00', borderRadius: '50%' }} />
            <span>正在深度分析全网实时动态...</span>
          </div>
        ) : (
          displayText ? (
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {displayText}
            </ReactMarkdown>
          ) : '点击“重新生成”以获取最新情报动态分析。'
        )}
      </div>

      {/* Subtle decorative elements */}
      <div style={{
        position: 'absolute', right: -10, bottom: -10, opacity: 0.05, pointerEvents: 'none'
      }}>
        <Zap size={80} color="#ff5c00" strokeWidth={1} />
      </div>
    </div>
  );
}

// ─────────────────────────────────────  Console
import { motion, AnimatePresence } from 'framer-motion';

function ConsolePanel({ logs, onClear }: { logs: LogEntry[]; onClear: () => void }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const userScrolledRef = useRef(false);

  // Auto-scroll logic: only scroll if the user is already at the bottom
  useEffect(() => {
    const container = scrollRef.current;
    if (container && !userScrolledRef.current) {
      container.scrollTo({
        top: container.scrollHeight,
        behavior: 'smooth'
      });
    }
  }, [logs]);

  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const target = e.currentTarget;
    const isAtBottom = target.scrollHeight - target.scrollTop <= target.clientHeight + 50;
    userScrolledRef.current = !isAtBottom;
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: '#070707', border: '2px solid #222' }}>
      {/* Console header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 14px', borderBottom: '2px solid #1a1a1a', background: '#0f0f0f' }}>
        <Terminal size={14} style={{ color: '#34d399' }} />
        <span style={{ fontWeight: 800, fontSize: 13, letterSpacing: 0.5, flex: 1 }}>实时情报流</span>
        <span style={{ animation: 'pulse 1.5s infinite', display: 'flex', alignItems: 'center', gap: 4, fontSize: 10, color: '#34d399', fontWeight: 700 }}>
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#34d399', display: 'inline-block' }} />
          LIVE
        </span>
        <button onClick={onClear} style={{ background: 'none', border: 'none', color: '#555', cursor: 'pointer', padding: 2 }} title="清空">
          <X size={13} />
        </button>
      </div>

      {/* Log list */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        style={{ flex: 1, overflow: 'auto', padding: '8px 0', fontFamily: 'monospace', fontSize: 12, scrollbarGutter: 'stable' }}
      >
        <AnimatePresence initial={false}>
          {logs.map(log => (
            <motion.div
              key={log.id}
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.2, ease: "easeOut" }}
              style={{
                display: 'flex', alignItems: 'flex-start', gap: 6, padding: '3px 12px', lineHeight: 1.45,
                background: log.level === 'ERROR' ? 'rgba(255,68,68,0.04)' : 'transparent'
              }}
            >
              <span style={{ color: '#555', minWidth: 72, flexShrink: 0, opacity: 0.8 }}>{log.time}</span>
              <span style={{ minWidth: 40, textAlign: 'center', fontWeight: 700, color: levelColor(log.level), flexShrink: 0 }}>{log.level}</span>
              <span style={{ minWidth: 48, color: '#666', flexShrink: 0 }}>[{log.domain}]</span>
              <span style={{ color: '#c9d1d9', wordBreak: 'break-all' }}>{log.msg}</span>
            </motion.div>
          ))}
        </AnimatePresence>

        {/* Blinking cursor / Prompt line */}
        <div style={{ padding: '4px 12px', display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ color: '#34d399', fontWeight: 700, opacity: 0.7 }}>{'>'}</span>
          <motion.span
            animate={{ opacity: [1, 0, 1] }}
            transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
            style={{ width: 8, height: 14, background: '#34d399', display: 'inline-block' }}
          />
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────  Main App ─────────────────────────────────────
const API_BASE = 'http://localhost:5001';

export default function App() {
  const [activeTab, setActiveTab] = useState('all');
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [connected, setConnected] = useState(false);
  const [aiSummary, setAiSummary] = useState('');
  const [isSummarizing, setIsSummarizing] = useState(false);
  const [totalItems, setTotalItems] = useState(0);
  const [sidebarTab, setSidebarTab] = useState<'feed' | 'sources'>('feed');

  // Real dynamic states
  const [hotItems, setHotItems] = useState<any[]>([]);
  const [domainStats, setDomainStats] = useState<StatItem[]>([]);
  const [sources, setSources] = useState<any[]>([]);

  const logId = useRef(0);

  const addLog = useCallback((entry: Omit<LogEntry, 'id' | 'time'>) => {
    setLogs(prev => [...prev.slice(-120), { ...entry, id: logId.current++, time: now() }]);
  }, []);

  // Fetch Dashboard Data
  const fetchData = async (domain?: string) => {
    try {
      const respDomains = await fetch(`${API_BASE}/api/v1/domains`);
      const dataDomains = await respDomains.json();
      if (dataDomains.success) {
        const stats: StatItem[] = dataDomains.domains.map((d: any) => ({
          label: d.name_cn,
          value: d.source_count.toString(),
          delta: '+0', // backend doesn't provide delta yet
          positive: true
        }));
        setDomainStats(stats);
      }

      const respSources = await fetch(`${API_BASE}/api/v1/sources`);
      const dataSources = await respSources.json();
      if (dataSources.success) {
        setSources(dataSources.data);
      }

      const url = new URL(`${API_BASE}/api/v1/items`);
      url.searchParams.append('limit', '20');
      if (domain && domain !== 'all') {
        url.searchParams.append('domain', domain);
      }

      const respItems = await fetch(url.toString());
      const dataItems = await respItems.json();
      if (dataItems.success) {
        setTotalItems(dataItems.total || 0);
        setHotItems(dataItems.data.map((item: any, idx: number) => {
          const domainLabelMap: Record<string, string> = {
            'global': '全球',
            'economy': '经济',
            'technology': '技术',
            'academic': '学术'
          };
          return {
            rank: idx + 1,
            title: item.title,
            url: item.url,
            domain: domainLabelMap[item.domain] || '综合',
            raw_domain: item.domain,
            heat: item.hotness_score || 0
          };
        }));
      }
    } catch (err) {
      console.error('Failed to fetch dashboard data:', err);
    }
  };

  const fetchSummary = async (domain?: string) => {
    setIsSummarizing(true);
    try {
      const url = new URL(`${API_BASE}/api/v1/ai/summary`);
      if (domain && domain !== 'all') {
        url.searchParams.append('domain', domain);
      }

      const resp = await fetch(url.toString(), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });
      const data = await resp.json();
      if (data.success) {
        setAiSummary(data.summary);
      } else {
        setAiSummary('未能获取AI智能情报综述：' + (data.msg || '未知错误'));
      }
    } catch (err) {
      console.error('Failed to fetch AI summary:', err);
      setAiSummary('未能连接到后端服务，请检查后端运行状态。');
    } finally {
      setIsSummarizing(false);
    }
  };

  // SSE SSE Connection
  useEffect(() => {
    const eventSource = new EventSource(`${API_BASE}/stream`);

    eventSource.onopen = () => {
      setConnected(true);
      addLog({ level: 'OK', domain: 'SYS', msg: '已建立后端 SSE 连接' });
    };

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.event === 'connected') return;

        let level: 'INFO' | 'OK' | 'WARN' | 'ERROR' = 'INFO';
        if (data.event.includes('complete') || data.event.includes('done')) level = 'OK';

        addLog({
          level,
          domain: data.source_id || data.category || 'SSE',
          msg: `收到系统事件: ${data.event} ${data.total_items ? `(总数: ${data.total_items})` : ''}`
        });

        // Refresh data when crawl completes or scheduler finishes
        if (data.event.includes('complete') || data.event.includes('done')) {
          fetchData(activeTab);
        }
      } catch (err) {
        console.error('Failed to parse SSE message:', err);
      }
    };

    eventSource.onerror = (err) => {
      console.error('SSE connection error:', err);
      setConnected(false);
      addLog({ level: 'ERROR', domain: 'SYS', msg: '后端 SSE 连接丢失，尝试重连...' });
    };

    return () => {
      eventSource.close();
    };
  }, [addLog]);

  useEffect(() => {
    fetchData(activeTab);
    fetchSummary(activeTab);
  }, [activeTab]);

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', background: '#080808', color: '#e0e0e0', fontFamily: 'Inter,sans-serif' }}>

      {/* ── Top navbar ── */}
      <header style={{ borderBottom: '2px solid #1e1e1e', background: '#0a0a0a', display: 'flex', alignItems: 'center', padding: '0 20px', height: 50, flexShrink: 0 }}>
        <span style={{ fontWeight: 900, fontSize: 18, letterSpacing: 1.5, marginRight: 32 }}>
          u24<span style={{ color: '#ff5c00' }}>Time</span>
        </span>

        {/* Domain tab nav */}
        <nav style={{ display: 'flex', gap: 2, flex: 1 }}>
          {DOMAIN_TABS.map(tab => {
            const Icon = tab.icon;
            const active = activeTab === tab.id;
            return (
              <button key={tab.id} onClick={() => setActiveTab(tab.id)}
                style={{
                  display: 'flex', alignItems: 'center', gap: 5, padding: '6px 14px', border: 'none', cursor: 'pointer',
                  background: active ? '#1a1a1a' : 'transparent',
                  color: active ? '#fff' : '#666',
                  fontWeight: active ? 700 : 500, fontSize: 13,
                  borderBottom: active ? '2px solid #ff5c00' : '2px solid transparent',
                  transition: 'all 0.15s'
                }}>
                <Icon size={13} />
                {tab.label}
              </button>
            );
          })}
        </nav>

        {/* Right controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, fontWeight: 700 }}>
            {connected
              ? <><Wifi size={13} style={{ color: '#34d399' }} /><span style={{ color: '#34d399' }}>已连接</span></>
              : <><WifiOff size={13} style={{ color: '#f87171' }} /><span style={{ color: '#f87171' }}>重连中</span></>}
          </span>
          <button
            onClick={() => { fetchData(activeTab); fetchSummary(activeTab); }}
            style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '5px 12px', border: '1.5px solid #333', background: 'none', color: '#ccc', cursor: 'pointer', fontWeight: 700, fontSize: 12 }}
          >
            <RefreshCw size={12} /> 刷新
          </button>
        </div>
      </header>

      {/* ── Body: main + console ── */}
      <div style={{ flex: 1, display: 'flex', gap: 0 }}>

        {/* ── Main content ── */}
        <main style={{ flex: 1, padding: '20px', display: 'flex', flexDirection: 'column', gap: 20 }}>

          <AISummaryPanel
            summary={aiSummary}
            loading={isSummarizing}
            onRefresh={fetchSummary}
          />

          <StatBar stats={domainStats.length > 0 ? domainStats : DOMAIN_STATS_FALLBACK} />

          {/* Main content grid - Now single column for focus */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <PanelBox
              title="热搜排行"
              icon={<TrendingUp size={14} />}
              badge="每5分钟更新"
              count={hotItems.length}
              style={{ minHeight: 480 }}
            >
              <HotPanelItems items={hotItems.length > 0 ? hotItems : []} />
            </PanelBox>
          </div>

          {/* Sparkline / Activity row */}
          <PanelBox title="域活跃度" icon={<BarChart2 size={14} />} badge="24h" style={{ height: 100, flexShrink: 0 }}>
            <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end', height: 46, paddingTop: 6 }}>
              {['地缘', '经济', '科技', '学术'].map((d, di) => {
                const heights = [[30, 45, 38, 55, 42, 60, 52], [20, 35, 50, 30, 40, 35, 48], [55, 62, 70, 60, 75, 68, 80], [18, 25, 30, 20, 28, 22, 35]];
                return (
                  <div key={d} style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1 }}>
                    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 2, height: 36 }}>
                      {heights[di].map((h, j) => (
                        <div key={j} style={{ flex: 1, height: `${h}%`, background: domainColor(d), opacity: 0.7 + (j / heights[di].length) * 0.3, borderRadius: '1px 1px 0 0' }} />
                      ))}
                    </div>
                    <span style={{ fontSize: 10, color: '#888', textAlign: 'center' }}>{d}</span>
                  </div>
                );
              })}
            </div>
          </PanelBox>

          {/* Alert bar */}
          <div style={{ display: 'flex', gap: 8, padding: '10px 14px', background: 'rgba(255,68,68,0.06)', border: '1.5px solid rgba(255,68,68,0.25)', alignItems: 'center' }}>
            <AlertTriangle size={14} style={{ color: '#f87171', flexShrink: 0 }} />
            <span style={{ fontSize: 12, color: '#f87171', fontWeight: 700 }}>警告</span>
            <span style={{ fontSize: 12, color: '#c9d1d9' }}>Twitter/X API 已超限额，相关舆情数据切换至缓存模式，时效性降低约 40 分钟。</span>
          </div>
        </main>

        {/* ── Console right panel ── */}
        <aside style={{
          width: 420,
          borderLeft: '2px solid #1a1a1a',
          display: 'flex',
          flexDirection: 'column',
          flexShrink: 0
        }}>
          {/* Sidebar Tabs */}
          <div style={{ display: 'flex', background: '#0a0a0a', borderBottom: '1px solid #222' }}>
            <button
              onClick={() => setSidebarTab('feed')}
              style={{
                flex: 1, padding: '12px', background: sidebarTab === 'feed' ? '#111' : 'transparent',
                color: sidebarTab === 'feed' ? '#ff5c00' : '#666', border: 'none', cursor: 'pointer',
                fontSize: 12, fontWeight: 800, borderBottom: sidebarTab === 'feed' ? '2px solid #ff5c00' : 'none',
                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6
              }}
            >
              <Terminal size={14} /> 实时情报
            </button>
            <button
              onClick={() => setSidebarTab('sources')}
              style={{
                flex: 1, padding: '12px', background: sidebarTab === 'sources' ? '#111' : 'transparent',
                color: sidebarTab === 'sources' ? '#ff5c00' : '#666', border: 'none', cursor: 'pointer',
                fontSize: 12, fontWeight: 800, borderBottom: sidebarTab === 'sources' ? '2px solid #ff5c00' : 'none',
                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6
              }}
            >
              <Radio size={14} /> 数据源
            </button>
          </div>

          <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
            {sidebarTab === 'feed' ? (
              <ConsolePanel logs={logs} onClear={() => setLogs([])} />
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
                <div style={{ flex: 1, overflow: 'auto', padding: '14px' }}>
                  <SourcePanelSources sources={sources} />
                </div>
                {/* Fixed Stats Footer in Sidebar */}
                <div style={{ padding: '14px', background: '#0f0f0f', borderTop: '2px solid #222', fontSize: 11, color: '#666' }}>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                    <div>总条目 <strong style={{ color: '#fff' }}>{totalItems}</strong></div>
                    <div>规范化 <strong style={{ color: '#10b981' }}>97.4%</strong></div>
                    <div>活跃任务 <strong style={{ color: '#d97706' }}>{sources.filter(s => s.status === 'live').length}</strong></div>
                    <div>上次同步 <strong style={{ color: '#fff' }}>刚刚</strong></div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </aside>
      </div>

      {/* ── Status bar ── */}
      <footer style={{ borderTop: '1px solid #161616', background: '#0a0a0a', display: 'flex', alignItems: 'center', padding: '4px 16px', gap: 20, flexShrink: 0 }}>
        <span style={{ fontSize: 11, color: '#555', display: 'flex', alignItems: 'center', gap: 5 }}>
          <Activity size={11} style={{ color: '#34d399' }} />
          <span>系统正常</span>
        </span>
        <span style={{ fontSize: 11, color: '#555' }}>CPU <strong style={{ color: '#c9d1d9' }}>14%</strong></span>
        <span style={{ fontSize: 11, color: '#555' }}>在线率 <strong style={{ color: '#34d399' }}>99.9%</strong></span>
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 11, color: '#444' }}>© 2026 WALL-AI · u24Time 开源情报系统</span>
        <ChevronRight size={11} style={{ color: '#333' }} />
      </footer>
    </div>
  );
}
