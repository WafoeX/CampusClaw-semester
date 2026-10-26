import { useCallback, useEffect, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { useAuth } from "./auth";
import { AgentNavigation } from "./agents";
import { type McpAudit } from "./agent-api";
import { useAgentApi } from "./use-agent-api";

export function McpAudits() {
  const { identity } = useAuth();
  return identity?.role === "teacher" ? <TeacherAudits /> : <Navigate to="/materials" replace />;
}

function TeacherAudits() {
  const api = useAgentApi();
  const [rows, setRows] = useState<McpAudit[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const load = useCallback(async (after?: string) => {
    const page = await api.mcpAudits(after);
    setRows(current => after ? [...current.filter(row => !page.items.some(next => next.id === row.id)), ...page.items] : page.items);
    setCursor(page.next_cursor);
  }, [api]);
  useEffect(() => {
    let active = true;
    void load().catch(() => { if (active) setError("无法加载本班工具审计，请刷新重试。"); })
      .finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [load]);
  async function refresh(after?: string) {
    if (busy) return;
    setBusy(true); setError("");
    try { await load(after); }
    catch (e) { setError(e instanceof Error ? e.message : "无法读取工具审计。"); }
    finally { setBusy(false); }
  }
  return <main className="page-shell agent-page">
    <AgentNavigation /><h1>本班工具审计</h1><Link to="/mcp">返回 MCP 管理</Link>
    <p>本班教师共享最小工具审计；不包含问题、参数、工具正文或凭证，不授予会话内容访问权。成功仅表示已授权工具执行成功。</p>
    <p role="status" aria-live="polite">{busy ? "正在加载工具审计…" : "工具审计已加载。"}</p>
    {error && <p role="alert" className="error">{error}</p>}
    <button disabled={busy} onClick={() => void refresh()}>刷新工具审计</button>
    {!busy && !rows.length && <p>暂无工具调用记录。</p>}
    <ul className="agent-list">{rows.map(row => <li className="library-panel" key={row.id}>
      <h2>{row.tool_ref}</h2>
      <p>状态：{row.status === "ok" ? "成功" : row.status === "denied" ? "已拒绝" : "执行错误"} · 安全原因：{row.code}</p>
      <p>发起用户：{row.user_id}</p><p>开始（UTC）：{row.created_at} · 完成（UTC）：{row.completed_at}</p>
      <p>会话标识：{row.conversation_id}</p><p>回合标识：{row.assistant_message_id}</p>
    </li>)}</ul>
    {cursor && <button disabled={busy} onClick={() => void refresh(cursor)}>加载更多工具审计</button>}
  </main>;
}
