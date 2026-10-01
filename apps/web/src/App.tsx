import { FormEvent, useEffect, useMemo, useState } from 'react'
import { Link, Navigate, NavLink, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import { ReactFlow, addEdge, Background, Controls, Handle, MiniMap, Position, useEdgesState, useNodesState, type Connection, type Edge, type Node } from '@xyflow/react'
import { Activity, ArrowDownToLine, Blocks, Check, ChevronRight, CircleHelp, Clock3, KeyRound, LayoutDashboard, LogOut, Plus, Play, Settings, Trash2, Workflow as WorkflowIcon } from 'lucide-react'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'
type Identity = { id: string; email: string; organization_id?: string }
type WorkflowRecord = { id: string; name: string; definition: Definition; enabled: boolean; published_version_id?: string | null; schedule_cron?: string | null; updated_at: string }
type Definition = { nodes: Node[]; edges: Edge[] }
type Execution = { id: string; workflow_id: string; workflow_version_id: string; status: string; trigger_input: Record<string, unknown>; result?: unknown; error?: string; retry_count: number; created_at: string; started_at?: string; finished_at?: string; nodes?: Array<{ id: string; node_id: string; node_type: string; status: string; input: unknown; output?: unknown; error?: string; retry_count: number; duration_ms?: number }> }

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = localStorage.getItem('flowforge-token')
  const response = await fetch(`${API}${path}`, { ...options, headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}), ...options.headers } })
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}))
    throw new Error(payload.detail || `Request failed (${response.status})`)
  }
  if (response.status === 204) return undefined as T
  return response.json()
}

const nodeCatalog = [
  { type: 'manual-trigger', name: 'Manual Trigger', group: 'Triggers', icon: Play },
  { type: 'http-request', name: 'HTTP Request', group: 'Data', icon: ArrowDownToLine },
  { type: 'json-transform', name: 'JSON Transform', group: 'Data', icon: Blocks },
  { type: 'condition', name: 'Condition', group: 'Logic', icon: CircleHelp },
  { type: 'filter', name: 'Filter', group: 'Logic', icon: Activity },
  { type: 'delay', name: 'Delay', group: 'Logic', icon: Clock3 },
  { type: 'llm-prompt', name: 'LLM Prompt', group: 'AI', icon: Blocks },
  { type: 'summarizer', name: 'Summarizer', group: 'AI', icon: Blocks },
  { type: 'email', name: 'Email', group: 'Actions', icon: ArrowDownToLine },
  { type: 'webhook', name: 'Webhook', group: 'Actions', icon: ArrowDownToLine },
  { type: 'database-query', name: 'Database Query', group: 'Data', icon: Blocks },
]

function CanvasNode({ data, selected }: { data: { type: string; config?: Record<string, unknown> }; selected?: boolean }) {
  const item = nodeCatalog.find((entry) => entry.type === data.type)
  const Icon = item?.icon || Blocks
  return <div className={`flow-node ${selected ? 'selected' : ''} type-${data.type}`}><Handle type="target" position={Position.Left} /><div className="node-icon"><Icon size={15} /></div><div className="node-copy"><strong>{item?.name || data.type}</strong><small>{data.config?.url ? String(data.config.url) : data.config?.prompt ? String(data.config.prompt).slice(0, 28) : 'Configure step'}</small></div><Handle type="source" position={Position.Right} id="default" />{data.type === 'condition' && <><Handle type="source" position={Position.Bottom} id="true" style={{ left: '35%' }} /><Handle type="source" position={Position.Bottom} id="false" style={{ left: '70%' }} /></>}</div>
}
const nodeTypes = { workflow: CanvasNode }

function App() {
  const [token, setToken] = useState(localStorage.getItem('flowforge-token'))
  const [identity, setIdentity] = useState<Identity | null>(null)
  const [authReady, setAuthReady] = useState(!token)
  useEffect(() => {
    if (!token) { setAuthReady(true); return }
    request<Identity>('/auth/me').then(setIdentity).catch(() => { localStorage.removeItem('flowforge-token'); setToken(null) }).finally(() => setAuthReady(true))
  }, [token])
  const logout = async () => { try { await request('/auth/logout', { method: 'POST' }) } catch { /* Local session still ends if the API is unavailable. */ } localStorage.removeItem('flowforge-token'); setToken(null); setIdentity(null) }
  if (!authReady) return <div className="loading-page">Connecting to Flowforge…</div>
  return <Routes>
    <Route path="/login" element={token ? <Navigate to="/dashboard" /> : <AuthPage mode="login" onAuth={(nextToken, user) => { localStorage.setItem('flowforge-token', nextToken); setToken(nextToken); setIdentity(user) }} />} />
    <Route path="/register" element={token ? <Navigate to="/dashboard" /> : <AuthPage mode="register" onAuth={(nextToken, user) => { localStorage.setItem('flowforge-token', nextToken); setToken(nextToken); setIdentity(user) }} />} />
    <Route path="*" element={token ? <Shell identity={identity} logout={logout} /> : <Navigate to="/login" />} />
  </Routes>
}

function AuthPage({ mode, onAuth }: { mode: 'login' | 'register'; onAuth: (token: string, user: Identity) => void }) {
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const navigate = useNavigate()
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(''); setBusy(true)
    const form = new FormData(event.currentTarget)
    try {
      const result = await request<{ access_token: string; user: Identity }>(`/auth/${mode}`, { method: 'POST', body: JSON.stringify({ email: form.get('email'), password: form.get('password'), ...(mode === 'register' ? { organization_name: form.get('organization') } : {}) }) })
      onAuth(result.access_token, result.user); navigate('/dashboard')
    } catch (reason) { setError((reason as Error).message) } finally { setBusy(false) }
  }
  return <main className="auth-page"><div className="auth-brand"><span className="brand-mark">F</span><span>FLOWFORGE<span className="brand-dot">.</span></span></div><section className="auth-panel"><p className="eyebrow">WORKFLOW AUTOMATION</p><h1>{mode === 'login' ? 'Welcome back.' : 'Build your workspace.'}</h1><p className="muted">{mode === 'login' ? 'Sign in to continue your work.' : 'Create an account to start automating.'}</p><form onSubmit={submit} className="stack-form"><label>Email address<input name="email" type="email" autoComplete="email" required /></label>{mode === 'register' && <label>Workspace name<input name="organization" required minLength={1} maxLength={160} /></label>}<label>Password<input name="password" type="password" autoComplete={mode === 'login' ? 'current-password' : 'new-password'} required minLength={mode === 'register' ? 10 : 1} maxLength={72} /></label>{error && <div className="error-banner">{error}</div>}<button className="button primary full" disabled={busy}>{busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}<ChevronRight size={16} /></button></form><p className="auth-switch">{mode === 'login' ? 'New to Flowforge?' : 'Already have an account?'} <Link to={mode === 'login' ? '/register' : '/login'}>{mode === 'login' ? 'Create account' : 'Sign in'}</Link></p></section><span className="auth-foot">AUTOMATION, WITH INTENTION.</span></main>
}

function Shell({ identity, logout }: { identity: Identity | null; logout: () => void }) {
  const nav = [{ to: '/dashboard', label: 'Overview', icon: LayoutDashboard }, { to: '/workflows', label: 'Workflows', icon: WorkflowIcon }, { to: '/settings/integrations', label: 'Integrations', icon: KeyRound }, { to: '/settings', label: 'Workspace', icon: Settings }]
  return <div className="app-shell"><aside className="sidebar"><Link to="/dashboard" className="brand"><span className="brand-mark">F</span><span>FLOWFORGE<span className="brand-dot">.</span></span></Link><div className="workspace-chip"><span className="workspace-avatar">{identity?.email?.[0]?.toUpperCase() || 'W'}</span><span><strong>{identity?.email?.split('@')[0] || 'Workspace'}</strong><small>Personal workspace</small></span><ChevronRight size={14} /></div><nav>{nav.map(({ to, label, icon: Icon }) => <NavLink key={to} to={to} className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}><Icon size={17} />{label}</NavLink>)}</nav><div className="sidebar-bottom"><div className="connection-status"><i /> API connected</div><button className="nav-link logout-button" onClick={logout}><LogOut size={17} />Sign out</button></div></aside><main className="main-area"><header className="topbar"><span className="crumb">Workspace <span>/</span> <strong>Automation</strong></span><div className="topbar-right"><span className="user-email">{identity?.email}</span><span className="user-avatar">{identity?.email?.[0]?.toUpperCase()}</span></div></header><div className="page-content"><Routes><Route path="/" element={<Navigate to="/dashboard" replace />} /><Route path="/dashboard" element={<Dashboard />} /><Route path="/workflows" element={<Workflows />} /><Route path="/workflows/new" element={<Editor />} /><Route path="/workflows/:id" element={<Editor />} /><Route path="/executions/:id" element={<ExecutionDetail />} /><Route path="/settings" element={<SettingsPage />} /><Route path="/settings/integrations" element={<Integrations />} /><Route path="*" element={<Navigate to="/dashboard" replace />} /></Routes></div></main></div>
}

function PageHeading({ kicker, title, action }: { kicker: string; title: string; action?: React.ReactNode }) { return <div className="page-heading"><div><p className="eyebrow">{kicker}</p><h1>{title}</h1></div>{action}</div> }

function Dashboard() {
  const [data, setData] = useState<{ workflow_count: number; active_workflows: number; execution_counts: Record<string, number>; recent_executions: Execution[] } | null>(null)
  const [error, setError] = useState('')
  useEffect(() => { request<typeof data>('/dashboard').then(setData).catch((reason) => setError((reason as Error).message)) }, [])
  if (error) return <div className="error-banner">{error}</div>
  if (!data) return <div className="loading-inline">Loading workspace data…</div>
  const successes = data.execution_counts.success || 0
  const failed = data.execution_counts.failed || 0
  return <><PageHeading kicker="WORKSPACE / OVERVIEW" title="Your automation desk" action={<Link to="/workflows/new" className="button primary"><Plus size={16} />New workflow</Link>} /><div className="metric-grid"><Metric label="Total workflows" value={data.workflow_count} detail="Across this workspace" /><Metric label="Active workflows" value={data.active_workflows} detail="Published and enabled" /><Metric label="Successful runs" value={successes} detail="All recorded executions" accent="green" /><Metric label="Failed runs" value={failed} detail="Review and retry" accent={failed ? 'red' : 'neutral'} /></div><section className="section-block"><div className="section-heading"><div><p className="eyebrow">LATEST ACTIVITY</p><h2>Recent executions</h2></div><Link to="/workflows" className="text-link">All workflows <ChevronRight size={15} /></Link></div><ExecutionTable executions={data.recent_executions} /></section><section className="start-strip"><div className="strip-symbol"><WorkflowIcon size={20} /></div><div><strong>Make the first step count.</strong><p>Build a workflow, connect your tools, and let the run history tell the story.</p></div><Link to="/workflows/new" className="button outline">Open editor <ChevronRight size={15} /></Link></section></>
}
function Metric({ label, value, detail, accent = 'neutral' }: { label: string; value: number; detail: string; accent?: string }) { return <div className="metric"><span className={`metric-indicator ${accent}`} /><p>{label}</p><strong>{value}</strong><small>{detail}</small></div> }

function Workflows() {
  const [items, setItems] = useState<WorkflowRecord[] | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')
  const navigate = useNavigate()
  const load = () => request<WorkflowRecord[]>('/workflows').then(setItems).catch((reason) => setError((reason as Error).message))
  useEffect(() => { void load() }, [])
  async function remove(item: WorkflowRecord) { if (!window.confirm(`Delete “${item.name}”?`)) return; setBusy(item.id); try { await request(`/workflows/${item.id}`, { method: 'DELETE' }); await load() } catch (reason) { setError((reason as Error).message) } finally { setBusy('') } }
  async function run(item: WorkflowRecord) { setBusy(item.id); try { const result = await request<{ id: string }>(`/workflows/${item.id}/execute`, { method: 'POST', body: JSON.stringify({ input: {} }) }); navigate(`/executions/${result.id}`) } catch (reason) { setError((reason as Error).message) } finally { setBusy('') } }
  return <><PageHeading kicker="AUTOMATION / WORKFLOWS" title="Workflows" action={<Link to="/workflows/new" className="button primary"><Plus size={16} />Create workflow</Link>} />{error && <div className="error-banner">{error}</div>}{items === null ? <div className="loading-inline">Loading workflows…</div> : items.length === 0 ? <div className="empty-state"><div className="empty-icon"><WorkflowIcon /></div><h2>No workflows yet</h2><p>Create a workflow from scratch or start from a natural-language brief.</p><Link to="/workflows/new" className="button primary"><Plus size={16} />Create your first workflow</Link></div> : <div className="workflow-list">{items.map((item) => <article className="workflow-row" key={item.id}><span className="workflow-glyph"><WorkflowIcon size={19} /></span><div className="workflow-row-copy"><Link to={`/workflows/${item.id}`}><strong>{item.name}</strong></Link><span>{item.definition?.nodes?.length || 0} steps · Updated {new Date(item.updated_at).toLocaleDateString()}</span></div><span className={`status-pill ${item.published_version_id ? 'success' : 'draft'}`}>{item.published_version_id ? 'Published' : 'Draft'}</span><button title="Run workflow" className="icon-button" disabled={!item.published_version_id || busy === item.id} onClick={() => run(item)}><Play size={16} /></button><button title="Delete workflow" className="icon-button danger-icon" disabled={busy === item.id} onClick={() => remove(item)}><Trash2 size={16} /></button></article>)}</div>}</>
}

function defaultNode(type: string, position: { x: number; y: number }): Node {
  const id = `${type.replaceAll('-', '_')}_${crypto.randomUUID().slice(0, 6)}`
  const defaults: Record<string, Record<string, unknown>> = {
    'manual-trigger': {}, 'http-request': { method: 'GET', url: '', headers: {}, params: {}, body: {}, timeout: 20 },
    'json-transform': { template: { value: '{{nodes.manual_trigger.output.input}}' } },
    condition: { left: '', operator: 'equals', right: '' }, filter: { items: [], key: '', value: '' }, delay: { seconds: 1 },
    'llm-prompt': { system_prompt: 'You are a concise assistant.', prompt: '', temperature: 0.2, max_tokens: 500 },
    summarizer: { prompt: 'Summarize: {{nodes.manual_trigger.output.input}}' }, email: { to: '', subject: '', body: '' },
    webhook: { method: 'POST', url: '', headers: {} }, 'database-query': { query: 'SELECT 1', parameters: {} },
  }
  return { id, type: 'workflow', position, data: { type, config: defaults[type] || {} } }
}

function Editor() {
  const { id } = useParams()
  const isNew = !id || id === 'new'
  const navigate = useNavigate()
  const [name, setName] = useState('Untitled workflow')
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([defaultNode('manual-trigger', { x: 120, y: 190 })])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [configText, setConfigText] = useState('{}')
  const [workflowId, setWorkflowId] = useState(isNew ? null : id!)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [prompt, setPrompt] = useState('')
  const [missing, setMissing] = useState<string[]>([])
  const [cron, setCron] = useState('')
  const selectedNode = nodes.find((node) => node.id === selected)
  useEffect(() => {
    if (isNew) return
    request<WorkflowRecord>(`/workflows/${id}`).then((item) => { setName(item.name); setNodes(item.definition.nodes || []); setEdges(item.definition.edges || []); setCron(item.schedule_cron || '') }).catch((reason) => setError((reason as Error).message))
  }, [id, isNew, setEdges, setNodes])
  useEffect(() => { setConfigText(JSON.stringify(selectedNode?.data.config || {}, null, 2)) }, [selectedNode?.id])
  const flowNodes = useMemo(() => nodes.map((node) => ({ ...node, type: 'workflow' })), [nodes])
  const onConnect = (connection: Connection) => setEdges((current) => addEdge({ ...connection, animated: true }, current))
  const addNode = (type: string) => { const next = defaultNode(type, { x: 180 + Math.random() * 280, y: 160 + Math.random() * 220 }); setNodes((current) => [...current, next]); setSelected(next.id) }
  async function save(publish = false): Promise<string | null> {
    setBusy(true); setError(''); setMessage('')
    try {
      let parsedConfig: Record<string, unknown> | null = null
      if (selectedNode) { parsedConfig = JSON.parse(configText) as Record<string, unknown> }
      const currentNodes = nodes.map((node) => node.id === selected && parsedConfig ? { ...node, data: { ...node.data, config: parsedConfig } } : node)
      const definition = { nodes: currentNodes.map((node) => ({ id: node.id, data: node.data, position: node.position })), edges }
      const payload = { name, definition }
      const saved = workflowId ? await request<WorkflowRecord>(`/workflows/${workflowId}`, { method: 'PUT', body: JSON.stringify(payload) }) : await request<WorkflowRecord>('/workflows', { method: 'POST', body: JSON.stringify(payload) })
      setWorkflowId(saved.id); setNodes(currentNodes); setMessage('Saved')
      if (publish) { const result = await request<{ version: number }>(`/workflows/${saved.id}/publish`, { method: 'POST' }); setMessage(`Published version ${result.version}`) }
      if (isNew) navigate(`/workflows/${saved.id}`, { replace: true })
      return saved.id
    } catch (reason) { setError((reason as Error).message); return null } finally { setBusy(false) }
  }
  async function run() { setError(''); const savedId = await save(true); if (!savedId) return; setBusy(true); try { const result = await request<{ id: string }>(`/workflows/${savedId}/execute`, { method: 'POST', body: JSON.stringify({ input: {} }) }); navigate(`/executions/${result.id}`) } catch (reason) { setError((reason as Error).message) } finally { setBusy(false) } }
  async function schedule() { if (!workflowId) { setError('Save the workflow before scheduling it.'); return }; setBusy(true); setError(''); try { const result = await request<{ enabled: boolean; cron: string | null }>(`/workflows/${workflowId}/schedule`, { method: 'POST', body: JSON.stringify({ cron: cron || null, enabled: Boolean(cron) }) }); setMessage(result.enabled ? `Schedule enabled: ${result.cron}` : 'Schedule disabled') } catch (reason) { setError((reason as Error).message) } finally { setBusy(false) } }
  async function generate() { setBusy(true); setError(''); setMissing([]); try { const generated = await request<{ name: string; nodes: Array<{ id: string; type: string; config: Record<string, unknown>; x: number; y: number }>; edges: Edge[]; missing_information: string[] }>('/agent/generate-workflow', { method: 'POST', body: JSON.stringify({ prompt }) }); setName(generated.name); setNodes(generated.nodes.map((node) => ({ id: node.id, type: 'workflow', position: { x: node.x, y: node.y }, data: { type: node.type, config: node.config } }))); setEdges(generated.edges); setMissing(generated.missing_information); setMessage('AI draft generated. Review every node before saving or publishing.') } catch (reason) { setError((reason as Error).message) } finally { setBusy(false) } }
  const removeSelected = () => { if (!selected) return; setNodes((current) => current.filter((node) => node.id !== selected)); setEdges((current) => current.filter((edge) => edge.source !== selected && edge.target !== selected)); setSelected(null) }
  return <div className="editor-page"><div className="editor-top"><div><Link to="/workflows" className="back-link">Workflows</Link><div className="editor-title"><input aria-label="Workflow name" value={name} onChange={(event) => setName(event.target.value)} /><span className={`status-pill ${workflowId ? 'draft' : 'draft'}`}>Draft</span></div></div><div className="editor-actions">{message && <span className="inline-success"><Check size={14} />{message}</span>}<button className="button outline" onClick={() => save(false)} disabled={busy}>Save</button><button className="button outline" onClick={() => save(true)} disabled={busy}>Publish</button><button className="button primary" onClick={run} disabled={busy}><Play size={15} />Run</button></div></div>{error && <div className="error-banner">{error}</div>}<div className="editor-tools"><div className="tool-section"><strong>ADD STEP</strong><div className="node-tool-list">{nodeCatalog.map(({ type, name: label, icon: Icon }) => <button key={type} className="node-tool" onClick={() => addNode(type)}><Icon size={15} /><span>{label}</span><Plus size={13} /></button>)}</div></div><section className="canvas-wrap"><ReactFlow nodes={flowNodes} edges={edges} nodeTypes={nodeTypes} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect} onNodeClick={(_, node) => setSelected(node.id)} onPaneClick={() => setSelected(null)} fitView deleteKeyCode={['Backspace', 'Delete']}><Background color="#c8cec9" gap={22} /><Controls /><MiniMap nodeColor={(node) => node.data.type === 'manual-trigger' ? '#43866f' : '#4a6c87'} /></ReactFlow><div className="canvas-caption">{nodes.length} nodes <span>·</span> {edges.length} connections</div></section><aside className="config-panel"><div className="panel-head"><div><p className="eyebrow">NODE SETTINGS</p><h3>{selectedNode ? nodeCatalog.find((item) => item.type === selectedNode.data.type)?.name : 'Workflow setup'}</h3></div>{selectedNode && <button className="icon-button danger-icon" title="Delete selected node" onClick={removeSelected}><Trash2 size={15} /></button>}</div>{selectedNode ? <><p className="field-hint">Edit this node's JSON configuration. Expressions like <code>{'{{nodes.step_id.output.value}}'}</code> resolve from upstream output.</p><textarea aria-label="Node configuration JSON" className="json-editor" value={configText} onChange={(event) => setConfigText(event.target.value)} spellCheck={false} /><div className="config-actions"><button className="button small outline" onClick={() => { try { const config = JSON.parse(configText); setNodes((current) => current.map((node) => node.id === selected ? { ...node, data: { ...node.data, config } } : node)); setMessage('Node configuration applied') } catch { setError('Node config must be valid JSON') } }}>Apply config</button></div></> : <><p className="field-hint">Select a node on the canvas to configure it. Drag nodes to arrange the workflow and connect handles to define execution order.</p><label className="field-label">Scheduled cron expression<input value={cron} onChange={(event) => setCron(event.target.value)} placeholder="0 9 * * 1-5" /></label><button className="button small outline full" onClick={schedule} disabled={busy || !workflowId}>Save schedule</button></>}<div className="agent-box"><div className="agent-heading"><span className="agent-spark">✳</span><strong>Describe a workflow</strong></div><textarea aria-label="Workflow description" value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="Every morning check inventory and email me products below 10 units…" /><button className="button small dark full" onClick={generate} disabled={busy || prompt.trim().length < 5}>{busy ? 'Working…' : 'Generate draft'}<ChevronRight size={14} /></button>{missing.length > 0 && <div className="missing-info"><strong>Needs your input</strong>{missing.map((item) => <span key={item}>{item}</span>)}</div>}</div></aside></div></div>
}

function ExecutionTable({ executions }: { executions: Execution[] }) {
  const [workflowNames, setWorkflowNames] = useState<Record<string, string>>({})
  useEffect(() => { request<WorkflowRecord[]>('/workflows').then((items) => setWorkflowNames(Object.fromEntries(items.map((item) => [item.id, item.name])))).catch(() => undefined) }, [])
  if (!executions.length) return <div className="table-empty">No executions have been recorded yet.</div>
  return <div className="table-scroll"><table><thead><tr><th>Workflow</th><th>Status</th><th>Started</th><th>Duration</th><th>Execution</th></tr></thead><tbody>{executions.map((item) => <tr key={item.id}><td><Link to={`/executions/${item.id}`} className="table-workflow">{workflowNames[item.workflow_id] || 'Workflow'}</Link></td><td><span className={`status-pill ${item.status}`}>{item.status}</span></td><td>{item.started_at ? new Date(item.started_at).toLocaleString() : new Date(item.created_at).toLocaleString()}</td><td>{item.started_at && item.finished_at ? `${Math.max(0, Math.round((new Date(item.finished_at).getTime() - new Date(item.started_at).getTime()) / 1000))}s` : '—'}</td><td><Link className="mono-link" to={`/executions/${item.id}`}>{item.id.slice(0, 8)}…</Link></td></tr>)}</tbody></table></div>
}

function ExecutionDetail() {
  const { id } = useParams()
  const [execution, setExecution] = useState<Execution | null>(null)
  const [workflow, setWorkflow] = useState<WorkflowRecord | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const navigate = useNavigate()
  useEffect(() => {
    let active = true
    const load = async () => { try { const result = await request<Execution>(`/executions/${id}`); if (active) setExecution(result) } catch (reason) { if (active) setError((reason as Error).message) } }
    void load(); const timer = window.setInterval(() => { if (active) void load() }, 2000)
    return () => { active = false; window.clearInterval(timer) }
  }, [id])
  useEffect(() => { if (execution?.workflow_id) request<WorkflowRecord>(`/workflows/${execution.workflow_id}`).then(setWorkflow).catch(() => undefined) }, [execution?.workflow_id])
  async function retry() { if (!execution) return; setBusy(true); setError(''); try { const result = await request<{ id: string }>(`/executions/${execution.id}/retry`, { method: 'POST' }); navigate(`/executions/${result.id}`) } catch (reason) { setError((reason as Error).message) } finally { setBusy(false) } }
  if (error && !execution) return <div className="error-banner">{error}</div>
  if (!execution) return <div className="loading-inline">Loading execution…</div>
  const duration = execution.started_at ? Math.max(0, Math.round(((execution.finished_at ? new Date(execution.finished_at).getTime() : Date.now()) - new Date(execution.started_at).getTime()) / 1000)) : null
  return <><PageHeading kicker="RUN HISTORY / EXECUTION" title={workflow?.name || 'Execution details'} action={<div className="editor-actions"><span className={`status-pill ${execution.status}`}>{execution.status}</span>{execution.status === 'failed' && <button className="button primary" onClick={retry} disabled={busy}><Activity size={15} />Retry run</button>}</div>} />{error && <div className="error-banner">{error}</div>}<div className="execution-meta"><div><small>EXECUTION ID</small><code>{execution.id}</code></div><div><small>VERSION</small><code>{execution.workflow_version_id.slice(0, 8)}</code></div><div><small>STARTED</small><span>{execution.started_at ? new Date(execution.started_at).toLocaleString() : 'Waiting for worker'}</span></div><div><small>DURATION</small><span>{duration === null ? '—' : `${duration}s`}</span></div><div><small>RETRIES</small><span>{execution.retry_count}</span></div></div>{execution.error && <div className="error-banner"><strong>Execution failed:</strong> {execution.error}</div>}<section className="section-block"><div className="section-heading"><div><p className="eyebrow">RUNTIME INSPECTION</p><h2>Node timeline</h2></div><span className="muted">Refreshes from the server every 2 seconds</span></div>{execution.nodes?.length ? <div className="timeline">{execution.nodes.map((node, index) => <article className="timeline-node" key={node.id}><div className={`timeline-marker ${node.status}`}><span>{index + 1}</span></div><div className="timeline-card"><div className="timeline-top"><div><strong>{node.node_type.replaceAll('-', ' ')}</strong><code>{node.node_id}</code></div><div className="timeline-stats"><span className={`status-pill ${node.status}`}>{node.status}</span><span>{node.duration_ms == null ? '—' : `${node.duration_ms} ms`}</span><span>{node.retry_count} retries</span></div></div>{node.error && <div className="node-error">{node.error}</div>}<div className="inspect-grid"><div><label>INPUT</label><pre>{JSON.stringify(node.input, null, 2)}</pre></div><div><label>OUTPUT</label><pre>{JSON.stringify(node.output ?? null, null, 2)}</pre></div></div></div></article>)}</div> : <div className="table-empty">{execution.status === 'pending' ? 'Queued; waiting for a worker to begin.' : 'No node records have been created.'}</div>}</section></>
}

function Integrations() {
  const [items, setItems] = useState<Array<{ id: string; name: string; kind: string; masked: boolean }>>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const load = () => request<typeof items>('/credentials').then(setItems).catch((reason) => setError((reason as Error).message))
  useEffect(() => { void load() }, [])
  async function save(event: FormEvent<HTMLFormElement>) { event.preventDefault(); setBusy(true); setError(''); const form = new FormData(event.currentTarget); try { await request('/credentials', { method: 'POST', body: JSON.stringify({ name: form.get('name'), kind: form.get('kind'), value: form.get('value') }) }); event.currentTarget.reset(); await load() } catch (reason) { setError((reason as Error).message) } finally { setBusy(false) } }
  async function remove(id: string) { try { await request(`/credentials/${id}`, { method: 'DELETE' }); await load() } catch (reason) { setError((reason as Error).message) } }
  return <><PageHeading kicker="SETTINGS / CONNECTIONS" title="Integrations" /><p className="page-intro">Credentials are encrypted before storage and are never returned by the API.</p>{error && <div className="error-banner">{error}</div>}<section className="settings-section"><div className="section-heading"><div><p className="eyebrow">CONNECTED SECRETS</p><h2>Credential vault</h2></div></div>{items.length ? <div className="credential-list">{items.map((item) => <div className="credential-row" key={item.id}><KeyRound size={17} /><div><strong>{item.name}</strong><small>{item.kind.toUpperCase()} · Secret hidden</small></div><button className="icon-button danger-icon" title="Delete credential" onClick={() => remove(item.id)}><Trash2 size={15} /></button></div>)}</div> : <div className="table-empty">No credentials stored for this workspace.</div>}<form onSubmit={save} className="credential-form"><h3>Add a credential</h3><div className="credential-fields"><label>Name<input name="name" required /></label><label>Type<select name="kind"><option value="http">HTTP / API</option><option value="llm">LLM provider</option><option value="postgres">PostgreSQL</option><option value="smtp">SMTP</option></select></label><label className="secret-field">Secret<input name="value" type="password" autoComplete="new-password" required /></label></div><button className="button primary" disabled={busy}><Plus size={15} />Store credential</button></form></section></>
}

function SettingsPage() {
  const [identity, setIdentity] = useState<Identity | null>(null)
  useEffect(() => { request<Identity>('/auth/me').then(setIdentity).catch(() => undefined) }, [])
  return <><PageHeading kicker="SETTINGS / WORKSPACE" title="Workspace settings" /><section className="settings-section"><p className="eyebrow">CURRENT WORKSPACE</p><h2>Organization</h2><div className="settings-detail"><span>Member</span><strong>{identity?.email || 'Loading…'}</strong></div><div className="settings-detail"><span>Organization ID</span><code>{identity?.organization_id || 'Loading…'}</code></div><p className="field-hint">Workflows, executions, schedules, webhooks and credentials are isolated to this organization.</p><Link className="button outline" to="/settings/integrations"><KeyRound size={15} />Manage integrations</Link></section></>
}

export default App
