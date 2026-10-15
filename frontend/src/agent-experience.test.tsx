import { webcrypto } from "node:crypto";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { agent, answer, conversation, events, frames, historical, ids, skill, stream } from "./test/chat-fixtures";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
type Handler = (path: string, init?: RequestInit) => Response | Promise<Response> | undefined;
function mount(path: string, role: "teacher" | "student", handler: Handler = () => undefined) {
  const calls: { path: string; init?: RequestInit }[] = [];
  const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input); const pathname = url.split("?")[0];
    calls.push({ path: url, init });
    if (url === "/api/auth/me") return json({ user_id: ids.user, account: `${role}.fixture`, class_id: ids.material, role });
    const override = handler(url, init);
    if (override) return override;
    if (pathname === "/api/agents") return json(role === "teacher" ? [agent] : [{ id: agent.id, name: agent.name, description: agent.description }]);
    if (pathname === "/api/skills") return json([skill]);
    if (pathname === "/api/conversations") return json([conversation]);
    if (pathname === `/api/conversations/${ids.conversation}`) return json(conversation);
    if (pathname === "/api/materials") return json([]);
    throw new Error(`Unexpected fixture route ${url}`);
  });
  render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>);
  return { fetcher, calls, user: userEvent.setup() };
}
beforeEach(() => { window.localStorage.setItem("campusclaw.access-token", "fixture-token"); vi.stubGlobal("crypto", webcrypto); });
afterEach(() => { window.localStorage.clear(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("creator-only teacher management", () => {
  it("shows multiple owned agents, edits private prompt and bindings via keyboard", async () => {
    const second = { ...agent, id: ids.material, name: "第二导师" };
    const { user, calls } = mount("/agents/manage", "teacher", (path, init) => {
      if (path === "/api/agents" && init?.method === "GET") return json([agent, second]);
      if (init?.method === "PATCH") return json(agent);
    });
    expect(await screen.findByRole("heading", { name: "第二导师" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: `编辑 ${agent.name}` }));
    expect(screen.getByLabelText("智能体名称")).toHaveFocus();
    expect(screen.getByLabelText("教师提示词")).toHaveValue(agent.system_prompt);
    await user.click(screen.getByLabelText(skill.name));
    await user.click(screen.getByLabelText("教师提示词"));
    await user.keyboard("{Control>}a{/Control}新的私有提示");
    await user.click(screen.getByRole("button", { name: "保存智能体" }));
    await screen.findByText("智能体已保存，请确认发布状态。");
    const request = calls.find(c => c.init?.method === "PATCH")!;
    expect(JSON.parse(String(request.init?.body))).toMatchObject({ skill_ids: [], system_prompt: "新的私有提示" });
    expect(screen.getByRole("link", { name: `审计 ${agent.name}` })).toHaveAttribute("href", `/agents/${agent.id}/audit`);
  });
  it("validates whitespace, input bounds and exposes publication readiness errors safely", async () => {
    const { user, calls } = mount("/agents/manage", "teacher", (path, init) => {
      if (path.endsWith("/unpublish") && init?.method === "POST") return json({ detail: { code: "agent_not_ready", message: "hidden provider" } }, 409);
    });
    await screen.findByRole("button", { name: `取消发布 ${agent.name}` });
    expect(screen.getByLabelText("教师提示词")).toHaveAttribute("maxlength", "20000");
    await user.type(screen.getByLabelText("智能体名称"), "   "); await user.type(screen.getByLabelText("教师提示词"), "   ");
    await user.click(screen.getByRole("button", { name: "保存智能体" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("名称和提示词不能为空");
    expect(calls.filter(c => c.init?.method === "POST")).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: `取消发布 ${agent.name}` }));
    expect(await screen.findByRole("alert")).toHaveTextContent("绑定有效的解题引导技能");
    expect(screen.queryByText("hidden provider")).not.toBeInTheDocument();
  });
  it("creates skills, binds compatible selections and confirms retirement", async () => {
    const { user, calls } = mount("/agents/manage", "teacher", (path, init) => {
      if (path === "/api/skills" && init?.method === "POST") return json(skill, 201);
      if (path === "/api/agents" && init?.method === "POST") return json(agent, 201);
      if (init?.method === "DELETE") return json({ ...skill, state: "retired" });
    });
    await screen.findByText("配置已加载，仅显示您创建的资源。");
    await user.type(screen.getByLabelText("技能名称"), "新技能");
    await user.type(screen.getByLabelText("技能指令"), "提示与追问");
    await user.click(screen.getByRole("button", { name: "保存技能" }));
    await screen.findByText("技能已保存，请检查绑定智能体的发布状态。");
    expect(JSON.parse(String(calls.find(c => c.path === "/api/skills" && c.init?.method === "POST")?.init?.body))).toEqual({ name: "新技能", skill_type: "solution_guidance", instructions: "提示与追问" });
    await user.type(screen.getByLabelText("智能体名称"), "新导师"); await user.type(screen.getByLabelText("教师提示词"), "引导学习");
    await user.click(screen.getByLabelText(skill.name)); await user.click(screen.getByRole("button", { name: "保存智能体" }));
    await screen.findByText("智能体已保存，请确认发布状态。");
    expect(JSON.parse(String(calls.find(c => c.path === "/api/agents" && c.init?.method === "POST")?.init?.body))).toMatchObject({ skill_ids: [ids.skill] });
    vi.spyOn(window, "confirm").mockReturnValue(false);
    await user.click(screen.getByRole("button", { name: `停用技能 ${skill.name}` }));
    expect(calls.some(c => c.init?.method === "DELETE")).toBe(false);
    vi.mocked(window.confirm).mockReturnValue(true);
    await user.click(screen.getByRole("button", { name: `停用技能 ${skill.name}` }));
    await screen.findByText("技能已停用，请修复相关智能体绑定并重新发布。");
    expect(calls.some(c => c.path === `/api/skills/${ids.skill}` && c.init?.method === "DELETE")).toBe(true);
  });
  it("lets the creator remove a retired binding before repairing publication", async () => {
    const { user, calls } = mount("/agents/manage", "teacher", (path, init) => {
      if (path === "/api/skills") return json([]);
      if (path === `/api/agents/${ids.agent}` && init?.method === "PATCH") return json({ ...agent, skill_ids: [] });
    });
    await user.click(await screen.findByRole("button", { name: `编辑 ${agent.name}` }));
    await user.click(screen.getByRole("button", { name: `移除不可用技能 ${ids.skill}` }));
    await user.click(screen.getByRole("button", { name: "保存智能体" }));
    await screen.findByText("智能体已保存，请确认发布状态。");
    expect(JSON.parse(String(calls.find(c => c.init?.method === "PATCH")?.init?.body))).toMatchObject({ skill_ids: [] });
  });
  it("redirects students away without requesting private configuration", async () => {
    const { calls } = mount("/agents/manage", "student");
    await screen.findByRole("heading", { name: "Materials" });
    expect(calls.some(c => c.path.includes("agents") || c.path.includes("skills"))).toBe(false);
    expect(screen.queryByText(agent.system_prompt)).not.toBeInTheDocument();
  });
});

describe("student catalog and deletion", () => {
  it("uses only safe catalog fields and active conversations; creates from an authorized choice", async () => {
    const { user, calls } = mount("/conversations", "student", (path, init) => {
      if (path === "/api/conversations" && init?.method === "GET") return json([conversation, { ...conversation, id: ids.material, agent_name: "已删除的会话", deleted_at: conversation.created_at }]);
      if (path === "/api/conversations" && init?.method === "POST") return json(conversation, 201);
    });
    await screen.findByRole("heading", { name: agent.name });
    expect(screen.queryByText(agent.system_prompt)).not.toBeInTheDocument();
    expect(screen.queryByText("已删除的会话")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: `与 ${agent.name} 创建会话` }));
    await screen.findByRole("heading", { name: `智能体会话 · ${agent.name}` });
    expect(JSON.parse(String(calls.find(c => c.path === "/api/conversations" && c.init?.method === "POST")?.init?.body))).toEqual({ agent_id: ids.agent });
    expect(calls.some(c => c.path.includes("skills"))).toBe(false);
  });
  it("discloses retained teacher audit access, confirms deletion and restores focus", async () => {
    const { user, calls } = mount("/conversations", "student", (path, init) => {
      if (path === `/api/conversations/${ids.conversation}` && init?.method === "DELETE") return json({ ...conversation, deleted_at: conversation.created_at });
    });
    await user.click(await screen.findByRole("button", { name: `删除 ${agent.name} 的会话` }));
    expect(screen.getByRole("button", { name: "取消删除" })).toHaveFocus();
    expect(screen.getByRole("region", { name: "确认删除会话？" })).toHaveTextContent("教师仍可审计您的身份、问题、回答和引用");
    await user.keyboard("{Tab}{Enter}");
    await waitFor(() => expect(screen.queryByRole("region", { name: "确认删除会话？" })).not.toBeInTheDocument());
    expect(screen.getByRole("heading", { name: "智能体与会话" })).toHaveFocus();
    expect(screen.queryByRole("button", { name: `删除 ${agent.name} 的会话` })).not.toBeInTheDocument();
    expect(calls.filter(c => c.init?.method === "DELETE")).toHaveLength(1);
  });
  it("shows an empty current-class catalog without offering private or draft agents", async () => {
    mount("/conversations", "student", path => path === "/api/agents" ? json([]) : undefined);
    expect(await screen.findByText("暂无可用智能体，请联系教师。")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /创建会话/ })).not.toBeInTheDocument();
    expect(screen.queryByText(agent.system_prompt)).not.toBeInTheDocument();
  });
  it("handles unavailable catalogs and publication conflicts without exposing prompts", async () => {
    const { user } = mount("/conversations", "student", (path, init) => {
      if (path === "/api/conversations" && init?.method === "POST") return json({ detail: { code: "agent_not_ready" } }, 409);
    });
    await user.click(await screen.findByRole("button", { name: `与 ${agent.name} 创建会话` }));
    expect(await screen.findByRole("alert")).toHaveTextContent("智能体尚未就绪");
  });
});

describe("accessible grounded chat", () => {
  it("assembles each delta once, links current citations, focuses sources, downloads with Bearer and returns input focus", async () => {
    vi.stubGlobal("URL", class extends URL { static createObjectURL = vi.fn(() => "blob:fixture"); static revokeObjectURL = vi.fn(); });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    const { user, calls } = mount(`/conversations/${ids.conversation}`, "student", (path, init) => {
      if (path.endsWith("/messages")) return new Response(stream(), { headers: { "content-type": "text/event-stream" } });
      if (path === `/api/materials/${ids.material}/download` && init?.method === "GET") return new Response("fixture");
    });
    await screen.findByRole("heading", { name: `智能体会话 · ${agent.name}` });
    await user.type(screen.getByLabelText("当前问题"), "解释条件");
    await user.click(screen.getByRole("button", { name: "发送消息" }));
    await screen.findByText("回答已完成。");
    const assistant = screen.getByRole("article", { name: "智能体消息 2" });
    expect(assistant).toHaveTextContent(answer);
    expect(assistant.querySelectorAll("img,script")).toHaveLength(0);
    expect(within(assistant).getByText("智能体配置已更新，本轮使用新配置。")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveAttribute("aria-live", "polite");
    expect(screen.getByLabelText("当前问题")).toHaveFocus();
    await user.click(within(assistant).getByRole("link", { name: "[S1]" }));
    expect(screen.getByRole("heading", { name: "S1 · 课程笔记" }).parentElement).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "下载授权资料 S1" }));
    await waitFor(() => expect(calls.some(c => c.path.endsWith("/download"))).toBe(true));
    expect(new Headers(calls.find(c => c.path.endsWith("/download"))?.init?.headers).get("authorization")).toBe("Bearer fixture-token");
    expect(calls.filter(c => c.path.endsWith("/messages"))).toHaveLength(1);
  });
  it("allows one in-flight turn, does not retry on interruption, and explicitly refreshes authoritative state", async () => {
    let controller: ReadableStreamDefaultController<Uint8Array>;
    let refreshed = false;
    const { user, calls } = mount(`/conversations/${ids.conversation}`, "student", (path, init) => {
      if (path.endsWith("/messages")) return new Response(new ReadableStream({ start(c) { controller = c; c.enqueue(new TextEncoder().encode(frames(events().slice(0, 2)))); } }), { headers: { "content-type": "text/event-stream" } });
      if (path.startsWith(`/api/conversations/${ids.conversation}?`) && init?.method === "GET" && refreshed) return json({ ...conversation, messages: [historical] });
    });
    await screen.findByText("已刷新服务器记录。");
    await user.type(screen.getByLabelText("当前问题"), "问题"); await user.click(screen.getByRole("button", { name: "发送消息" }));
    expect(await screen.findByRole("button", { name: "回答中…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "刷新服务器记录（不会重发）" })).toBeDisabled();
    controller!.close();
    expect(await screen.findByRole("alert")).toHaveTextContent("连接中断");
    expect(screen.getByRole("button", { name: "发送消息" })).toBeDisabled();
    expect(screen.queryByRole("link", { name: "[S1]" })).not.toBeInTheDocument();
    refreshed = true;
    await user.click(screen.getByRole("button", { name: "刷新服务器记录（不会重发）" }));
    await screen.findByRole("link", { name: "[S1]" });
    expect(screen.getByRole("button", { name: "发送消息" })).toBeEnabled();
    expect(calls.filter(c => c.path.endsWith("/messages"))).toHaveLength(1);
  });
  it("blocks unavailable agents but retains plain-text history", async () => {
    mount(`/conversations/${ids.conversation}`, "student", path => {
      if (path === "/api/agents") return json([]);
      if (path.startsWith(`/api/conversations/${ids.conversation}?`)) return json({ ...conversation, messages: [{ ...historical, content: "旧引用 [S9] <script>bad()</script>", citations: [] }] });
    });
    expect(await screen.findByText(/智能体暂不可用/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "发送消息" })).toBeDisabled();
    expect(screen.queryByRole("link", { name: "[S9]" })).not.toBeInTheDocument();
    expect(screen.getByRole("article", { name: "智能体消息 2" })).toHaveTextContent("旧引用 [S9] <script>bad()</script>");
  });
  it("shows a safe post-start error without fabricated text", async () => {
    const start = events()[0];
    const { user } = mount(`/conversations/${ids.conversation}`, "student", path => {
      if (path.endsWith("/messages")) return new Response(stream(frames([start, { name: "message.error", data: { conversation_id: ids.conversation, user_message_id: ids.user, assistant_message_id: ids.assistant, sequence: 2, code: "generation_failed", retryable: true } }])), { headers: { "content-type": "text/event-stream" } });
    });
    await screen.findByText("已刷新服务器记录。"); await user.type(screen.getByLabelText("当前问题"), "问题"); await user.click(screen.getByRole("button", { name: "发送消息" }));
    expect(await screen.findByText(/本轮生成失败，未提供回答/)).toBeInTheDocument();
    expect(screen.queryByText(answer)).not.toBeInTheDocument();
  });
});

describe("creator audit and existing routes", () => {
  it("lists both active and deleted conversations, filters and reads complete paginated audit without a send form", async () => {
    const { user, calls } = mount(`/agents/${ids.agent}/audit`, "teacher", path => {
      if (path === `/api/agents/${ids.agent}/conversations`) return json([conversation, { ...conversation, id: ids.material, deleted_at: conversation.created_at }]);
      if (path.endsWith("?deleted=true")) return json([{ ...conversation, deleted_at: conversation.created_at }]);
      if (path.includes(`/conversations/${ids.conversation}?`)) return json({ ...conversation, deleted_at: conversation.created_at, messages: path.includes("after_ordinal=2") ? [{ ...historical, id: ids.material, ordinal: 4, content: "下一页完整审计" }] : [historical], next_after_ordinal: path.includes("after_ordinal=2") ? null : 2 });
    });
    expect(await screen.findByText("学生已删除（保留审计）")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("审计状态"), "true");
    await waitFor(() => expect(screen.getAllByRole("link", { name: /student.fixture/ })).toHaveLength(1));
    await user.click(screen.getByRole("link", { name: /student.fixture/ }));
    await screen.findByRole("heading", { name: `会话审计 · ${agent.name}` });
    expect(screen.queryByRole("form", { name: "发送消息" })).not.toBeInTheDocument();
    expect(screen.getByRole("article", { name: "智能体消息 2" })).toHaveTextContent(answer);
    await user.click(screen.getByRole("button", { name: "加载更多历史" }));
    expect(await screen.findByText("下一页完整审计")).toBeInTheDocument();
    expect(calls.some(c => c.path.includes("after_ordinal=2&limit=100"))).toBe(true);
  });
  it("exposes no audit content or links on same-class non-creator 404", async () => {
    mount(`/agents/${ids.agent}/audit`, "teacher", path => path.includes("/conversations") ? json({ detail: { code: "conversation_not_found" } }, 404) : undefined);
    expect(await screen.findByRole("alert")).toHaveTextContent("资源不存在或无权访问");
    expect(screen.queryByRole("link", { name: /student.fixture/ })).not.toBeInTheDocument();
    expect(screen.queryByText(answer)).not.toBeInTheDocument();
  });
  it("prevents students from requesting creator audit", async () => {
    const { calls } = mount(`/agents/${ids.agent}/audit`, "student");
    await screen.findByRole("heading", { name: "智能体与会话" });
    expect(calls.some(c => c.path.startsWith(`/api/agents/${ids.agent}/conversations`))).toBe(false);
  });
  it("keeps materials, upload and legacy knowledge alongside teacher navigation", async () => {
    const { user } = mount("/materials", "teacher");
    await screen.findByRole("heading", { name: "知识库问答" });
    expect(screen.getByRole("link", { name: "上传资料" })).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "我的智能体与技能" }));
    await screen.findByRole("heading", { name: "我的智能体与技能" });
    await user.click(screen.getByRole("link", { name: "资料与单轮问答" }));
    await screen.findByRole("heading", { name: "Teaching materials" });
  });
});
