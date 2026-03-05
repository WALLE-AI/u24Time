import { useState, useEffect, useRef, useCallback } from 'react';
import {
  Shield, Globe, Activity, Cpu, Terminal, TrendingUp,
  BarChart2, Radio, Wifi, WifiOff, RefreshCw, Zap,
  AlertTriangle, ChevronRight, Sparkles, BookOpen, DollarSign, X,
  ListTodo, Clock, CheckCircle2, CircleDashed, Loader2
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

interface TaskEntry {
  task_id: string;
  task_type: string;
  source_ids: string[];
  status: string;
  items_fetched: number;
  items_aligned: number;
  started_at: string;
  finished_at?: string;
}

interface SchedulerJob {
  source_id: string;
  next_run: string | null;
  interval_min: number;
}
const DOMAIN_TABS = [
  { id: 'all', label: '全览', icon: Globe },
  { id: 'global', label: '全球监控', icon: Shield },
  { id: 'economy', label: '经济', icon: DollarSign },
  { id: 'technology', label: '技术', icon: Cpu },
  { id: 'academic', label: '学术', icon: BookOpen },
  { id: 'entertainment', label: '娱乐', icon: Sparkles },
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

function formatTime(isoString?: string) {
  if (!isoString) return '';
  const date = new Date(isoString);
  const now = new Date();
  const diff = now.getTime() - date.getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return '刚刚';
  if (mins < 60) return `${mins}分钟前`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}小时前`;
  return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' }) + ' ' + date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
}

function domainColor(d: string) {
  const map: Record<string, string> = {
    'global': '#ff5c00', 'economy': '#3357FF', 'technology': '#33FF57', 'academic': '#c084fc', 'entertainment': '#ff007f'
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
function NewsFlashPanel({ items, lastRefreshed }: { items: any[], lastRefreshed: Date | null }) {
  return (
    <PanelBox
      title="今日时讯快报"
      icon={<Zap size={14} color="#ffaa00" />}
      badge="最新推送"
      badgeColor="#ffaa00"
      titleRight={
        <div style={{ fontSize: 10, color: '#555', display: 'flex', alignItems: 'center', gap: 4 }}>
          <Clock size={10} />
          {lastRefreshed ? `已于 ${lastRefreshed.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })} 更新` : '正在同步...'}
        </div>
      }
      style={{ marginBottom: 0 }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
        {items.map((item, idx) => (
          <a
            key={item.item_id || idx}
            href={item.url}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: 12,
              padding: '12px 0',
              borderBottom: idx === items.length - 1 ? 'none' : '1px solid #1a1a1a',
              textDecoration: 'none',
              color: 'inherit',
              transition: 'background 0.2s',
              cursor: item.url ? 'pointer' : 'default'
            }}
            onMouseEnter={(e) => { if (item.url) e.currentTarget.style.background = 'rgba(255,170,0,0.03)'; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
          >
            <div style={{ marginTop: 5 }}>
              <div style={{ width: 6, height: 6, borderRadius: '50%', background: '#ffaa00', boxShadow: '0 0 8px rgba(255,170,0,0.6)' }} />
            </div>
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span style={{ fontSize: 13, fontWeight: 600, lineHeight: 1.5, color: '#eee' }}>{item.title}</span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 11, color: '#ffaa00', fontWeight: 700, fontFamily: 'monospace' }}>{formatTime(item.published_at || item.crawled_at)}</span>
                <span style={{ fontSize: 10, color: '#444' }}>|</span>
                <span style={{ fontSize: 11, color: '#666', fontWeight: 500 }}>{item.source_id}</span>
                {item.domain && (
                  <span style={{ fontSize: 10, color: domainColor(item.domain), opacity: 0.8 }}>#{item.domain}</span>
                )}
              </div>
            </div>
          </a>
        ))}
        {items.length === 0 && <div style={{ padding: '30px 0', color: '#555', textAlign: 'center', fontSize: 13 }}>正在载入最新时讯...</div>}
      </div>
    </PanelBox>
  );
}

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
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span style={{ fontSize: 13, fontWeight: 600, lineHeight: 1.3 }}>{item.title}</span>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ fontSize: 10, color: '#666', fontWeight: 500 }}>{formatTime(item.crawled_at)}</span>
              {item.raw_domain === 'academic' && (
                <div style={{ display: 'flex', gap: 6 }}>
                  {item.categories && item.categories.length > 0 && item.categories.slice(0, 2).map((c: string, idx: number) => (
                    <span key={c + idx} style={{ padding: '1px 5px', background: 'rgba(192, 132, 252, 0.1)', color: '#c084fc', borderRadius: 3, fontSize: 9, border: '1px solid rgba(192, 132, 252, 0.3)' }}>
                      {c}
                    </span>
                  ))}
                  {item.sub_domain && (
                    <span style={{ padding: '1px 5px', background: 'rgba(52, 211, 153, 0.1)', color: '#34d399', borderRadius: 3, fontSize: 9, border: '1px solid rgba(52, 211, 153, 0.3)' }}>
                      {item.sub_domain === 'paper' ? '论文' : item.sub_domain}
                    </span>
                  )}
                </div>
              )}
            </div>
          </div>
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

// ─────────────────────────────────────  Task Center Components
function TaskStatusIcon({ status }: { status: string }) {
  if (status === 'done') return <CheckCircle2 size={12} style={{ color: '#34d399' }} />;
  if (status === 'running') return <Loader2 size={12} className="animate-spin" style={{ color: '#6ee7f7' }} />;
  if (status === 'failed') return <X size={12} style={{ color: '#f87171' }} />;
  return <CircleDashed size={12} style={{ color: '#888' }} />;
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
  titleRight?: React.ReactNode;
}

function PanelBox({ title, icon, badge, badgeColor = '#34d399', count, children, style, actions, titleRight }: PanelBoxProps) {
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
        <div style={{ flex: 1 }} />
        {titleRight}
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
  const [sidebarTab, setSidebarTab] = useState<'feed' | 'sources' | 'tasks'>('feed');
  const [economySubCategory, setEconomySubCategory] = useState('all');
  const [techSubCategory, setTechSubCategory] = useState('all');
  const [academicSubCategory, setAcademicSubCategory] = useState('all');
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);

  // Real dynamic states
  const [hotItems, setHotItems] = useState<any[]>([]);
  const [newsFlashItems, setNewsFlashItems] = useState<any[]>([]);
  const [domainStats, setDomainStats] = useState<StatItem[]>([]);
  const [sources, setSources] = useState<any[]>([]);

  // 域活跃度：每个域维护最近 8 个采集周期的 items_count 滑动窗口
  // key: 'global' | 'economy' | 'technology' | 'academic'
  const ACTIVITY_WINDOW = 8;
  const [domainActivity, setDomainActivity] = useState<Record<string, number[]>>({
    global: [0, 0, 0, 0, 0, 0, 0, 0],
    economy: [0, 0, 0, 0, 0, 0, 0, 0],
    technology: [0, 0, 0, 0, 0, 0, 0, 0],
    academic: [0, 0, 0, 0, 0, 0, 0, 0],
    entertainment: [0, 0, 0, 0, 0, 0, 0, 0],
  });
  const [domainLastUpdated, setDomainLastUpdated] = useState<Record<string, string | null>>({
    global: null, economy: null, technology: null, academic: null, entertainment: null,
  });
  // 地区分布：每个域对应 { CN: n, US: n, Global: n, Other: n }
  const [domainGeoDistribution, setDomainGeoDistribution] = useState<Record<string, Record<string, number>>>({
    global: {}, economy: {}, technology: {}, academic: {}, entertainment: {},
  });

  // Task Center states
  const [tasks, setTasks] = useState<TaskEntry[]>([]);
  const [schedulerJobs, setSchedulerJobs] = useState<SchedulerJob[]>([]);
  const [runningTasksCount, setRunningTasksCount] = useState(0);

  // Scheduler run states
  const [runningSchedulers, setRunningSchedulers] = useState<Set<string>>(new Set());
  const [schedulerStaleCache, setSchedulerStaleCache] = useState<Record<string, { last_success: string; items_count: number }>>({});

  const logId = useRef(0);
  // Ref to always have latest activeTab inside SSE closure (avoids stale closure bug)
  const activeTabRef = useRef(activeTab);
  useEffect(() => { activeTabRef.current = activeTab; }, [activeTab]);

  const addLog = useCallback((entry: Omit<LogEntry, 'id' | 'time'>) => {
    setLogs(prev => [...prev.slice(-120), { ...entry, id: logId.current++, time: now() }]);
  }, []);

  // Fetch Tasks and Scheduler
  const fetchTaskCenter = async () => {
    try {
      const [tasksResp, schedResp] = await Promise.all([
        fetch(`${API_BASE}/api/v1/crawl/tasks`),
        fetch(`${API_BASE}/api/v1/scheduler/status`)
      ]);
      const tasksData = await tasksResp.json();
      const schedData = await schedResp.json();

      if (tasksData.success && tasksData.data) {
        const sorted = tasksData.data.sort((a: any, b: any) => new Date(b.started_at).getTime() - new Date(a.started_at).getTime());
        setTasks(sorted);
        setRunningTasksCount(sorted.filter((t: any) => t.status === 'running' || t.status === 'pending').length);
      }
      if (schedData.success && schedData.data && schedData.data.jobs) {
        setSchedulerJobs(schedData.data.jobs.sort((a: any, b: any) => {
          if (!a.next_run) return 1;
          if (!b.next_run) return -1;
          return new Date(a.next_run).getTime() - new Date(b.next_run).getTime();
        }));
        if (schedData.data.stale_cache) {
          setSchedulerStaleCache(schedData.data.stale_cache);
        }
      }
    } catch (err) {
      console.error('Failed to fetch task center data:', err);
    }
  };

  // Fetch Domain Activity (initial load from DB + scheduler cache)
  const fetchDomainActivity = useCallback(async () => {
    try {
      const resp = await fetch(`${API_BASE}/api/v1/domains/activity`);
      const data = await resp.json();
      if (data.success && data.data) {
        const newActivity: Record<string, number[]> = {};
        const newLastUpdated: Record<string, string | null> = {};
        const newGeo: Record<string, Record<string, number>> = {};
        for (const item of data.data) {
          const d = item.domain as string;
          const base = item.recent_items as number;
          newActivity[d] = Array(ACTIVITY_WINDOW).fill(base);
          newLastUpdated[d] = item.last_updated;
          newGeo[d] = (item.geo_distribution as Record<string, number>) ?? {};
        }
        setDomainActivity(prev => ({ ...prev, ...newActivity }));
        setDomainLastUpdated(prev => ({ ...prev, ...newLastUpdated }));
        setDomainGeoDistribution(prev => ({ ...prev, ...newGeo }));
      }
    } catch (err) {
      console.error('Failed to fetch domain activity:', err);
    }
  }, []);

  // ── Dashboard Data Fetch (wrapped in useCallback for stable ref) ──
  const fetchData = useCallback(async (domain?: string) => {
    try {
      const respDomains = await fetch(`${API_BASE}/api/v1/domains`);
      const dataDomains = await respDomains.json();
      if (dataDomains.success) {
        const stats: StatItem[] = dataDomains.domains.map((d: any) => ({
          label: d.name_cn,
          value: d.source_count.toString(),
          delta: '+0',
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
        if (domain === 'economy' && economySubCategory !== 'all') {
          url.searchParams.append('sub_domain', economySubCategory);
        }
        if (domain === 'technology' && techSubCategory !== 'all') {
          url.searchParams.append('sub_domain', techSubCategory);
        }
        if (domain === 'academic' && academicSubCategory !== 'all') {
          url.searchParams.append('sub_domain', academicSubCategory);
        }
      }
      url.searchParams.append('_t', String(Date.now())); // Cache buster

      const respItems = await fetch(url.toString());
      const dataItems = await respItems.json();
      if (dataItems.success) {
        setTotalItems(dataItems.total || 0);
        setHotItems(dataItems.data.map((item: any, idx: number) => {
          const domainLabelMap: Record<string, string> = {
            'global': '全球',
            'economy': '经济',
            'technology': '技术',
            'academic': '学术',
            'entertainment': '娱乐'
          };
          return {
            rank: idx + 1,
            title: item.title,
            url: item.url,
            domain: domainLabelMap[item.domain] || '综合',
            raw_domain: item.domain,
            sub_domain: item.sub_domain,
            categories: item.categories || [],
            heat: item.hotness_score || 0,
            published_at: item.published_at,
            crawled_at: item.crawled_at
          };
        }));
      }

    } catch (err) {
      console.error('Failed to fetch dashboard data:', err);
    }
  }, [economySubCategory, techSubCategory, academicSubCategory]);

  // ── 独立的时讯快报拉取函数（走内存极速接口）────────
  const fetchNewsFlash = useCallback(async (domain?: string) => {
    try {
      const flashUrl = new URL(`${API_BASE}/api/v1/newsflash`);
      flashUrl.searchParams.append('limit', '8');
      if (domain && domain !== 'all') {
        flashUrl.searchParams.append('domain', domain);
      }
      const respFlash = await fetch(flashUrl.toString());
      const dataFlash = await respFlash.json();
      if (dataFlash.success) {
        setNewsFlashItems(dataFlash.data);
        setLastRefreshed(new Date());
      }
    } catch (err) {
      console.error('Failed to fetch news flash:', err);
    }
  }, []);

  // Use SSE events (scheduler_done) to trigger refreshes instead of hardcoded polling
  useEffect(() => {
    // Intentionally empty or handle other activeTab specific logic without setInterval
  }, [activeTab]);

  const fetchSummary = async (domain?: string, force = false) => {
    const cacheKey = `u24_ai_summary_${domain || 'all'}`;
    if (!force) {
      const cached = localStorage.getItem(cacheKey);
      if (cached) {
        setAiSummary(cached);
        setIsSummarizing(false);
        return;
      }
    }

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
        localStorage.setItem(cacheKey, data.summary);
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

  const fetchDataRef = useRef(fetchData);
  useEffect(() => { fetchDataRef.current = fetchData; }, [fetchData]);
  const fetchNewsFlashRef = useRef(fetchNewsFlash);
  useEffect(() => { fetchNewsFlashRef.current = fetchNewsFlash; }, [fetchNewsFlash]);
  const activeTabForFlashRef = useRef(activeTab);
  useEffect(() => { activeTabForFlashRef.current = activeTab; }, [activeTab]);

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
          domain: data.domain || data.source_id || data.category || 'SSE',
          msg: data.event === 'scheduler_done'
            ? `[${data.domain || data.source_id}] 采集完成 ${data.items_count != null ? data.items_count + ' 条' : ''}`
            : `收到系统事件: ${data.event}${data.total_items ? ` (总数: ${data.total_items})` : ''}`
        });

        if (data.event.includes('task_') || data.event === 'scheduler_done') {
          fetchTaskCenter();
        }

        if (data.event === 'scheduler_start' && data.source_id) {
          setRunningSchedulers(prev => {
            const next = new Set(prev);
            next.add(data.source_id);
            return next;
          });
        } else if ((data.event === 'scheduler_done' || data.event === 'scheduler_error') && data.source_id) {
          setRunningSchedulers(prev => {
            const next = new Set(prev);
            next.delete(data.source_id);
            return next;
          });
          if (data.event === 'scheduler_done') {
            setSchedulerStaleCache(prev => ({
              ...prev,
              [data.source_id]: {
                last_success: data.timestamp,
                items_count: data.items_count ?? 0
              }
            }));
          }
        }

        // 实时更新域活跃度滑动窗口
        if (data.event === 'scheduler_done' && data.domain) {
          const eventDomain = data.domain as string;
          const count = (data.items_count as number) ?? 0;
          setDomainActivity(prev => {
            const current = prev[eventDomain] ?? Array(ACTIVITY_WINDOW).fill(0);
            // 推入新值，移除最旧值
            const updated = [...current.slice(1), count];
            return { ...prev, [eventDomain]: updated };
          });
          setDomainLastUpdated(prev => ({
            ...prev,
            [eventDomain]: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
          }));
        }

        // Refresh data on scheduler events
        if (data.event === 'scheduler_done') {
          const currentTab = activeTabRef.current;
          const eventDomain = data.domain as string | undefined;

          const isMatch = currentTab === 'all' || !eventDomain || eventDomain === currentTab;

          // 【修复】今日时讯快报：0延迟内存流直达，不再走网络请求
          if (data.items && data.items.length > 0) {
            // 全球tab，或者特定tab匹配上的，直接插入前端状态
            if (isMatch) {
              setNewsFlashItems(prev => {
                const combined = [...data.items, ...prev];
                const uniqueMap = new Map();
                combined.forEach(item => {
                  if (!uniqueMap.has(item.item_id || item.url)) {
                    uniqueMap.set(item.item_id || item.url, item);
                  }
                });
                return Array.from(uniqueMap.values()).slice(0, 8);
              });
              setLastRefreshed(new Date());
            }
          } else {
            // Fallback back to fetching
            fetchNewsFlashRef.current(currentTab !== 'all' ? currentTab : undefined);
          }

          // 热搜排行：依然走网络请求获取计算后的数据
          if (isMatch) {
            fetchDataRef.current(currentTab);
          }
        } else if (data.event.includes('complete')) {
          // Other crawl events (manual API/RSS/hotsearch) also refresh both
          fetchNewsFlashRef.current(activeTabForFlashRef.current !== 'all' ? activeTabForFlashRef.current : undefined);
          fetchDataRef.current(activeTabRef.current);
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
    fetchNewsFlash(activeTab !== 'all' ? activeTab : undefined);
  }, [activeTab, fetchData, fetchNewsFlash]);

  // 2分钟安全网咋轮询——防止 SSE 断连期间错过数据更新
  useEffect(() => {
    const timer = setInterval(() => {
      const tab = activeTabForFlashRef.current;
      fetchDataRef.current(tab);
      fetchNewsFlashRef.current(tab !== 'all' ? tab : undefined);
    }, 2 * 60 * 1000); // 2 minutes
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    fetchTaskCenter();
    fetchDomainActivity();
    // Poll scheduler every 30s as a fallback
    const interval = setInterval(fetchTaskCenter, 30000);
    return () => clearInterval(interval);
  }, [fetchDomainActivity]);

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
            onClick={() => { fetchData(activeTab); fetchNewsFlash(activeTab !== 'all' ? activeTab : undefined); fetchSummary(activeTab, true); }}
            style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '5px 12px', border: '1.5px solid #333', background: 'none', color: '#ccc', cursor: 'pointer', fontWeight: 700, fontSize: 12 }}
          >
            <RefreshCw size={12} /> 刷新
          </button>
        </div>
      </header>

      {/* ── Body: main + console ── */}
      <div style={{ flex: 1, display: 'flex', gap: 0, overflow: 'hidden' }}>

        {/* ── Main content ── */}
        <main style={{ flex: 1, padding: '20px', display: 'flex', flexDirection: 'column', gap: 20, overflow: 'auto' }}>

          <AISummaryPanel
            key={activeTab}
            summary={aiSummary}
            loading={isSummarizing}
            onRefresh={() => fetchSummary(activeTab, true)}
          />

          <StatBar stats={domainStats.length > 0 ? domainStats : DOMAIN_STATS_FALLBACK} />

          <NewsFlashPanel items={newsFlashItems} lastRefreshed={lastRefreshed} />

          {/* Main content grid - Now single column for focus */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <PanelBox
              title={activeTab === 'economy' ? "经济动态排名" : "热搜排行"}
              icon={<TrendingUp size={14} />}
              badge="实时 (SSE 推送)"
              count={hotItems.length}
              style={{ minHeight: 480 }}
              actions={(
                <>
                  {activeTab === 'economy' && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 11, color: '#666' }}>分类:</span>
                      <select
                        value={economySubCategory}
                        onChange={(e) => setEconomySubCategory(e.target.value)}
                        style={{
                          background: '#1a1a1a',
                          color: '#fff',
                          border: '1px solid #333',
                          fontSize: 11,
                          padding: '2px 6px',
                          borderRadius: 2,
                          cursor: 'pointer',
                          outline: 'none'
                        }}
                      >
                        <option value="all">全部动态</option>
                        <option value="stock">股市/全球指数</option>
                        <option value="finance">实时财经快讯</option>
                        <option value="crypto">加密货币价格</option>
                        <option value="futures">黄金/有色金属/大宗</option>
                        <option value="quant">市场情绪/量化</option>
                      </select>
                    </div>
                  )}
                  {activeTab === 'technology' && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 11, color: '#666' }}>分类:</span>
                      <select
                        value={techSubCategory}
                        onChange={(e) => setTechSubCategory(e.target.value)}
                        style={{
                          background: '#1a1a1a',
                          color: '#fff',
                          border: '1px solid #333',
                          fontSize: 11,
                          padding: '2px 6px',
                          borderRadius: 2,
                          cursor: 'pointer',
                          outline: 'none'
                        }}
                      >
                        <option value="all">全部动态</option>
                        <option value="oss">GitHub 项目趋势</option>
                        <option value="tech_news">技术社区 & 新闻</option>
                        <option value="ai_model">AI 模型更新</option>
                        <option value="ai_dataset">AI 数据集更新</option>
                        <option value="cyber">网络安全威胁</option>
                        <option value="infra">基础设施状态</option>
                      </select>
                    </div>
                  )}
                  {activeTab === 'academic' && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 11, color: '#666' }}>分类:</span>
                      <select
                        value={academicSubCategory}
                        onChange={(e) => setAcademicSubCategory(e.target.value)}
                        style={{
                          background: '#1a1a1a',
                          color: '#fff',
                          border: '1px solid #333',
                          fontSize: 11,
                          padding: '2px 6px',
                          borderRadius: 2,
                          cursor: 'pointer',
                          outline: 'none'
                        }}
                      >
                        <option value="all">全部动态</option>
                        <option value="paper">学术论文 (arXiv / HF / S2)</option>
                        <option value="conference">学术会议</option>
                        <option value="prediction">预测市场</option>
                      </select>
                    </div>
                  )}
                </>
              )}
            >
              <HotPanelItems items={hotItems.length > 0 ? hotItems : []} />
            </PanelBox>
          </div>

          {/* Sparkline / Activity row — 实时域活跃度 + 地区分布 */}
          {(() => {
            const DOMAIN_DEFS = [
              { id: 'global', label: '地缘', color: '#ff5c00' },
              { id: 'economy', label: '经济', color: '#3357FF' },
              { id: 'technology', label: '科技', color: '#33FF57' },
              { id: 'academic', label: '学术', color: '#c084fc' },
            ];
            // 地区颜色 & 标签
            const GEO_COLOR: Record<string, string> = {
              CN: '#f87171',   // 中国 · 红
              US: '#60a5fa',   // 美国 · 蓝
              Global: '#34d399', // 全球 · 绿
              Other: '#fbbf24',  // 其他 · 黄
            };
            const GEO_LABEL: Record<string, string> = {
              CN: '🇨🇳', US: '🇺🇸', Global: '🌐', Other: '…',
            };

            const allValues = DOMAIN_DEFS.flatMap(d => domainActivity[d.id] ?? []);
            const globalMax = Math.max(...allValues, 1);
            const toHeight = (v: number) => Math.max(5, Math.round((v / globalMax) * 90));

            return (
              <PanelBox
                title="域活跃度"
                icon={<BarChart2 size={14} />}
                badge="实时"
                badgeColor="#34d399"
                style={{ minHeight: 160, flexShrink: 0 }}
              >
                <div style={{ display: 'flex', gap: 12, paddingTop: 6 }}>
                  {DOMAIN_DEFS.map(({ id, label, color }) => {
                    const bars = domainActivity[id] ?? Array(ACTIVITY_WINDOW).fill(0);
                    const lastTime = domainLastUpdated[id];
                    const isActive = bars[bars.length - 1] > 0;
                    const geo = domainGeoDistribution[id] ?? {};
                    const geoTotal = Object.values(geo).reduce((a, b) => a + b, 0) || 1;

                    // 地区条带的顺序：CN > US > Global > Other
                    const geoOrder = ['CN', 'US', 'Global', 'Other', ...Object.keys(geo).filter(k => !['CN', 'US', 'Global', 'Other'].includes(k))];
                    const geoSegments = geoOrder
                      .filter(k => geo[k] > 0)
                      .map(k => ({ key: k, pct: Math.max(2, Math.round((geo[k] / geoTotal) * 100)) }));

                    return (
                      <div key={id} style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1, minWidth: 0 }}>
                        {/* 柱状图 */}
                        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 2, height: 42 }}>
                          {bars.map((v, j) => (
                            <div key={j} style={{
                              flex: 1, height: `${toHeight(v)}%`,
                              background: color,
                              opacity: 0.4 + (j / bars.length) * 0.6,
                              borderRadius: '1px 1px 0 0',
                              transition: 'height 0.5s ease',
                            }} />
                          ))}
                        </div>

                        {/* 域名 + 最近更新时间 */}
                        <span style={{ fontSize: 10, color: isActive ? color : '#666', textAlign: 'center', fontWeight: isActive ? 700 : 400, transition: 'color 0.5s' }}>
                          {label}
                        </span>
                        {lastTime && (
                          <span style={{ fontSize: 9, color: '#444', textAlign: 'center', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                            {lastTime}
                          </span>
                        )}

                        {/* 地区分布堆叠进度条 */}
                        <div
                          title={geoSegments.map(s => `${GEO_LABEL[s.key] ?? s.key} ${s.pct}%`).join('  ')}
                          style={{
                            display: 'flex', height: 6, borderRadius: 3, overflow: 'hidden',
                            background: 'rgba(255,255,255,0.06)',
                            border: '1px solid rgba(255,255,255,0.08)',
                            marginTop: 2,
                          }}
                        >
                          {geoSegments.length > 0 ? geoSegments.map(({ key, pct }) => (
                            <div key={key} style={{
                              width: `${pct}%`,
                              background: GEO_COLOR[key] ?? '#888',
                              transition: 'width 0.6s ease',
                              opacity: 0.85,
                            }} />
                          )) : (
                            <div style={{ width: '100%', background: 'rgba(255,255,255,0.05)' }} />
                          )}
                        </div>

                        {/* 图例 */}
                        {geoSegments.length > 0 && (
                          <div style={{ display: 'flex', gap: 3, flexWrap: 'wrap', justifyContent: 'center' }}>
                            {geoSegments.map(({ key, pct }) => (
                              <span key={key} style={{ fontSize: 9, color: GEO_COLOR[key] ?? '#888', whiteSpace: 'nowrap' }}>
                                {GEO_LABEL[key] ?? key}{pct}%
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </PanelBox>
            );
          })()}

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
            <button
              onClick={() => setSidebarTab('tasks')}
              style={{
                flex: 1, padding: '12px', background: sidebarTab === 'tasks' ? '#111' : 'transparent',
                color: sidebarTab === 'tasks' ? '#ff5c00' : '#666', border: 'none', cursor: 'pointer',
                fontSize: 12, fontWeight: 800, borderBottom: sidebarTab === 'tasks' ? '2px solid #ff5c00' : 'none',
                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6, position: 'relative'
              }}
            >
              <ListTodo size={14} /> 任务监控
              {runningTasksCount > 0 && <span className="pulse-dot" style={{ position: 'absolute', top: 12, right: 12, width: 4, height: 4, background: '#6ee7f7', borderRadius: '50%' }} />}
            </button>
          </div>

          <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
            {sidebarTab === 'feed' ? (
              <ConsolePanel logs={logs} onClear={() => setLogs([])} />
            ) : sidebarTab === 'sources' ? (
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
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
                <div style={{ flex: 1, overflow: 'auto', display: 'flex', flexDirection: 'column' }}>
                  {/* Active/Recent Tasks */}
                  <div style={{ padding: '14px 14px 4px', fontSize: 11, fontWeight: 700, color: '#666', letterSpacing: 1 }}>
                    近期运行任务
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column' }}>
                    {tasks.slice(0, 8).map(t => (
                      <div key={t.task_id} style={{
                        padding: '10px 14px',
                        borderBottom: '1px solid #111',
                        background: t.status === 'running' ? 'rgba(110, 231, 247, 0.05)' : 'transparent',
                        display: 'flex', flexDirection: 'column', gap: 6
                      }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <TaskStatusIcon status={t.status} />
                            <span style={{ fontSize: 12, fontWeight: 700, color: t.status === 'running' ? '#6ee7f7' : '#e0e0e0', textTransform: 'uppercase' }}>
                              {t.task_type}
                            </span>
                          </div>
                          <span style={{ fontSize: 10, color: '#555' }}>
                            {new Date(t.started_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
                          </span>
                        </div>
                        <div style={{ fontSize: 11, color: '#888', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                          {t.source_ids.length > 0 ? t.source_ids.join(', ') : 'All sources'}
                        </div>
                        {(t.status === 'done' || t.status === 'failed') && (
                          <div style={{ fontSize: 10, color: t.status === 'done' ? '#34d399' : '#f87171', display: 'flex', justifyContent: 'flex-end' }}>
                            {t.status === 'done' ? `${t.items_aligned} items` : 'Failed'}
                          </div>
                        )}
                      </div>
                    ))}
                    {tasks.length === 0 && <div style={{ padding: '20px', textAlign: 'center', color: '#444', fontSize: 12 }}>暂无任务记录</div>}
                  </div>

                  {/* Scheduler Status */}
                  <div style={{ padding: '20px 14px 4px', fontSize: 11, fontWeight: 700, color: '#666', letterSpacing: 1, marginTop: 'auto', borderTop: '1px solid #1a1a1a' }}>
                    后台调度监控
                  </div>
                  <div style={{ flex: 1, paddingBottom: 12 }}>
                    {schedulerJobs.map(job => {
                      const isClose = job.next_run && (new Date(job.next_run).getTime() - Date.now() < 60000);
                      const isRunning = runningSchedulers.has(job.source_id);
                      const cacheInfo = schedulerStaleCache[job.source_id];

                      return (
                        <div key={job.source_id} style={{ padding: '8px 14px', borderBottom: '1px solid #111', display: 'flex', flexDirection: 'column', gap: 6 }}>
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 2, overflow: 'hidden' }}>
                              <span style={{ fontSize: 11, color: isRunning ? '#6ee7f7' : '#a0a0a0', fontWeight: isRunning ? 700 : 400, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                {job.source_id.split('.').pop()}
                              </span>
                              <span style={{ fontSize: 9, color: '#555' }}>
                                {isRunning ? '正在采集中...' : `${job.interval_min}m interval`}
                              </span>
                            </div>
                            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 2, flexShrink: 0 }}>
                              <div style={{ fontSize: 10, color: isClose ? '#fbbf24' : '#666', display: 'flex', alignItems: 'center', gap: 4 }}>
                                <Clock size={10} />
                                {job.next_run ? new Date(job.next_run).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : '—'}
                              </div>
                              {cacheInfo && !isRunning && (
                                <span style={{ fontSize: 9, color: '#34d399' }}>{cacheInfo.items_count} 条</span>
                              )}
                            </div>
                          </div>
                          {isRunning && (
                            <div style={{ width: '100%', height: 2, background: 'rgba(255,255,255,0.05)', borderRadius: 1, overflow: 'hidden', position: 'relative' }}>
                              <div className="animate-progress" style={{ width: '50%', height: '100%', background: 'linear-gradient(90deg, transparent, #6ee7f7, transparent)', position: 'absolute', left: 0, top: 0 }} />
                            </div>
                          )}
                        </div>
                      );
                    })}
                    {schedulerJobs.length === 0 && <div style={{ padding: '20px', textAlign: 'center', color: '#444', fontSize: 12 }}>无调度任务</div>}
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
