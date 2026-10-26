import { type FormEvent, useCallback, useEffect, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { useAuth } from "./auth";
import { AgentNavigation } from "./agents";
import { type McpServer, type McpTool } from "./agent-api";
import { useAgentApi } from "./use-agent-api";

const states = { disconnected: "已断开", connecting: "连接中", connected: "已连接", error: "连接失败" };

export function McpManagement() {
  const { identity } = useAuth();
  return identity?.role === "teacher" ? <TeacherMcp /> : <Navigate to="/materials" replace />;
}

function TeacherMcp() {
  const api = useAgentApi();
  const [servers, setServers] = useState<McpServer[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [tools, setTools] = useState<Record<string, McpTool[]>>({});
  const [name, setName] = useState("");
  const [url, setUrl] = useState("http://mcp-demo:8090");
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("正在加载本班 MCP…");
  const load = useCallback(async () => {
    const page = await api.mcpServers();
    setServers(page.items); setCursor(page.next_cursor); setTools({});
  }, [api]);
  useEffect(() => {
    let active = true;
    void load().then(() => { if (active) setStatus("本班共享服务器已加载。"); })
      .catch(() => { if (active) setError("无法加载本班 MCP，请刷新重试。"); })
      .finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [load]);
  async function operation(work: () => Promise<unknown>, success: string) {
    if (busy) return;
    setBusy(true); setError("");
    try { await work(); setStatus(success); }
    catch (e) { setError(e instanceof Error ? e.message : "MCP 操作失败。"); }
    finally { setBusy(false); }
  }
  async function register(event: FormEvent) {
    event.preventDefault();
    await operation(async () => {
      await api.registerMcp({ name: name.trim(), base_url: url.trim() });
      setName(""); await load();
    }, "服务器已登记，请连接以发现工具。");
  }
  async function connection(server: McpServer, connect: boolean) {
    // Clear stale discovery before attempting a new generation, including failures.
    setTools(current => { const next = { ...current }; delete next[server.id]; return next; });
    await operation(async () => {
      try {
        const updated = await (connect ? api.connectMcp(server.id) : api.disconnectMcp(server.id));
        setServers(current => current.map(item => item.id === server.id ? updated : item));
        if (connect) {
          const discovered = await api.mcpTools(server.id);
          setTools(current => ({ ...current, [server.id]: discovered }));
        }
      } catch (e) {
        // A failed connect invalidates the old cache on the server as well.
        await load(); throw e;
      }
    }, connect ? "连接及工具发现已完成。" : "已断开，旧工具绑定的后续调用将被拒绝。");
  }
  return <main className="page-shell agent-page">
    <AgentNavigation /><h1>本班 MCP</h1><Link to="/mcp/audits">本班工具审计</Link>
    <p>本班教师共享服务器管理权限；技能和智能体仍仅创建者可修改。仅支持部署者批准的内部 URL。</p>
    <p>凭证由部署者在服务端配置，浏览器无需填写。名称和 URL 登记后不可修改。</p>
    <p role="status" aria-live="polite">{busy ? "正在处理…" : status}</p>
    {error && <p className="error" role="alert">{error}</p>}
    <form className="agent-form library-panel" aria-label="登记 MCP 服务器" onSubmit={register}>
      <label>服务器名称<input required pattern="[a-z][a-z0-9-]{0,62}" maxLength={63} value={name} onChange={e => setName(e.target.value)} /></label>
      <label>Base URL<input required type="url" maxLength={2048} value={url} onChange={e => setUrl(e.target.value)} /></label>
      <button disabled={busy} type="submit">登记服务器</button>
    </form>
    <section className="library-panel" aria-label="本班 MCP 服务器">
      <h2>服务器列表</h2>
      <button disabled={busy} onClick={() => void operation(load, "服务器状态已刷新。")}>刷新服务器</button>
      {!servers.length && !busy && <p>尚未登记服务器。</p>}
      <ul className="agent-list">{servers.map(server => <li key={server.id}>
        <h3>{server.name}</h3><p>{server.base_url}</p>
        <p>状态：{states[server.state]} · 工具数：{server.tool_count}</p>
        {server.safe_error_code && <p>安全错误码：{server.safe_error_code}；请检查服务后重新连接。</p>}
        <div className="agent-actions">
          <button disabled={busy} onClick={() => void connection(server, true)}>连接 {server.name}</button>
          <button disabled={busy} onClick={() => void connection(server, false)}>断开 {server.name}</button>
          <button disabled={busy} onClick={() => void operation(async () => {
            const discovered = await api.mcpTools(server.id);
            setTools(current => ({ ...current, [server.id]: discovered }));
          }, "工具列表已刷新。")}>发现工具 {server.name}</button>
        </div>
        {Object.hasOwn(tools, server.id) && <div>
          {!tools[server.id].length && <p>当前无已发现工具；请先连接。</p>}
          <ul>{tools[server.id].map(tool => <li key={tool.name}>
            <strong>{tool.tool_ref}</strong> · {tool.supported ? "可绑定" : "参数不兼容，无法绑定"}
            <p className="plain-text">{tool.description}</p>
          </li>)}</ul>
        </div>}
      </li>)}</ul>
      {cursor && <button disabled={busy} onClick={() => void operation(async () => {
        const page = await api.mcpServers(cursor);
        setServers(current => [...current.filter(item => !page.items.some(next => next.id === item.id)), ...page.items]);
        setCursor(page.next_cursor);
      }, "已加载更多服务器。")}>加载更多服务器</button>}
    </section>
  </main>;
}
