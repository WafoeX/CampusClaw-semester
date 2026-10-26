import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { ids, skill } from "./test/chat-fixtures";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const server = {
  id: ids.material, name: "campus-tools", base_url: "http://mcp-demo:8090", state: "disconnected",
  connection_generation: 0, safe_error_code: null, tool_count: 0,
  created_at: "2026-10-20T00:00:00Z", updated_at: "2026-10-20T00:00:00Z",
};
const tool = { name: "formula_hint", tool_ref: "formula_hint@campus-tools", description: "欧姆定律提示 <script>not executed</script>", input_schema: { type: "object" }, supported: true, code: null };
type Handler = (path: string, init?: RequestInit) => Response | undefined;
function mount(role: "teacher" | "student", handler: Handler = () => undefined, initialPath = "/mcp") {
  const calls: { path: string; init?: RequestInit }[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = String(input); calls.push({ path, init });
    if (path === "/api/auth/me") return json({ user_id: ids.user, account: "fixture", class_id: ids.material, role });
    const result = handler(path, init); if (result) return result;
    if (path.startsWith("/api/mcp/servers?")) return json({ items: [server], next_cursor: null });
    if (path === "/api/materials" || path === "/api/agents") return json([]);
    if (path === "/api/skills") return json([skill]);
    throw new Error(`Unexpected route ${path}`);
  });
  render(<MemoryRouter initialEntries={[initialPath]}><App /></MemoryRouter>);
  return { calls, user: userEvent.setup() };
}
beforeEach(() => window.localStorage.setItem("campusclaw.access-token", "fixture-jwt"));
afterEach(() => { window.localStorage.clear(); vi.restoreAllMocks(); });

describe("class-shared MCP management", () => {
  it("registers, connects, discovers and disconnects through the authenticated API without a credential field", async () => {
    let connected = false;
    const { calls, user } = mount("teacher", (path, init) => {
      if (path === "/api/mcp/servers" && init?.method === "POST") return json(server, 201);
      if (path.endsWith("/connect")) { connected = true; return json({ ...server, state: "connected", tool_count: 1, connection_generation: 1 }); }
      if (path.endsWith("/disconnect")) { connected = false; return json({ ...server, connection_generation: 2 }); }
      if (path.endsWith("/tools")) return json(connected ? [tool] : []);
    });
    await screen.findByText("本班共享服务器已加载。");
    expect(screen.getByRole("link", { name: "本班 MCP" })).toHaveAttribute("href", "/mcp");
    expect(screen.queryByLabelText(/token|令牌|密码|凭证/i)).not.toBeInTheDocument();
    await user.click(screen.getByLabelText("服务器名称"));
    await user.keyboard("campus-tools{Tab}{Tab}{Enter}");
    await screen.findByText("服务器已登记，请连接以发现工具。");
    const register = calls.find(c => c.path === "/api/mcp/servers" && c.init?.method === "POST")!;
    expect(JSON.parse(String(register.init?.body))).toEqual({ name: "campus-tools", base_url: "http://mcp-demo:8090" });
    expect(new Headers(register.init?.headers).get("authorization")).toBe("Bearer fixture-jwt");
    await user.click(screen.getByRole("button", { name: "连接 campus-tools" }));
    await screen.findByText("formula_hint@campus-tools");
    expect(screen.getByText(/状态：已连接/)).toBeInTheDocument();
    expect(document.querySelector("script")).toBeNull();
    expect(screen.getByText(tool.description)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "断开 campus-tools" }));
    await screen.findByText("已断开，旧工具绑定的后续调用将被拒绝。");
    expect(screen.queryByText("formula_hint@campus-tools")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "发现工具 campus-tools" }));
    await screen.findByText("当前无已发现工具；请先连接。");
    expect(calls.filter(c => c.path.endsWith("/connect"))).toHaveLength(1);
    expect(calls.filter(c => c.path.endsWith("/disconnect"))).toHaveLength(1);
    expect(calls.every(c => !String(c.init?.body).includes("fixture-jwt"))).toBe(true);
  });
  it("shows actionable fixed errors, clears stale discovery and does not retry a failed connect", async () => {
    const { calls, user } = mount("teacher", path => {
      if (path.endsWith("/tools")) return json([tool]);
      if (path.endsWith("/connect")) return json({ detail: { code: "remote_unauthorized", message: "PRIVATE_REMOTE_TOKEN" } }, 503);
    });
    await screen.findByText("本班共享服务器已加载。");
    await user.click(screen.getByRole("button", { name: "发现工具 campus-tools" }));
    await screen.findByText("formula_hint@campus-tools");
    await user.click(screen.getByRole("button", { name: "连接 campus-tools" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("远端认证失败，请联系部署者检查 MCP 凭证");
    expect(screen.queryByText("formula_hint@campus-tools")).not.toBeInTheDocument();
    expect(screen.queryByText("PRIVATE_REMOTE_TOKEN")).not.toBeInTheDocument();
    expect(calls.filter(c => c.path.endsWith("/connect"))).toHaveLength(1);
  });
  it("paginates server listings with the returned cursor", async () => {
    const { calls, user } = mount("teacher", path => {
      if (path === "/api/mcp/servers?limit=100") return json({ items: [server], next_cursor: "opaque+cursor=" });
      if (path.includes("cursor=")) return json({ items: [{ ...server, id: ids.agent, name: "other-tools" }], next_cursor: null });
    });
    await user.click(await screen.findByRole("button", { name: "加载更多服务器" }));
    await screen.findByRole("heading", { name: "other-tools" });
    expect(calls.some(c => c.path.endsWith("cursor=opaque%2Bcursor%3D"))).toBe(true);
    expect(screen.queryByRole("button", { name: "加载更多服务器" })).not.toBeInTheDocument();
  });
  it("keeps students out of management without requesting MCP endpoints", async () => {
    const { calls } = mount("student");
    await screen.findByRole("heading", { name: "Materials" });
    await waitFor(() => expect(screen.queryByRole("link", { name: "本班 MCP" })).not.toBeInTheDocument());
    expect(calls.some(c => c.path.startsWith("/api/mcp"))).toBe(false);
  });
});

describe("skill tool selections", () => {
  it("selects only supported discovered tools and sends explicit tools without a credential", async () => {
    const { calls, user } = mount("teacher", (path, init) => {
      if (path.startsWith("/api/mcp/servers?")) return json({ items: [{ ...server, state: "connected" }], next_cursor: null });
      if (path.endsWith("/tools")) return json([tool, { ...tool, name: "unsupported", tool_ref: "unsupported@campus-tools", supported: false }]);
      if (path === "/api/skills" && init?.method === "POST") return json(skill, 201);
    }, "/agents/manage");
    await screen.findByText("配置已加载，仅显示您创建的资源。");
    expect(screen.queryByLabelText("unsupported@campus-tools")).not.toBeInTheDocument();
    await user.click(screen.getByLabelText("formula_hint@campus-tools"));
    await user.type(screen.getByLabelText("技能名称"), "公式引导");
    await user.type(screen.getByLabelText("技能指令"), "检查公式条件");
    await user.click(screen.getByRole("button", { name: "保存技能" }));
    await screen.findByText("技能已保存，请检查绑定智能体的发布状态。");
    const payload = JSON.parse(String(calls.find(c => c.path === "/api/skills" && c.init?.method === "POST")?.init?.body));
    expect(payload.tools).toEqual(["knowledge_search", "formula_hint@campus-tools"]);
    expect(Object.keys(payload)).toEqual(["name", "skill_type", "instructions", "tools"]);
  });
  it("retains unavailable bindings across 409 and sends [] only after explicit removal", async () => {
    const old = { ...skill, tools: ["formula_hint@campus-tools"] };
    let reject = true;
    const { calls, user } = mount("teacher", (path, init) => {
      if (path === "/api/skills") return json([old]);
      if (path === `/api/skills/${ids.skill}` && init?.method === "PATCH") return reject
        ? json({ detail: { code: "server_disconnected", message: "PRIVATE" } }, 409) : json({ ...old, tools: [] });
    }, "/agents/manage");
    await user.click(await screen.findByRole("button", { name: `编辑技能 ${skill.name}` }));
    const checkbox = screen.getByLabelText(/formula_hint@campus-tools（不可用/);
    expect(checkbox).toBeChecked();
    await user.click(screen.getByRole("button", { name: "保存技能" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("工具服务器已断开");
    expect(checkbox).toBeChecked();
    expect(screen.getByLabelText("技能名称")).toHaveValue(old.name);
    expect(JSON.parse(String(calls.find(c => c.init?.method === "PATCH")?.init?.body)).tools).toEqual(old.tools);
    reject = false;
    await user.click(checkbox);
    await user.click(screen.getByRole("button", { name: "保存技能" }));
    await screen.findByText("技能已保存，请检查绑定智能体的发布状态。");
    expect(JSON.parse(String(calls.filter(c => c.init?.method === "PATCH").at(-1)?.init?.body)).tools).toEqual([]);
  });
});
