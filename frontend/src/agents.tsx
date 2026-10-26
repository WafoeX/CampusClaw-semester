import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { useAuth } from "./auth";
import { type Agent, type AgentInput, type Skill, type SkillInput } from "./agent-api";
import { useAgentApi } from "./use-agent-api";

const blankAgent: AgentInput = { name: "", description: "", system_prompt: "", skill_ids: [] };
const blankSkill: SkillInput = { name: "", skill_type: "solution_guidance", instructions: "" };

export function AgentNavigation() {
  const { identity } = useAuth();
  return <nav className="agent-navigation" aria-label="班级功能">
    <Link to="/materials">资料与单轮问答</Link>
    {identity?.role === "teacher" ? <><Link to="/agents/manage">我的智能体与技能</Link><Link to="/mcp">本班 MCP</Link></> : <Link to="/conversations">智能体与会话</Link>}
  </nav>;
}

export function AgentManagement() {
  const { identity } = useAuth();
  return identity?.role === "teacher" ? <TeacherManagement /> : <Navigate to="/materials" replace />;
}

function TeacherManagement() {
  const api = useAgentApi();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [availableTools, setAvailableTools] = useState<string[]>([]);
  const [toolCursor, setToolCursor] = useState<string | null>(null);
  const [toolWarning, setToolWarning] = useState("");
  const [agentId, setAgentId] = useState<string>();
  const [skillId, setSkillId] = useState<string>();
  const [agent, setAgent] = useState<AgentInput>(blankAgent);
  const [skill, setSkill] = useState<SkillInput>(blankSkill);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("正在加载我的配置…");
  const [busy, setBusy] = useState(true);
  const agentName = useRef<HTMLInputElement>(null);
  const skillName = useRef<HTMLInputElement>(null);
  const loadTools = useCallback(async (cursor?: string) => {
    try {
      const page = await api.mcpServers(cursor);
      const lists = await Promise.all(page.items.filter(s => s.state === "connected").map(s => api.mcpTools(s.id)));
      const refs = lists.flat().filter(t => t.supported).map(t => t.tool_ref);
      setAvailableTools(current => [...new Set([...(cursor ? current : []), ...refs])].sort());
      setToolCursor(page.next_cursor); setToolWarning("");
    } catch {
      if (!cursor) setAvailableTools([]);
      setToolWarning("无法加载可用工具；旧绑定已保留，请刷新工具或前往本班 MCP 检查连接。");
    }
  }, [api]);
  const load = useCallback(async () => {
    const [a, s] = await Promise.all([api.agents(), api.skills()]);
    setAgents(a.filter(item => item.state !== "retired"));
    setSkills(s.filter(item => item.state === "active"));
    await loadTools();
  }, [api, loadTools]);
  useEffect(() => {
    let active = true;
    void load().then(() => { if (active) setStatus("配置已加载，仅显示您创建的资源。"); })
      .catch(() => { if (active) setError("无法加载配置，请刷新重试。"); })
      .finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [load]);
  async function operation(work: () => Promise<unknown>, success: string, reload = true) {
    if (busy) return;
    setBusy(true); setError("");
    try { await work(); if (reload) await load(); setStatus(success); }
    catch (e) { setError(e instanceof Error ? e.message : "操作失败。"); }
    finally { setBusy(false); }
  }
  async function saveAgent(event: FormEvent) {
    event.preventDefault();
    if (!agent.name.trim() || !agent.system_prompt.trim()) { setError("名称和提示词不能为空。"); return; }
    await operation(async () => { await api.saveAgent(agent, agentId); setAgentId(undefined); setAgent(blankAgent); }, "智能体已保存，请确认发布状态。");
  }
  async function saveSkill(event: FormEvent) {
    event.preventDefault();
    if (!skill.name.trim() || !skill.instructions.trim()) { setError("技能名称和指令不能为空。"); return; }
    await operation(async () => { await api.saveSkill(skill, skillId); setSkillId(undefined); setSkill(blankSkill); }, "技能已保存，请检查绑定智能体的发布状态。");
  }
  return <main className="page-shell agent-page">
    <AgentNavigation /><h1>我的智能体与技能</h1>
    <p>仅创建者可管理与审计自己的智能体。解题引导只提供提示、步骤、检查和追问，不直接给出最终答案。</p>
    <p role="status" aria-live="polite">{busy ? "正在处理…" : status}</p>
    {error && <p className="error" role="alert">{error}</p>}
    <div className="agent-workspace">
      <section className="library-panel" aria-labelledby="my-agents"><h2 id="my-agents">智能体列表</h2>
        {!agents.length && !busy && <p>还没有智能体，可以创建多个草稿。</p>}
        <ul className="agent-list">{agents.map(a => <li key={a.id}>
          <h3>{a.name}</h3><p>{a.description}</p><p>状态：{a.state === "published" ? "已发布" : "草稿"}</p>
          <div className="agent-actions">
            <button disabled={busy} onClick={() => { setAgentId(a.id); setAgent({ name: a.name, description: a.description, system_prompt: a.system_prompt, skill_ids: a.skill_ids }); agentName.current?.focus(); }}>编辑 {a.name}</button>
            <button disabled={busy} onClick={() => void operation(() => api.publication(a.id, a.state !== "published"), "发布状态已更新。")}>{a.state === "published" ? "取消发布" : "发布"} {a.name}</button>
            <Link to={`/agents/${encodeURIComponent(a.id)}/audit`}>审计 {a.name}</Link>
            <button disabled={busy} onClick={() => { if (window.confirm(`停用 ${a.name}？既有会话仍保留供审计。`)) void operation(async () => { await api.retireAgent(a.id); if (agentId === a.id) { setAgentId(undefined); setAgent(blankAgent); } }, "智能体已停用。"); }}>停用 {a.name}</button>
          </div>
        </li>)}</ul>
      </section>
      <form className="agent-form library-panel" onSubmit={saveAgent} aria-label="智能体配置">
        <h2>{agentId ? "编辑智能体" : "创建智能体"}</h2>
        <label>智能体名称<input ref={agentName} required maxLength={120} value={agent.name} onChange={e => setAgent({ ...agent, name: e.target.value })} /></label>
        <label>描述<textarea maxLength={1000} value={agent.description ?? ""} onChange={e => setAgent({ ...agent, description: e.target.value })} /></label>
        <label>教师提示词<textarea required maxLength={20000} rows={5} value={agent.system_prompt} onChange={e => setAgent({ ...agent, system_prompt: e.target.value })} /></label>
        <p>教师配置不能覆盖平台的班级隔离、证据、引用与安全规则。</p>
        <fieldset><legend>绑定我的有效技能（发布至少需要一个解题引导技能）</legend>
          {skills.map(s => <label className="checkbox-label" key={s.id}><input type="checkbox" checked={agent.skill_ids.includes(s.id)} onChange={e => setAgent({ ...agent, skill_ids: e.target.checked ? [...agent.skill_ids, s.id] : agent.skill_ids.filter(id => id !== s.id) })} />{s.name}</label>)}
          {agent.skill_ids.filter(id => !skills.some(s => s.id === id)).map(id => <div key={id}>
            <p>此绑定技能已停用或不可用：{id}</p>
            <button type="button" disabled={busy} onClick={() => setAgent({ ...agent, skill_ids: agent.skill_ids.filter(item => item !== id) })}>移除不可用技能 {id}</button>
          </div>)}
          {!skills.length && <p>请先创建解题引导技能。</p>}
        </fieldset>
        <button type="submit" disabled={busy}>保存智能体</button>
        <button type="button" disabled={busy} onClick={() => { setAgentId(undefined); setAgent(blankAgent); agentName.current?.focus(); }}>新建智能体</button>
      </form>
      <section className="library-panel" aria-labelledby="my-skills"><h2 id="my-skills">我的技能</h2>
        <ul className="agent-list">{skills.map(s => <li key={s.id}><h3>{s.name}</h3><p className="plain-text">{s.instructions}</p>
          <button disabled={busy} onClick={() => { setSkillId(s.id); setSkill({ name: s.name, skill_type: s.skill_type, instructions: s.instructions, tools: [...s.tools] }); skillName.current?.focus(); }}>编辑技能 {s.name}</button>
          <button disabled={busy} onClick={() => { if (window.confirm(`停用技能 ${s.name}？相关智能体可能无法继续使用。`)) void operation(async () => { await api.retireSkill(s.id); if (skillId === s.id) { setSkillId(undefined); setSkill(blankSkill); } setAgent(current => ({ ...current, skill_ids: current.skill_ids.filter(id => id !== s.id) })); }, "技能已停用，请修复相关智能体绑定并重新发布。"); }}>停用技能 {s.name}</button>
        </li>)}</ul>
      </section>
      <form className="agent-form library-panel" onSubmit={saveSkill} aria-label="技能配置">
        <h2>{skillId ? "编辑技能" : "创建技能"}</h2>
        <label>技能名称<input ref={skillName} required maxLength={120} value={skill.name} onChange={e => setSkill({ ...skill, name: e.target.value })} /></label>
        <label>技能类型<select value={skill.skill_type} onChange={() => undefined}><option value="solution_guidance">解题引导</option></select></label>
        <label>技能指令<textarea required maxLength={20000} rows={5} value={skill.instructions} onChange={e => setSkill({ ...skill, instructions: e.target.value })} /></label>
        <fieldset><legend>技能工具（最多 8 项；平台始终执行本班检索）</legend>
          <p>全部有效绑定每轮都会尝试调用，仅向工具发送当前问题前 2000 字符。工具结果不是事实证据，不会递归调用。</p>
          <p>formula_hint 仅支持有限公式提示；unit_convert 支持有限同维度单位的固定转换模板。</p>
          {toolWarning && <p role="alert">{toolWarning}</p>}
          <button type="button" disabled={busy} onClick={() => void operation(() => loadTools(), "工具列表已刷新。", false)}>刷新可选工具</button>
          {toolCursor && <button type="button" disabled={busy} onClick={() => void operation(() => loadTools(toolCursor), "已加载更多工具。", false)}>加载更多可选工具</button>}
          {["knowledge_search", ...availableTools, ...(skill.tools ?? []).filter(ref => ref !== "knowledge_search" && !availableTools.includes(ref))].map(ref => <label className="checkbox-label" key={ref}>
            <input type="checkbox" checked={(skill.tools ?? ["knowledge_search"]).includes(ref)} onChange={e => {
              const current = skill.tools ?? ["knowledge_search"];
              setSkill({ ...skill, tools: e.target.checked ? [...current, ref] : current.filter(item => item !== ref) });
            }} />{ref}{ref !== "knowledge_search" && !availableTools.includes(ref) ? "（不可用；保留绑定，保存时需重新连接发现或移除）" : ""}
          </label>)}
        </fieldset>
        <button type="submit" disabled={busy}>保存技能</button>
        <button type="button" disabled={busy} onClick={() => { setSkillId(undefined); setSkill(blankSkill); skillName.current?.focus(); }}>新建技能</button>
      </form>
    </div>
  </main>;
}
