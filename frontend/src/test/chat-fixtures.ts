import { createHash } from "node:crypto";
import type { Agent, ChatEvent, Conversation, Message, Skill, Source } from "../agent-api";
export const ids = {
  agent: "00000000-0000-4000-8000-000000000001", skill: "00000000-0000-4000-8000-000000000002",
  conversation: "00000000-0000-4000-8000-000000000003", user: "00000000-0000-4000-8000-000000000004",
  assistant: "00000000-0000-4000-8000-000000000005", revision: "00000000-0000-4000-8000-000000000006",
  material: "00000000-0000-4000-8000-000000000007",
};
export const skill: Skill = { tools: ["knowledge_search"], id: ids.skill, state: "active", name: "引导技能", skill_type: "solution_guidance", instructions: "先给提示，再追问。", current_revision_id: ids.revision };
export const agent: Agent = { id: ids.agent, name: "课程导师", description: "本班课程引导", state: "published", system_prompt: "教师私有提示", skill_ids: [ids.skill], current_revision_id: ids.revision, published_revision_id: ids.revision };
export const source: Source = { source_id: "S1", material_id: ids.material, title: "课程笔记", original_filename: "notes.txt", excerpt: "合成课程证据", page: null, line_start: 1, line_end: 2, section: null, action: `/api/materials/${ids.material}/download` };
export const conversation: Conversation = { id: ids.conversation, agent_id: ids.agent, agent_name: agent.name, student_id: ids.user, student_account: "student.fixture", creator_retains_audit_access: true, deleted_at: null, created_at: "2026-10-15T00:00:00Z", updated_at: "2026-10-15T00:00:00Z", messages: [], next_after_ordinal: null };
export const answer = "先检查条件 😀[S1]。<img src=x onerror=alert(1)>";
export function events(content = answer, citations = true): ChatEvent[] {
  const common = { conversation_id: ids.conversation, user_message_id: ids.user, assistant_message_id: ids.assistant };
  const config = { configuration_revision_id: ids.revision, configuration_updated: true };
  const list: ChatEvent[] = [
    { name: "message.started", data: { ...common, ...config, sequence: 1 } },
    { name: "answer.delta", data: { ...common, sequence: 2, delta: content.slice(0, 2) } },
    { name: "answer.delta", data: { ...common, sequence: 3, delta: content.slice(2) } },
  ];
  if (citations) list.push({ name: "citation", data: { ...common, sequence: 4, source } });
  list.push({ name: "message.completed", data: { ...common, ...config, sequence: list.length + 1, status: citations ? "answered" : "insufficient_evidence", answer_length: [...content].length, answer_sha256: createHash("sha256").update(content).digest("hex"), requested_mode: "hybrid", retrieval_mode: "keyword_only", completed_at: "2026-10-15T00:00:01Z", meta: { tool_calls: [] } } });
  return list;
}
export function frames(list = events()): string { return list.map(e => `event: ${e.name}\ndata: ${JSON.stringify(e.data)}\n\n`).join(""); }
export function stream(text = frames(), split = 17): ReadableStream<Uint8Array> {
  const bytes = new TextEncoder().encode(text);
  return new ReadableStream({ start(controller) { for (let i = 0; i < bytes.length; i += split) controller.enqueue(bytes.slice(i, i + split)); controller.close(); } });
}
export const historical: Message = { tool_calls: [], id: ids.assistant, ordinal: 2, role: "assistant", state: "completed", content: answer, citations: [source], safe_error_code: null, applied_agent_revision_id: ids.revision, configuration_updated: true, retrieval_mode: "keyword_only", created_at: conversation.created_at, completed_at: conversation.updated_at };
