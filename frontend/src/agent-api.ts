export type CatalogAgent = { id: string; name: string; description: string | null };
export type AgentInput = { name: string; description: string | null; system_prompt: string; skill_ids: string[] };
export type Agent = CatalogAgent & AgentInput & {
  state: "draft" | "published" | "retired";
  current_revision_id: string | null;
  published_revision_id: string | null;
};
export type SkillInput = { name: string; skill_type: "solution_guidance"; instructions: string };
export type Skill = SkillInput & { id: string; state: "active" | "retired"; current_revision_id: string | null };
export type Source = {
  source_id: string; material_id: string; title: string; original_filename: string;
  excerpt: string; page: number | null; line_start: number | null; line_end: number | null;
  section: string | null; action: string;
};
export type Message = {
  id: string; ordinal: number; role: "user" | "assistant";
  state: "processing" | "completed" | "failed"; content: string | null;
  safe_error_code: string | null; retrieval_mode: string | null;
  applied_agent_revision_id: string | null; configuration_updated: boolean;
  created_at: string; completed_at: string | null; citations: Source[];
};
export type ConversationSummary = {
  id: string; agent_id: string; agent_name: string; student_id: string; student_account: string;
  creator_retains_audit_access: true; deleted_at: string | null; created_at: string; updated_at: string;
};
export type Conversation = ConversationSummary & { messages: Message[]; next_after_ordinal: number | null };
type Envelope = { sequence: number; conversation_id: string; user_message_id: string; assistant_message_id: string };
type Configuration = { configuration_revision_id: string; configuration_updated: boolean };
export type ChatEvent =
  | { name: "message.started"; data: Envelope & Configuration }
  | { name: "answer.delta"; data: Envelope & { delta: string } }
  | { name: "citation"; data: Envelope & { source: Source } }
  | { name: "message.completed"; data: Envelope & Configuration & {
    status: "answered" | "insufficient_evidence"; answer_length: number; answer_sha256: string;
    requested_mode: "hybrid"; retrieval_mode: "keyword" | "vector" | "hybrid" | "keyword_only"; completed_at: string;
  } }
  | { name: "message.error"; data: Envelope & { code: string; retryable: boolean } };

function safeApiMessage(status: number, code: string): string {
  if (code === "agent_not_ready") return "智能体尚未就绪：请绑定有效的解题引导技能后发布。";
  const messages: Record<number, string> = {
    401: "登录已失效，请重新登录。", 404: "资源不存在或无权访问。",
    409: "当前操作冲突，请刷新后重试。", 429: "发送过于频繁，请稍后再试。",
  };
  return messages[status] ?? "操作失败，请检查输入或稍后重试。";
}
export class ApiError extends Error {
  constructor(public status: number, public code: string) { super(safeApiMessage(status, code)); }
}
export class InterruptedStream extends Error {
  constructor() { super("连接中断或事件无效；请刷新会话确认服务器结果，不要自动重发。"); }
}
const segment = (id: string) => encodeURIComponent(id);
const record = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const uuid = (v: unknown): v is string => typeof v === "string" && /^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/i.test(v);
const text = (v: unknown, max: number): v is string => typeof v === "string" && v.length <= max;
export function validSource(v: unknown): v is Source {
  return record(v) && Object.keys(v).every(k => ["source_id", "material_id", "title", "original_filename", "excerpt", "page", "line_start", "line_end", "section", "action"].includes(k)) && typeof v.source_id === "string" && /^S[1-9][0-9]{0,2}$/.test(v.source_id)
    && uuid(v.material_id) && text(v.title, 1000) && text(v.original_filename, 1000)
    && text(v.excerpt, 4000) && v.excerpt.length > 0
    && v.action === `/api/materials/${segment(v.material_id)}/download`
    && [v.page, v.line_start, v.line_end].every(n => n === null || (Number.isInteger(n) && Number(n) >= 1))
    && (v.section === null || text(v.section, 200));
}

/** Strictly ordered semantic events; comments do not consume sequence numbers. Never auto-retry a POST. */
export async function parseChatStream(
  body: ReadableStream<Uint8Array>, conversationId: string, onEvent: (event: ChatEvent) => void,
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let buffer = "", sequence = 0, answer = "";
  const phase: { value: "start" | "answer" | "sources" | "done" } = { value: "start" };
  let ids: Record<string, unknown> | null = null;
  const sources = new Set<string>();
  async function frame(raw: string) {
    if (raw.length > 64000) throw new InterruptedStream();
    let name = ""; const data: string[] = [];
    for (const line of raw.split("\n")) {
      if (!line || line.startsWith(":")) continue;
      const colon = line.indexOf(":");
      const field = colon < 0 ? line : line.slice(0, colon);
      let value = colon < 0 ? "" : line.slice(colon + 1);
      if (value.startsWith(" ")) value = value.slice(1);
      if (field === "event" && !name) name = value;
      else if (field === "data") data.push(value);
      else throw new InterruptedStream();
    }
    if (!name && !data.length) return;
    let v: unknown;
    try { v = JSON.parse(data.join("\n")); } catch { throw new InterruptedStream(); }
    if (!record(v) || phase.value === "done" || v.sequence !== sequence + 1 || v.conversation_id !== conversationId
      || !uuid(v.user_message_id) || !uuid(v.assistant_message_id) || v.user_message_id === v.assistant_message_id
      || (ids && ["user_message_id", "assistant_message_id"].some(k => ids?.[k] !== v[k]))) throw new InterruptedStream();
    const commonKeys = ["sequence", "conversation_id", "user_message_id", "assistant_message_id"];
    const configurationKeys = ["configuration_revision_id", "configuration_updated"];
    const eventKeys: Record<string, string[]> = {
      "message.started": configurationKeys, "answer.delta": ["delta"], "citation": ["source"],
      "message.completed": [...configurationKeys, "status", "answer_length", "answer_sha256", "requested_mode", "retrieval_mode", "completed_at"],
      "message.error": ["code", "retryable"],
    };
    if (!Object.hasOwn(eventKeys, name) || Object.keys(v).some(k => ![...commonKeys, ...eventKeys[name]].includes(k))) throw new InterruptedStream();
    const config = () => uuid(v.configuration_revision_id) && typeof v.configuration_updated === "boolean";
    if (name === "message.started") {
      if (phase.value !== "start" || !config()) throw new InterruptedStream();
      ids = v; phase.value = "answer";
    } else if (!ids) throw new InterruptedStream();
    else if (name === "answer.delta") {
      if (phase.value !== "answer" || !text(v.delta, 1024) || !v.delta || [...v.delta].length > 512) throw new InterruptedStream();
      answer += v.delta;
      if ([...answer].length > 20000) throw new InterruptedStream();
    } else if (name === "citation") {
      if (!validSource(v.source) || sources.has(v.source.source_id) || sources.size >= 100) throw new InterruptedStream();
      sources.add(v.source.source_id); phase.value = "sources";
    } else if (name === "message.completed") {
      if (!config() || v.configuration_revision_id !== ids.configuration_revision_id
        || v.configuration_updated !== ids.configuration_updated || !answer
        || v.answer_length !== [...answer].length || typeof v.answer_sha256 !== "string"
        || !/^[a-f0-9]{64}$/.test(v.answer_sha256) || v.requested_mode !== "hybrid"
        || !["keyword", "vector", "hybrid", "keyword_only"].includes(String(v.retrieval_mode))
        || typeof v.completed_at !== "string" || !Number.isFinite(Date.parse(v.completed_at))) throw new InterruptedStream();
      const markers = new Set([...answer.matchAll(/\[(S[1-9][0-9]{0,2})\]/g)].map(m => m[1]));
      if (v.status === "insufficient_evidence") {
        if (answer !== "根据本班资料无法回答该问题" || sources.size) throw new InterruptedStream();
      } else if (v.status !== "answered" || !sources.size || markers.size !== sources.size
        || [...markers].some(id => !sources.has(id))) throw new InterruptedStream();
      const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(answer));
      if (Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, "0")).join("") !== v.answer_sha256) throw new InterruptedStream();
      phase.value = "done";
    } else if (name === "message.error") {
      if (answer || sources.size || typeof v.retryable !== "boolean" || !["generation_failed", "generation_invalid", "answer_generation_unavailable", "generation_timeout", "source_unavailable"].includes(String(v.code))) throw new InterruptedStream();
      phase.value = "done";
    } else throw new InterruptedStream();
    sequence++;
    onEvent({ name, data: v } as ChatEvent);
  }
  try {
    for (;;) {
      const { value, done } = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      // Normalize CRLF only when both bytes have arrived.
      buffer = buffer.replace(/\r\n/g, "\n");
      let end: number;
      while ((end = buffer.indexOf("\n\n")) >= 0) {
        await frame(buffer.slice(0, end)); buffer = buffer.slice(end + 2);
      }
      if (buffer.length > 64000) throw new InterruptedStream();
      if (done) break;
    }
    if (phase.value !== "done" || buffer.trim()) throw new InterruptedStream();
  } catch {
    await reader.cancel().catch(() => undefined);
    throw new InterruptedStream();
  } finally { reader.releaseLock(); }
}

export function createAgentApi(auth: { authorizationHeader: () => HeadersInit | null; handleUnauthenticated: () => void }) {
  async function request(path: string, method = "GET", payload?: unknown, signal?: AbortSignal) {
    const headers = new Headers(auth.authorizationHeader() ?? {});
    if (!headers.has("Authorization")) { auth.handleUnauthenticated(); throw new ApiError(401, "unauthenticated"); }
    if (payload !== undefined) headers.set("Content-Type", "application/json");
    const response = await fetch(`/api${path}`, { method, headers, body: payload === undefined ? undefined : JSON.stringify(payload), signal });
    if (!response.ok) {
      if (response.status === 401) auth.handleUnauthenticated();
      const body: unknown = await response.json().catch(() => null);
      const code = record(body) && record(body.detail) && typeof body.detail.code === "string" ? body.detail.code : "request_failed";
      throw new ApiError(response.status, code);
    }
    return response;
  }
  async function json<T>(path: string, method?: string, data?: unknown): Promise<T> {
    const response = await request(path, method, data);
    return response.json() as Promise<T>;
  }
  return {
    catalog: () => json<CatalogAgent[]>("/agents"),
    agents: () => json<Agent[]>("/agents"),
    agent: (id: string) => json<Agent>(`/agents/${segment(id)}`),
    saveAgent: (data: AgentInput, id?: string) => json<Agent>(id ? `/agents/${segment(id)}` : "/agents", id ? "PATCH" : "POST", data),
    retireAgent: (id: string) => json<Agent>(`/agents/${segment(id)}`, "DELETE"),
    publication: (id: string, publish: boolean) => json<Agent>(`/agents/${segment(id)}/${publish ? "publish" : "unpublish"}`, "POST"),
    skills: () => json<Skill[]>("/skills"),
    skill: (id: string) => json<Skill>(`/skills/${segment(id)}`),
    saveSkill: (data: SkillInput, id?: string) => json<Skill>(id ? `/skills/${segment(id)}` : "/skills", id ? "PATCH" : "POST", data),
    retireSkill: (id: string) => json<Skill>(`/skills/${segment(id)}`, "DELETE"),
    conversations: () => json<ConversationSummary[]>("/conversations"),
    createConversation: (id: string) => json<Conversation>("/conversations", "POST", { agent_id: id }),
    conversation: (id: string, after = 0) => json<Conversation>(`/conversations/${segment(id)}?after_ordinal=${after}&limit=100`),
    deleteConversation: (id: string) => json<ConversationSummary>(`/conversations/${segment(id)}`, "DELETE"),
    audit: (agent: string, deleted: string) => json<Conversation[]>(`/agents/${segment(agent)}/conversations${deleted ? `?deleted=${deleted}` : ""}`),
    auditConversation: (agent: string, id: string, after = 0) => json<Conversation>(`/agents/${segment(agent)}/conversations/${segment(id)}?after_ordinal=${after}&limit=100`),
    send: async (id: string, content: string, receive: (event: ChatEvent) => void, signal?: AbortSignal) => {
      const response = await request(`/conversations/${segment(id)}/messages`, "POST", { content }, signal);
      if (!response.headers.get("content-type")?.toLowerCase().startsWith("text/event-stream") || !response.body) throw new InterruptedStream();
      await parseChatStream(response.body, id, receive);
    },
    download: async (source: Source) => {
      if (!validSource(source)) throw new ApiError(400, "invalid_source");
      const response = await request(`/materials/${segment(source.material_id)}/download`);
      const url = URL.createObjectURL(await response.blob());
      try {
        const link = document.createElement("a"); link.href = url; link.download = source.original_filename; link.click();
      } finally { URL.revokeObjectURL(url); }
    },
  };
}
export type AgentApi = ReturnType<typeof createAgentApi>;
