import { webcrypto } from "node:crypto";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { InterruptedStream, parseChatStream, type ChatEvent, type ToolCall } from "./agent-api";
import { agent, conversation, events, frames, historical, ids, stream } from "./test/chat-fixtures";

const json = (body: unknown) => new Response(JSON.stringify(body), { headers: { "content-type": "application/json" } });
const calls: ToolCall[] = [
  { tool_ref: "formula_hint@campus-tools", status: "ok", code: "ok" },
  { tool_ref: "unit_convert@campus-tools", status: "denied", code: "server_disconnected" },
  { tool_ref: "tool0@campus-tools", status: "error", code: "tool_timeout" },
];
function terminal(failed: boolean): ChatEvent[] {
  const list = events();
  if (failed) return [list[0], { name: "message.error", data: {
    conversation_id: ids.conversation, user_message_id: ids.user, assistant_message_id: ids.assistant,
    sequence: 2, code: "generation_failed", retryable: true, meta: { tool_calls: calls },
  } }];
  const last = list.at(-1)!;
  if (last.name === "message.completed") last.data.meta = { tool_calls: calls };
  return list;
}
beforeEach(() => { window.localStorage.setItem("campusclaw.access-token", "fixture-jwt"); vi.stubGlobal("crypto", webcrypto); });
afterEach(() => { window.localStorage.clear(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("safe tool stream metadata", () => {
  it.each([false, true])("preserves all finalized statuses on terminal failed=%s", async failed => {
    const list = terminal(failed), receive = vi.fn();
    await parseChatStream(stream(frames(list)), ids.conversation, receive);
    expect(receive).toHaveBeenLastCalledWith(list.at(-1));
  });
  it.each([
    undefined, {}, { tool_calls: null }, { tool_calls: [], token: "PRIVATE" },
    { tool_calls: [{ ...calls[0], text: "RAW_TOOL" }] },
    { tool_calls: [{ ...calls[0], arguments: { question: "PRIVATE" } }] },
    { tool_calls: [{ ...calls[0], status: "pending" }] },
    { tool_calls: [{ ...calls[0], code: "<script>unsafe</script>" }] },
    { tool_calls: [calls[0], calls[0]] },
  ])("rejects missing or unsafe meta %# before passing it to the consumer", async meta => {
    for (const failed of [false, true]) {
      const list = terminal(failed);
      const last = list.at(-1)!;
      const raw = frames(list).replace(JSON.stringify("meta") + ":" + JSON.stringify("meta" in last.data ? last.data.meta : null), JSON.stringify("meta") + ":" + JSON.stringify(meta));
      const receive = vi.fn<(event: ChatEvent) => void>();
      await expect(parseChatStream(stream(raw), ids.conversation, receive)).rejects.toThrow(InterruptedStream);
      expect(receive.mock.calls.every(([e]) => !["message.completed", "message.error"].includes(e.name))).toBe(true);
    }
  });
});

describe("student tool outcome rendering", () => {
  it.each([false, true])("shows terminal and historical statuses without rendering remote text, failed=%s", async failed => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const path = String(input);
      if (path === "/api/auth/me") return json({ user_id: ids.user, account: "fixture", class_id: ids.material, role: "student" });
      if (path === "/api/agents") return json([agent]);
      if (path.endsWith("/messages")) return new Response(stream(frames(terminal(failed))), { headers: { "content-type": "text/event-stream" } });
      if (path.startsWith(`/api/conversations/${ids.conversation}?`)) return json({ ...conversation, messages: [{ ...historical, id: ids.material, tool_calls: calls }] });
      throw new Error("Unexpected fixture route");
    });
    render(<MemoryRouter initialEntries={[`/conversations/${ids.conversation}`]}><App /></MemoryRouter>);
    await screen.findByText("已刷新服务器记录。");
    const history = screen.getByRole("region", { name: "消息 2 的工具状态" });
    expect(history).toHaveTextContent("formula_hint@campus-tools：成功");
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("当前问题"), "欧姆定律？");
    await user.click(screen.getByRole("button", { name: "发送消息" }));
    await screen.findByText(failed ? "生成失败；请刷新服务器记录后决定是否发送新问题。" : "回答已完成。");
    const outcome = screen.getByRole("region", { name: "消息 4 的工具状态" });
    expect(outcome).toHaveTextContent("formula_hint@campus-tools：成功（ok）");
    expect(outcome).toHaveTextContent("unit_convert@campus-tools：已拒绝（server_disconnected）");
    expect(outcome).toHaveTextContent("tool0@campus-tools：执行错误（tool_timeout）");
    expect(outcome).toHaveTextContent("工具结果不是事实证据");
    expect(within(outcome).queryByRole("button")).not.toBeInTheDocument();
    expect(document.querySelector("script,img")).toBeNull();
    if (failed) expect(screen.getByRole("article", { name: "智能体消息 4" })).toHaveTextContent("本轮生成失败");
  });
});

describe("minimal class audit UI", () => {
  it("paginates actual audit contracts and displays only minimal fixed fields", async () => {
    const requests: string[] = [];
    const row = { ...calls[0], id: ids.assistant, server_id: ids.material, user_id: ids.user, conversation_id: ids.conversation, assistant_message_id: ids.assistant, created_at: "2026-10-21T00:00:00Z", completed_at: "2026-10-21T00:00:01Z", raw_result: "DO_NOT_RENDER", question: "DO_NOT_RENDER", token: "DO_NOT_RENDER" };
    vi.spyOn(globalThis, "fetch").mockImplementation(async input => {
      const path = String(input); requests.push(path);
      if (path === "/api/auth/me") return json({ user_id: ids.user, account: "fixture", class_id: ids.material, role: "teacher" });
      if (path === "/api/mcp/audits?limit=100") return json({ items: [row], next_cursor: "cursor=" });
      if (path.endsWith("cursor=cursor%3D")) return json({ items: [{ ...row, ...calls[1], id: ids.skill }], next_cursor: null });
      throw new Error("Unexpected fixture route");
    });
    render(<MemoryRouter initialEntries={["/mcp/audits"]}><App /></MemoryRouter>);
    await screen.findByRole("heading", { name: "formula_hint@campus-tools" });
    expect(screen.queryByText("DO_NOT_RENDER")).not.toBeInTheDocument();
    expect(screen.getByText(/发起用户/)).toHaveTextContent(ids.user);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "加载更多工具审计" }));
    await screen.findByRole("heading", { name: "unit_convert@campus-tools" });
    expect(screen.getByText(/安全原因：server_disconnected/)).toHaveTextContent("已拒绝");
    expect(requests).toContain("/api/mcp/audits?limit=100&cursor=cursor%3D");
    expect(screen.queryByRole("button", { name: "加载更多工具审计" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /会话标识/ })).not.toBeInTheDocument();
  });
});
