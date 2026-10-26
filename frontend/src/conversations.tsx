import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";
import { useAuth } from "./auth";
import { AgentNavigation } from "./agents";
import { ApiError, validSource, validToolCalls, type CatalogAgent, type ChatEvent, type Conversation, type ConversationSummary, type Message, type Source } from "./agent-api";
import { useAgentApi } from "./use-agent-api";

const retention = "删除后，创建该智能体的教师仍可审计您的身份、问题、回答和引用；记录按部署保留政策保存，不会立即销毁。";

export function ConversationHome() {
  const { identity } = useAuth();
  return identity?.role === "student" ? <StudentHome /> : <Navigate to="/agents/manage" replace />;
}
function StudentHome() {
  const api = useAgentApi();
  const navigate = useNavigate();
  const [catalog, setCatalog] = useState<CatalogAgent[]>([]);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [confirm, setConfirm] = useState<ConversationSummary | null>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  const title = useRef<HTMLHeadingElement>(null);
  const load = useCallback(async () => {
    const [agents, rows] = await Promise.all([api.catalog(), api.conversations()]);
    setCatalog(agents); setConversations(rows.filter(row => !row.deleted_at));
  }, [api]);
  useEffect(() => { void load().catch(() => setError("无法加载会话，请刷新重试。")).finally(() => setBusy(false)); }, [load]);
  useEffect(() => { if (confirm) cancel.current?.focus(); }, [confirm]);
  async function create(id: string) {
    setBusy(true); setError("");
    try { const row = await api.createConversation(id); navigate(`/conversations/${encodeURIComponent(row.id)}`); }
    catch (e) { setError(e instanceof Error ? e.message : "无法创建会话。"); await load().catch(() => undefined); }
    finally { setBusy(false); }
  }
  async function remove() {
    if (!confirm) return;
    setBusy(true); setError("");
    try { await api.deleteConversation(confirm.id); setConversations(rows => rows.filter(row => row.id !== confirm.id)); setConfirm(null); title.current?.focus(); }
    catch (e) { setError(e instanceof Error ? e.message : "无法删除会话。"); }
    finally { setBusy(false); }
  }
  return <main className="page-shell agent-page"><AgentNavigation /><h1 ref={title} tabIndex={-1}>智能体与会话</h1>
    <p>{retention}</p>
    <p role="status">{busy ? "正在处理…" : "已加载本班可用智能体与您的会话。"}</p>
    {error && <p className="error" role="alert">{error}</p>}
    <section className="library-panel" aria-labelledby="catalog"><h2 id="catalog">本班已发布智能体</h2>
      {!busy && !catalog.length && <p>暂无可用智能体，请联系教师。</p>}
      <ul className="agent-list">{catalog.map(a => <li key={a.id}><h3>{a.name}</h3><p>{a.description}</p><button disabled={busy} onClick={() => void create(a.id)}>与 {a.name} 创建会话</button></li>)}</ul>
    </section>
    <section className="library-panel" aria-labelledby="own-conversations"><h2 id="own-conversations">我的会话</h2>
      {!busy && !conversations.length && <p>还没有会话。</p>}
      <ul className="agent-list">{conversations.map(c => <li key={c.id}><Link to={`/conversations/${encodeURIComponent(c.id)}`}>{c.agent_name} · {new Date(c.updated_at).toLocaleString()}</Link>
        <button disabled={busy || !!confirm} onClick={() => setConfirm(c)}>删除 {c.agent_name} 的会话</button>
      </li>)}</ul>
    </section>
    {confirm && <section className="library-panel" role="region" aria-labelledby="delete-title"><h2 id="delete-title">确认删除会话？</h2><p id="retention-notice">{retention}</p>
      <button ref={cancel} disabled={busy} onClick={() => { setConfirm(null); title.current?.focus(); }}>取消删除</button>
      <button disabled={busy} aria-describedby="retention-notice" onClick={() => void remove()}>确认删除会话</button>
    </section>}
  </main>;
}

/** Only link markers that have a matching validated source in this particular message. */
function Answer({ message }: { message: Message }) {
  const sources = new Map(message.citations.filter(validSource).map(s => [s.source_id, s]));
  return <p className="plain-text">{(message.content ?? "").split(/(\[S[1-9][0-9]{0,2}\])/g).map((part, index) => {
    const id = part.slice(1, -1);
    const target = `message-${message.id}-source-${id}`;
    return /^\[S[1-9][0-9]{0,2}\]$/.test(part) && sources.has(id)
      ? <a key={index} href={`#${target}`} onClick={event => { event.preventDefault(); const node = document.getElementById(target); node?.focus(); node?.scrollIntoView?.({ block: "nearest" }); }}>{part}</a>
      : <span key={index}>{part}</span>;
  })}</p>;
}
function MessageHistory({ messages, onDownload }: { messages: Message[]; onDownload: (source: Source) => void }) {
  return <ol className="message-history" aria-label="会话消息">{messages.map(message => <li key={message.id}>
    <article className={`chat-message ${message.role}`} aria-label={`${message.role === "user" ? "学生" : "智能体"}消息 ${message.ordinal}`}>
      <h3>{message.role === "user" ? "学生" : "智能体"}</h3>
      {message.configuration_updated && <p className="degraded-notice">智能体配置已更新，本轮使用新配置。</p>}
      {message.state === "failed" ? <p>本轮生成失败，未提供回答。请确认服务器状态后再决定是否发送新问题。</p> : <Answer message={message} />}
      <p className="muted">{message.state === "processing" ? "处理中／等待服务器确认" : message.state === "failed" ? "失败" : "已完成"}</p>
      {message.role === "assistant" && validToolCalls(message.tool_calls) && message.tool_calls.length > 0 && <section aria-label={`消息 ${message.ordinal} 的工具状态`}>
        <p>工具执行状态独立于回答质量；工具结果不是事实证据。</p>
        <ul>{message.tool_calls.map(call => <li key={call.tool_ref}>{call.tool_ref}：{call.status === "ok" ? "成功" : call.status === "denied" ? "已拒绝" : "执行错误"}（{call.code}）</li>)}</ul>
      </section>}
      {message.applied_agent_revision_id && <p className="muted">配置版本：{message.applied_agent_revision_id}</p>}
      {message.citations.length > 0 && <section aria-label={`消息 ${message.ordinal} 的来源`}>{message.citations.filter(validSource).map(source => <article className="source-card" id={`message-${message.id}-source-${source.source_id}`} key={source.source_id} tabIndex={-1}>
        <h4>{source.source_id} · {source.title}</h4><p>{source.original_filename}</p><p className="plain-text">{source.excerpt}</p>
        <p>{source.page ? `第 ${source.page} 页` : `第 ${source.line_start ?? "?"}–${source.line_end ?? "?"} 行`}{source.section ? ` · ${source.section}` : ""}</p>
        <button onClick={() => onDownload(source)}>下载授权资料 {source.source_id}</button>
      </article>)}</section>}
    </article>
  </li>)}</ol>;
}

export function ConversationPage() {
  const { identity } = useAuth();
  const { conversationId = "" } = useParams();
  return identity?.role === "student" ? <ConversationView key={conversationId} id={conversationId} /> : <Navigate to="/agents/manage" replace />;
}
export function CreatorAuditPage() {
  const { identity } = useAuth();
  const { agentId = "", conversationId } = useParams();
  if (identity?.role !== "teacher") return <Navigate to="/conversations" replace />;
  return conversationId ? <ConversationView key={`${agentId}/${conversationId}`} id={conversationId} auditAgent={agentId} /> : <CreatorAuditList key={agentId} agentId={agentId} />;
}
function CreatorAuditList({ agentId }: { agentId: string }) {
  const api = useAgentApi();
  const [rows, setRows] = useState<Conversation[]>([]);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);
  useEffect(() => {
    let active = true;
    setBusy(true); setRows([]); setError("");
    void api.audit(agentId, filter).then(value => { if (active) setRows(value); })
      .catch(e => { if (active) setError(e instanceof Error ? e.message : "无法读取审计记录。"); })
      .finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [api, agentId, filter]);
  return <main className="page-shell agent-page"><AgentNavigation /><h1>创建者会话审计</h1>
    <p>仅智能体创建者可查看，包含学生删除后保留的内容。</p>
    <label>审计状态<select value={filter} onChange={e => setFilter(e.target.value)}><option value="">全部</option><option value="false">未删除</option><option value="true">学生已删除</option></select></label>
    {busy && <p role="status">正在加载审计记录…</p>}{error && <p className="error" role="alert">{error}</p>}
    <ul className="agent-list">{rows.map(c => <li key={c.id}><Link to={`/agents/${encodeURIComponent(agentId)}/audit/${encodeURIComponent(c.id)}`}>{c.student_account} · {c.agent_name}</Link><p>{c.deleted_at ? "学生已删除（保留审计）" : "未删除"}</p></li>)}</ul>
  </main>;
}

function ConversationView({ id, auditAgent }: { id: string; auditAgent?: string }) {
  const api = useAgentApi();
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [available, setAvailable] = useState(false);
  const [busy, setBusy] = useState(true);
  const [sending, setSending] = useState(false);
  const [interrupted, setInterrupted] = useState(false);
  const [question, setQuestion] = useState("");
  const [error, setError] = useState("");
  const [status, setStatus] = useState("正在加载会话…");
  const input = useRef<HTMLTextAreaElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const controller = useRef<AbortController | null>(null);
  const locked = useRef(false);
  const load = useCallback(async () => {
    setBusy(true); setError("");
    try {
      const row = auditAgent ? await api.auditConversation(auditAgent, id) : await api.conversation(id);
      const catalog = auditAgent ? [] : await api.catalog();
      setConversation(row); setAvailable(!auditAgent && catalog.some(a => a.id === row.agent_id));
      setInterrupted(false); setStatus("已刷新服务器记录。");
    } catch (e) { setConversation(null); setError(e instanceof Error ? e.message : "无法加载会话。"); }
    finally { setBusy(false); }
  }, [api, auditAgent, id]);
  useEffect(() => { void load().then(() => heading.current?.focus()); return () => controller.current?.abort(); }, [load]);
  const processing = conversation?.messages.some(m => m.state === "processing") ?? false;
  async function more() {
    if (!conversation?.next_after_ordinal) return;
    setBusy(true); setError("");
    try {
      const after = conversation.next_after_ordinal;
      const page = auditAgent ? await api.auditConversation(auditAgent, id, after) : await api.conversation(id, after);
      setConversation(current => current ? { ...page, messages: [...current.messages, ...page.messages.filter(m => !current.messages.some(old => old.id === m.id))] } : page);
      setStatus("已加载下一页历史。");
    } catch (e) { setError(e instanceof Error ? e.message : "无法加载历史。"); }
    finally { setBusy(false); }
  }
  async function download(source: Source) {
    try { await api.download(source); } catch (e) { setError(e instanceof Error ? e.message : "无法下载资料。"); }
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (locked.current || busy || !available || processing || interrupted || conversation?.next_after_ordinal) return;
    const content = question.trim();
    if (!content || [...content].length > 20000) { setError("请输入不超过 20000 字符的问题。"); input.current?.focus(); return; }
    locked.current = true; setSending(true); setError(""); setStatus("正在连接…");
    const abort = new AbortController(); controller.current = abort;
    let assistantId = ""; const sources: Source[] = [];
    const receive = (event: ChatEvent) => {
      const { data } = event;
      assistantId = data.assistant_message_id;
      if (event.name === "message.started") {
        setQuestion(""); setStatus(event.data.configuration_updated ? "智能体配置已更新，正在检索本班资料…" : "正在检索本班资料并生成回答…");
        setConversation(current => {
          if (!current) return current;
          const ordinal = current.messages.at(-1)?.ordinal ?? 0;
          const common = { safe_error_code: null, retrieval_mode: null, citations: [], tool_calls: [], created_at: new Date().toISOString(), completed_at: null };
          return { ...current, messages: [...current.messages,
            { ...common, id: data.user_message_id, ordinal: ordinal + 1, role: "user", state: "completed", content, applied_agent_revision_id: null, configuration_updated: false },
            { ...common, id: data.assistant_message_id, ordinal: ordinal + 2, role: "assistant", state: "processing", content: "", applied_agent_revision_id: event.data.configuration_revision_id, configuration_updated: event.data.configuration_updated },
          ] };
        });
      } else if (event.name === "citation") sources.push(event.data.source);
      else {
        setConversation(current => current ? { ...current, messages: current.messages.map(m => {
          if (m.id !== data.assistant_message_id) return m;
          if (event.name === "answer.delta") return { ...m, content: (m.content ?? "") + event.data.delta };
          if (event.name === "message.completed") return { ...m, state: "completed", tool_calls: event.data.meta.tool_calls, citations: [...sources], retrieval_mode: event.data.retrieval_mode, completed_at: event.data.completed_at };
          if (event.name === "message.error") return { ...m, state: "failed", tool_calls: event.data.meta.tool_calls, content: null, citations: [], safe_error_code: event.data.code };
          return m;
        }) } : current);
        setStatus(event.name === "answer.delta" ? "正在接收已验证回答…" : event.name === "message.error" ? "生成失败；请刷新服务器记录后决定是否发送新问题。" : "回答已完成。");
      }
    };
    try { await api.send(id, content, receive, abort.signal); }
    catch (e) {
      if (!(e instanceof ApiError)) {
        setInterrupted(true); setStatus("连接中断，尚未确认最终结果。请显式刷新会话，勿自动重发。");
        setConversation(current => current ? { ...current, messages: current.messages.map(m => m.id === assistantId ? { ...m, state: "processing", citations: [] } : m) } : current);
      } else if (e.status === 409) { setInterrupted(true); setStatus("会话状态已变化，请刷新服务器记录。"); }
      setError(e instanceof Error ? e.message : "请求失败。");
    } finally { locked.current = false; setSending(false); controller.current = null; input.current?.focus(); }
  }
  return <main className="page-shell agent-page"><AgentNavigation />
    <h1 ref={heading} tabIndex={-1}>{auditAgent ? "会话审计" : "智能体会话"}{conversation ? ` · ${conversation.agent_name}` : ""}</h1>
    <Link to={auditAgent ? `/agents/${encodeURIComponent(auditAgent)}/audit` : "/conversations"}>返回会话列表</Link>
    <p role="status" aria-label="会话状态" aria-live="polite" aria-atomic="true">{status}</p>
    {error && <p className="error" role="alert">{error}</p>}
    <button disabled={sending || busy} onClick={() => void load()}>刷新服务器记录（不会重发）</button>
    {conversation && <>
      <p>学生：{conversation.student_account} · {conversation.deleted_at ? "学生已删除（保留审计）" : "未删除"}</p>
      {!auditAgent && <p>{retention}</p>}
      {!auditAgent && !available && !busy && <p className="degraded-notice">智能体暂不可用：已取消发布、停用或配置无效。历史仍可阅读，不能发送新消息。</p>}
      <MessageHistory messages={conversation.messages} onDownload={source => void download(source)} />
      {conversation.next_after_ordinal !== null && <button disabled={busy || sending} onClick={() => void more()}>加载更多历史</button>}
      {!auditAgent && <form className="agent-form library-panel" onSubmit={submit} aria-label="发送消息">
        <label>当前问题<textarea ref={input} required rows={4} maxLength={20000} value={question} onChange={e => setQuestion(e.target.value)} aria-describedby="message-help" /></label>
        <p id="message-help">每轮重新检索本班资料；同一会话一次只能发送一条消息。中断后先刷新，服务器可能已完成处理。{conversation.next_after_ordinal !== null ? "请先加载全部历史再发送。" : ""}</p>
        <button type="submit" disabled={sending || busy || !available || processing || interrupted || conversation.next_after_ordinal !== null}>{sending ? "回答中…" : "发送消息"}</button>
      </form>}
    </>}
  </main>;
}
