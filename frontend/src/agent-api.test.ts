import { webcrypto } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, createAgentApi, InterruptedStream, parseChatStream, type ChatEvent } from "./agent-api";
import { events, frames, ids, source, stream } from "./test/chat-fixtures";

beforeEach(() => vi.stubGlobal("crypto", webcrypto));
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const auth = () => ({ authorizationHeader: () => ({ Authorization: "Bearer synthetic-token" }), handleUnauthenticated: vi.fn() });

describe("authenticated agent API", () => {
  it("clears authentication on JSON and pre-stream 401 without leaking server text", async () => {
    const a = auth(); const api = createAgentApi(a);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ detail: { code: "unauthenticated", message: "private body" } }), { status: 401 }));
    await expect(api.agents()).rejects.toThrow(ApiError);
    await expect(api.send(ids.conversation, "question", vi.fn())).rejects.toThrow("登录已失效");
    expect(a.handleUnauthenticated).toHaveBeenCalledTimes(2);
  });
  it("does not fetch without a token", async () => {
    const fetcher = vi.spyOn(globalThis, "fetch"); const unauth = vi.fn();
    await expect(createAgentApi({ authorizationHeader: () => null, handleUnauthenticated: unauth }).skills()).rejects.toThrow(ApiError);
    expect(fetcher).not.toHaveBeenCalled(); expect(unauth).toHaveBeenCalledOnce();
  });
  it("uses one Bearer header, exact methods/bodies, encoded ids, and no client history", async () => {
    const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response("{}"));
    const api = createAgentApi(auth());
    await api.saveAgent({ name: "a", description: null, system_prompt: "p", skill_ids: [] });
    await api.saveAgent({ name: "a", description: null, system_prompt: "p", skill_ids: [] }, ids.agent);
    await api.publication(ids.agent, true); await api.publication(ids.agent, false); await api.retireAgent(ids.agent);
    await api.saveSkill({ name: "s", skill_type: "solution_guidance", instructions: "i" });
    await api.saveSkill({ name: "s", skill_type: "solution_guidance", instructions: "i" }, ids.skill);
    await api.skill(ids.skill); await api.retireSkill(ids.skill); await api.agent(ids.agent); await api.skills(); await api.catalog();
    await api.createConversation(ids.agent); await api.conversations(); await api.conversation(ids.conversation, 100);
    await api.deleteConversation(ids.conversation); await api.audit(ids.agent, "true"); await api.auditConversation(ids.agent, ids.conversation, 200);
    expect(fetcher.mock.calls.map(([url, init]) => [url, init?.method])).toContainEqual([`/api/agents/${ids.agent}/publish`, "POST"]);
    expect(fetcher.mock.calls.map(([url]) => url)).toContain(`/api/agents/${ids.agent}/conversations/${ids.conversation}?after_ordinal=200&limit=100`);
    for (const [, init] of fetcher.mock.calls) expect([...new Headers(init?.headers).entries()].filter(([k]) => k === "authorization")).toEqual([["authorization", "Bearer synthetic-token"]]);
  });
  it("sends authenticated fetch SSE once and never retries interrupted requests", async () => {
    const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(stream(frames(events().slice(0, 2))), { headers: { "content-type": "text/event-stream" } }));
    await expect(createAgentApi(auth()).send(ids.conversation, "current only", vi.fn())).rejects.toThrow(InterruptedStream);
    expect(fetcher).toHaveBeenCalledOnce();
    expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body))).toEqual({ content: "current only" });
  });
  it("rejects untrusted download origins and paths without sending a token", async () => {
    const fetcher = vi.spyOn(globalThis, "fetch");
    for (const action of ["https://external.invalid/", "//external.invalid/", "/api/auth/me"]) {
      await expect(createAgentApi(auth()).download({ ...source, action })).rejects.toThrow(ApiError);
    }
    expect(fetcher).not.toHaveBeenCalled();
  });
});

describe("SSE contract parser", () => {
  it.each([1, 2, 17, 65536])("assembles Unicode frames split at %i bytes, skips heartbeats and handles CRLF", async split => {
    const seen: ChatEvent[] = [];
    await parseChatStream(stream((": heartbeat\n\n" + frames()).replace(/\n/g, "\r\n"), split), ids.conversation, e => seen.push(e));
    expect(seen).toEqual(events());
  });
  it("accepts exact refusal and safe terminal error", async () => {
    await expect(parseChatStream(stream(frames(events("根据本班资料无法回答该问题", false))), ids.conversation, vi.fn())).resolves.toBeUndefined();
    const first = events()[0];
    const error: ChatEvent = { name: "message.error", data: { conversation_id: ids.conversation, user_message_id: ids.user, assistant_message_id: ids.assistant, sequence: 2, code: "generation_timeout", retryable: true, meta: { tool_calls: [] } } };
    const receive = vi.fn();
    await parseChatStream(stream(frames([first, error])), ids.conversation, receive);
    expect(receive).toHaveBeenLastCalledWith(error);
  });
  it.each([
    "gap", "duplicate", "wrong-conversation", "wrong-message", "missing-start", "no-terminal", "double-terminal", "delta-after-citation", "unknown-event", "bad-digest", "bad-length", "bad-revision", "bad-source", "duplicate-source", "missing-source", "bad-refusal", "error-after-delta", "trailing-data", "oversize-frame", "malformed-json",
  ])("rejects %s without auto-retry", async kind => {
    let list = structuredClone(events());
    if (kind === "gap") list[1].data.sequence = 3;
    if (kind === "duplicate") list.splice(2, 0, list[1]);
    if (kind === "wrong-conversation") list[1].data.conversation_id = ids.agent;
    if (kind === "wrong-message") list[1].data.assistant_message_id = ids.agent;
    if (kind === "missing-start") list = list.slice(1);
    if (kind === "no-terminal") list.pop();
    if (kind === "double-terminal") list.push(list.at(-1)!);
    if (kind === "delta-after-citation") { [list[2], list[3]] = [list[3], list[2]]; list[2].data.sequence = 3; list[3].data.sequence = 4; }
    if (kind === "bad-digest" && list[4].name === "message.completed") list[4].data.answer_sha256 = "0".repeat(64);
    if (kind === "bad-length" && list[4].name === "message.completed") list[4].data.answer_length++;
    if (kind === "bad-revision" && list[4].name === "message.completed") list[4].data.configuration_revision_id = ids.skill;
    if (kind === "bad-source" && list[3].name === "citation") list[3].data.source.action = "https://external.invalid";
    if (kind === "duplicate-source") { list.splice(4, 0, structuredClone(list[3])); list[4].data.sequence = 5; list[5].data.sequence = 6; }
    if (kind === "missing-source") { list.splice(3, 1); list[3].data.sequence = 4; }
    if (kind === "bad-refusal") list = events("incorrect refusal", false);
    if (kind === "error-after-delta") list[2] = { name: "message.error", data: { ...list[2].data, code: "generation_failed", retryable: true, meta: { tool_calls: [] } } };
    let raw = frames(list);
    if (kind === "unknown-event") raw = raw.replace("answer.delta", "unsafe.event");
    if (kind === "trailing-data") raw += "data: {}";
    if (kind === "oversize-frame") raw = "data: " + "x".repeat(64001);
    if (kind === "malformed-json") raw = raw.replace('"sequence":1', '"sequence":no');
    await expect(parseChatStream(stream(raw), ids.conversation, vi.fn())).rejects.toThrow(InterruptedStream);
  });
  it("rejects extra sensitive event fields before calling the consumer", async () => {
    const first = events()[0];
    const receive = vi.fn();
    const raw = `event: message.started\ndata: ${JSON.stringify({ ...first.data, system_prompt: "synthetic-private" })}\n\n`;
    await expect(parseChatStream(stream(raw), ids.conversation, receive)).rejects.toThrow(InterruptedStream);
    expect(receive).not.toHaveBeenCalled();
  });
  it("rejects invalid UTF-8 and transport failures", async () => {
    await expect(parseChatStream(new ReadableStream({ start(c) { c.enqueue(new Uint8Array([255])); c.close(); } }), ids.conversation, vi.fn())).rejects.toThrow(InterruptedStream);
    await expect(parseChatStream(new ReadableStream({ start(c) { c.error(new Error("network")); } }), ids.conversation, vi.fn())).rejects.toThrow(InterruptedStream);
  });
});
