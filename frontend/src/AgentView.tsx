import React, { useState, useEffect, useRef } from 'react';
import { Play, BrainCircuit, Loader2, Terminal, BookOpen, AlertCircle, Activity } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { motion, AnimatePresence } from 'framer-motion';

const API_BASE = 'http://localhost:5001/agents/e2e';

// ─────────────────────────────────────  Types
interface AgentViewProps {
    onBack?: () => void;
}

interface LogEntry {
    id: number;
    time: string;
    stage: string;
    msg: string;
    type?: 'info' | 'success' | 'warning' | 'error' | 'thought';
}

export default function AgentView({ }: AgentViewProps) {
    const [topic, setTopic] = useState('auto');
    const [customTopic, setCustomTopic] = useState('');
    const [isRunning, setIsRunning] = useState(false);
    // const [currentRunId, setCurrentRunId] = useState<string | null>(null);

    // States for SSE progress
    const [currentStage, setCurrentStage] = useState<string>('idle');
    const [progress, setProgress] = useState<number>(0);
    const [logs, setLogs] = useState<LogEntry[]>([]);
    const [finalReport, setFinalReport] = useState<string>('');

    const logId = useRef(0);
    const scrollRef = useRef<HTMLDivElement>(null);
    const esRef = useRef<EventSource | null>(null);

    const addLog = (stage: string, msg: string, type: LogEntry['type'] = 'info') => {
        setLogs(prev => [...prev.slice(-100), {
            id: logId.current++,
            time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
            stage,
            msg,
            type
        }]);
    };

    useEffect(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }
    }, [logs]);

    // Cleanup SSE on unmount
    useEffect(() => {
        return () => {
            esRef.current?.close();
        };
    }, []);

    const startPipeline = async () => {
        if (isRunning) return;

        // reset states
        setLogs([]);
        setProgress(0);
        setFinalReport('');
        setCurrentStage('initializing');
        setIsRunning(true);

        const actualTopic = topic === 'custom' ? customTopic : topic;

        addLog('SYS', `发送 E2E 调度指令: ${actualTopic === 'auto' ? '自动巡游热点' : actualTopic}`, 'thought');

        try {
            const resp = await fetch(`${API_BASE}/run`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    topic: actualTopic,
                    platforms: ['weibo', 'zhihu', 'github', 'twitter', 'hackernews'],
                    token_budget: 12000
                })
            });

            const data = await resp.json();
            if (resp.ok && data.run_id) {
                // setCurrentRunId(data.run_id);
                addLog('SYS', `分析任务已经投递. ID: ${data.run_id}`, 'success');
                connectSSE(data.run_id);
            } else {
                throw new Error(data.detail || '任务创建响应异常');
            }
        } catch (err: unknown) {
            const errorMessage = err instanceof Error ? err.message : String(err);
            addLog('SYS', `投递失败: ${errorMessage}`, 'error');
            setIsRunning(false);
            setCurrentStage('idle');
        }
    };

    const connectSSE = (runId: string) => {
        if (esRef.current) {
            esRef.current.close();
        }

        const eventSource = new EventSource(`${API_BASE}/stream/${runId}`);
        esRef.current = eventSource;

        eventSource.onopen = () => {
            addLog('SYS', '建立脑机长连接 (EventSource Stream)', 'info');
        };

        eventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);

                switch (data.event) {
                    case 'connected':
                        break;

                    case 'run_complete':
                        eventSource.close();
                        setIsRunning(false);
                        setCurrentStage('complete');
                        addLog('SYS', 'E2E 推演流程全部完成', 'success');
                        // Backend will embed final report in result if we poll status
                        fetchResult(runId);
                        break;

                    case 'stage_transition':
                        setCurrentStage(data.stage);
                        if (data.percent !== undefined) {
                            setProgress(data.percent);
                        }
                        addLog('COORD', `进入阶段: ${data.stage} (${data.percent || 0}%)`, 'info');
                        break;

                    case 'subagent_log':
                        addLog(data.source.toUpperCase(), data.content, data.type || 'info');
                        break;

                    case 'subagent_start':
                        addLog(data.agent_type.toUpperCase(), `智能体开始作业: ${data.query}`, 'thought');
                        break;

                    case 'subagent_complete':
                        addLog(data.agent_type.toUpperCase(), `作业完结`, 'success');
                        if (data.result && data.result.report) {
                            setFinalReport(data.result.report);
                        } else if (data.result && data.result.analysis) {
                            addLog(data.agent_type.toUpperCase(), `生成局部洞见 (${data.result.analysis.length} 字符)`, 'thought');
                        }
                        break;

                    case 'subagent_error':
                        addLog(data.agent_type.toUpperCase(), `遭遇错误: ${data.error}`, 'error');
                        break;

                    case 'error':
                        addLog('COORD', `系统级错误: ${data.error}`, 'error');
                        setCurrentStage('error');
                        setIsRunning(false);
                        eventSource.close();
                        break;

                    default:
                        // Generic log
                        addLog('INFO', JSON.stringify(data), 'info');
                }
            } catch (err: unknown) {
                // handle malformed JSON
            }
        };

        eventSource.onerror = () => {
            addLog('SYS', 'SSE 连接异常断开，可能后端推演已结束或崩溃', 'warning');
            eventSource.close();
            setIsRunning(false);
        };
    };

    const fetchResult = async (runId: string) => {
        try {
            const resp = await fetch(`${API_BASE}/status/${runId}`);
            const data = await resp.json();
            if (data && data.result && data.result.result && data.result.result.report) {
                setFinalReport(data.result.result.report);
            }
        } catch (err: unknown) {
            console.warn("Could not fetch final status", err);
        }
    };

    // 阶段显示组件
    const StageIndicator = ({ active, label, isPast }: { active: boolean, label: string, isPast: boolean }) => (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, opacity: active || isPast ? 1 : 0.3 }}>
            <div style={{
                width: 14, height: 14, borderRadius: '50%',
                background: active ? '#ff5c00' : isPast ? '#34d399' : '#333',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                boxShadow: active ? '0 0 10px rgba(255,92,0,0.5)' : 'none',
                transition: 'all 0.3s'
            }}>
                {isPast && !active && <div style={{ width: 6, height: 6, borderRadius: '50%', background: '#fff' }} />}
            </div>
            <span style={{ fontSize: 13, fontWeight: active ? 800 : 500, color: active ? '#ff5c00' : isPast ? '#c9d1d9' : '#666' }}>
                {label}
            </span>
            {active && <Loader2 size={12} className="animate-spin" style={{ color: '#ff5c00' }} />}
        </div>
    );

    const stagesDef = [
        { id: 'phase0_crawl', label: '1. 热点侦查' },
        { id: 'phase1_align', label: '2. 数据对齐' },
        { id: 'phase2_analysis', label: '3. 并行分析' },
        { id: 'phase3_select', label: '4. 选题决策' },
        { id: 'phase4_report', label: '5. IR 报告装订' },
        { id: 'phase5_graph', label: '6. 知识图谱' },
        { id: 'phase6_simulation', label: '7. 社会仿真' },
        { id: 'phase7_predict', label: '8. 趋势预测' }
    ];

    const currentStageIndex = stagesDef.findIndex(s => s.id === currentStage);

    return (
        <div style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: '0px', gap: 16 }}>

            {/* ── 头部控制台 ── */}
            <div style={{
                display: 'flex', flexDirection: 'column', gap: 12, padding: '20px',
                background: 'linear-gradient(135deg, rgba(20,20,20,1) 0%, rgba(10,10,10,1) 100%)',
                border: '2px solid #222', borderRadius: 4
            }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <BrainCircuit size={20} color="#ff5c00" />
                    <h2 style={{ fontSize: 16, fontWeight: 900, margin: 0, letterSpacing: 1 }}>端对端智能体编排系统 (E2E Pipeline)</h2>
                    <div style={{ flex: 1 }} />
                    <div style={{ padding: '4px 10px', background: 'rgba(52, 211, 153, 0.1)', color: '#34d399', fontSize: 11, fontWeight: 800, borderRadius: 2, border: '1px solid rgba(52,211,153,0.3)' }}>
                        V2 Core Engine
                    </div>
                </div>
                <p style={{ fontSize: 13, color: '#888', margin: 0, lineHeight: 1.5 }}>
                    U24Time 后端多智能体全链路推演层。下发指令后，调度器将统合 BettaFish (侦查) 与 MiroFish (推演) 双模组，经过网络搜寻、知识图谱建立与沙盘演化，最终生成研判报告。
                </p>

                <div style={{ display: 'flex', gap: 12, marginTop: 10, alignItems: 'center' }}>
                    <select
                        disabled={isRunning}
                        value={topic}
                        onChange={e => setTopic(e.target.value)}
                        style={{
                            padding: '10px 14px', background: '#0a0a0a', border: '1.5px solid #333',
                            color: '#eee', fontSize: 14, outline: 'none', width: '250px'
                        }}
                    >
                        <option value="auto">🌟 [全自动] 截取今日最热网络话题</option>
                        <option value="推演美中科技脱钩对半导体下游的影响">📌 推演：美中科技界对半导体下游的影响</option>
                        <option value="推演今年全球范围内的 AI 大模型降价潮趋势">📌 推演：AI大模型降价潮及商业模式变迁</option>
                        <option value="custom">✏️ 手动输入分析主旨...</option>
                    </select>

                    {topic === 'custom' && (
                        <input
                            disabled={isRunning}
                            value={customTopic}
                            onChange={e => setCustomTopic(e.target.value)}
                            placeholder="例如: 华尔街今夜的降息预期..."
                            style={{
                                flex: 1, padding: '10px 14px', background: '#0a0a0a', border: '1.5px solid #333',
                                color: '#fff', fontSize: 14, outline: 'none'
                            }}
                        />
                    )}

                    <button
                        onClick={startPipeline}
                        disabled={isRunning || (topic === 'custom' && !customTopic.trim())}
                        style={{
                            padding: '10px 24px', background: isRunning ? '#333' : '#ff5c00', color: '#fff', border: 'none',
                            fontWeight: 800, fontSize: 14, cursor: isRunning ? 'not-allowed' : 'pointer',
                            display: 'flex', alignItems: 'center', gap: 8, transition: 'background 0.2s'
                        }}
                    >
                        {isRunning ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} fill="currentColor" />}
                        {isRunning ? '脑机链入中...' : '发起深度推演'}
                    </button>
                </div>

                {/* 进度条展示 */}
                <div style={{ position: 'relative', width: '100%', height: 4, background: '#111', borderRadius: 2, overflow: 'hidden' }}>
                    <motion.div
                        initial={{ width: 0 }}
                        animate={{ width: `${progress}%` }}
                        transition={{ duration: 0.8, ease: "easeOut" }}
                        style={{ position: 'absolute', top: 0, left: 0, height: '100%', background: 'linear-gradient(90deg, #ff5c00, #ff8c00)', boxShadow: '0 0 8px rgba(255,140,0,0.5)' }}
                    />
                </div>
            </div>

            <div style={{ display: 'flex', gap: 16, flex: 1, minHeight: 0 }}>

                {/* ── 左侧：状态链与流输出 ── */}
                <div style={{ width: '400px', display: 'flex', flexDirection: 'column', gap: 16, flexShrink: 0 }}>

                    <div style={{ background: '#0c0c0c', border: '2px solid #222', padding: '16px', display: 'flex', flexDirection: 'column', gap: 14 }}>
                        <div style={{ fontSize: 11, fontWeight: 800, color: '#666', letterSpacing: 1, marginBottom: 4 }}>运行阶段 (PHASES)</div>
                        {stagesDef.map((s, idx) => (
                            <StageIndicator
                                key={s.id}
                                label={s.label}
                                active={currentStage === s.id}
                                isPast={idx < currentStageIndex || currentStage === 'complete'}
                            />
                        ))}
                        {currentStage === 'complete' && (
                            <div style={{ marginTop: 10, padding: 10, background: 'rgba(52,211,153,0.1)', color: '#34d399', fontSize: 13, fontWeight: 700, textAlign: 'center', border: '1px solid rgba(52,211,153,0.3)' }}>
                                推演已达成
                            </div>
                        )}
                        {currentStage === 'error' && (
                            <div style={{ marginTop: 10, padding: 10, background: 'rgba(248,113,113,0.1)', color: '#f87171', fontSize: 13, fontWeight: 700, textAlign: 'center', border: '1px solid rgba(248,113,113,0.3)' }}>
                                运行遭遇致命异常
                            </div>
                        )}
                    </div>

                    <div style={{ flex: 1, background: '#070707', border: '2px solid #222', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
                        <div style={{ padding: '8px 14px', background: '#0f0f0f', borderBottom: '2px solid #1a1a1a', display: 'flex', alignItems: 'center', gap: 8 }}>
                            <Terminal size={14} color="#666" />
                            <span style={{ fontSize: 12, fontWeight: 800, color: '#888', letterSpacing: 1 }}>子智能体思考日志</span>
                        </div>
                        <div ref={scrollRef} style={{ flex: 1, overflow: 'auto', padding: '10px 0', fontFamily: 'monospace', fontSize: 12 }}>
                            <AnimatePresence initial={false}>
                                {logs.map(log => (
                                    <motion.div
                                        key={log.id}
                                        initial={{ opacity: 0, x: -5 }}
                                        animate={{ opacity: 1, x: 0 }}
                                        style={{
                                            padding: '4px 14px', display: 'flex', gap: 8, lineHeight: 1.4,
                                            color: log.type === 'error' ? '#f87171' : log.type === 'success' ? '#34d399' : log.type === 'thought' ? '#a78bfa' : '#c9d1d9',
                                            background: log.type === 'error' ? 'rgba(248,113,113,0.05)' : 'transparent'
                                        }}
                                    >
                                        <span style={{ color: '#555', flexShrink: 0 }}>{log.time}</span>
                                        <span style={{
                                            color: log.stage === 'COORD' ? '#ff5c00' :
                                                log.stage === 'BETTAFISH' ? '#34d399' :
                                                    log.stage === 'MIROFISH' ? '#c084fc' :
                                                        log.stage === 'SIMAGENT' ? '#38bdf8' : '#666',
                                            fontWeight: 800, minWidth: 80, flexShrink: 0
                                        }}>[{log.stage}]</span>
                                        <span style={{ wordBreak: 'break-all' }}>{log.msg}</span>
                                    </motion.div>
                                ))}
                            </AnimatePresence>
                            {isRunning && (
                                <div style={{ padding: '8px 14px', display: 'flex', alignItems: 'center', gap: 6 }}>
                                    <motion.span animate={{ opacity: [1, 0, 1] }} transition={{ duration: 1, repeat: Infinity, ease: "linear" }} style={{ width: 8, height: 14, background: '#666', display: 'inline-block' }} />
                                </div>
                            )}
                        </div>
                    </div>
                </div>

                {/* ── 右侧：AI 产出报告区域 ── */}
                <div style={{ flex: 1, background: '#0a0a0a', border: '2px solid #222', display: 'flex', flexDirection: 'column' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '14px 20px', background: '#111', borderBottom: '2px solid #222' }}>
                        <BookOpen size={18} color="#c084fc" />
                        <span style={{ fontWeight: 800, fontSize: 14, letterSpacing: 1 }}>MiroFish 全球态势研判简报</span>
                        <div style={{ flex: 1 }} />
                        {isRunning && <span style={{ fontSize: 12, color: '#ffaa00', display: 'flex', alignItems: 'center', gap: 6 }}><Activity size={12} className="animate-pulse" /> 网络撰写中...</span>}
                    </div>
                    <div className="markdown-content" style={{ flex: 1, overflow: 'auto', padding: '24px 30px', fontSize: 14, lineHeight: 1.8, color: '#e0e0e0', opacity: finalReport ? 1 : 0.6 }}>
                        {finalReport ? (
                            <div style={{ animation: 'fade-in 0.5s ease-out' }}>
                                <ReactMarkdown remarkPlugins={[remarkGfm]}>{finalReport}</ReactMarkdown>
                            </div>
                        ) : (
                            <div style={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: '#555', gap: 16 }}>
                                {isRunning ? (
                                    <>
                                        <BrainCircuit size={48} className="animate-pulse" style={{ color: '#333' }} />
                                        <p style={{ margin: 0 }}>正在搜集高维数据，最终战储报告将呈递于此...</p>
                                    </>
                                ) : (
                                    <>
                                        <AlertCircle size={48} style={{ color: '#222' }} />
                                        <p style={{ margin: 0 }}>在左侧控制台开启全新的多智能体推演进程以获取沙盒战略报告。</p>
                                    </>
                                )}
                            </div>
                        )}
                    </div>
                </div>

            </div>
        </div >
    );
}
