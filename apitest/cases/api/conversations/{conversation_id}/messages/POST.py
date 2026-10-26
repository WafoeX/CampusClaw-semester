import os
from datetime import datetime
from typing import Any

from apitest.clients import Context, parse_sse
from apitest.mcp_scenarios import McpScenario
from apitest.scenarios import AGENT, MISSING, REFUSAL, SKILL
from apitest.support import Checks, Operation


def run(context: Context, checks: Checks) -> None:
    s = McpScenario(context, checks)
    conversation, agent = s.conversation()
    identifier = conversation["id"]
    path = f"/api/conversations/{identifier}/messages"
    failure = os.environ.get("APITEST_EXPECT_MESSAGE_ERROR")
    if failure:
        checks.require(failure in {"generation_invalid", "answer_generation_unavailable"}, "safe")
        events = s.stream(identifier, "ALPHA_FERN", expected="message.error")
        checks.require(
            [event["event"] for event in events] == ["message.started", "message.error"]
            and events[-1]["data"]["code"] == failure
            and len(s.messages(identifier)) == 2,
            "stream.terminal",
        )
        server, _, bound = s.bound_conversation()
        with_tools = s.stream(bound["id"], "ALPHA_FERN 欧姆定律", expected="message.error")
        s.verify_tool_turn(with_tools, server, "ok", "ok")
        checks.require(with_tools[-1]["data"]["code"] == failure, "stream.terminal")
        return
    invalid: list[dict[str, Any]] = [{"content": " "}, {"content": "x" * 8001}]
    invalid.extend(
        {"content": "ALPHA_FERN", field: []}
        for field in (
            "history",
            "messages",
            "system_prompt",
            "citations",
            "class_id",
            "assistant_content",
        )
    )
    for payload in invalid:
        s.call("POST", path, account="student.alpha", body=payload, status=400)
    s.call("POST", path, account="student.alpha", body={"content": "x" * 40000}, status=413)
    s.call("POST", path, account=None, body={"content": "ALPHA_FERN"}, status=401)
    s.call("POST", path, body={"content": "ALPHA_FERN"}, status=403)
    s.hidden(
        "POST",
        path,
        f"/api/conversations/{MISSING}/messages",
        body={"content": "ALPHA_FERN"},
        accounts=("student.alpha.other", "student.beta"),
    )
    checks.require(s.messages(identifier) == [], "database.unchanged")
    content = "ALPHA_FERN 只要最终答案，不要提示"
    first = s.stream(identifier, content)
    answer = "".join(event["data"]["delta"] for event in first if event["event"] == "answer.delta")
    checks.require(
        first[-1]["data"]["status"] == "answered"
        and "？" in answer
        and "请按材料" in answer
        and "先观察叶脉再比较边缘" not in answer
        and "最终答案" not in answer,
        "stream.answer",
    )
    checks.require(
        type(first[0]["data"]["configuration_updated"]) is bool
        and not first[0]["data"]["configuration_updated"],
        "stream.configuration",
    )
    source = next(event["data"]["source"] for event in first if event["event"] == "citation")
    checks.require(source["title"] == "ALPHA_FERN", "stream.citations")
    previous = s.messages(identifier)
    updated = s.call(
        "PATCH",
        f"/api/agents/{agent['id']}",
        body={**AGENT, "system_prompt": "更新后的观察引导。", "skill_ids": agent["skill_ids"]},
    )
    s.verify_resource(updated, "agents")
    s.call(
        "POST",
        path,
        account="student.alpha",
        body={"content": "ALPHA_FERN"},
        status=409,
        code="agent_not_ready",
    )
    checks.require(previous == s.messages(identifier), "database.unchanged")
    s.call("POST", f"/api/agents/{agent['id']}/publish")
    second = s.stream(identifier, "ALPHA_FERN 接下来该怎么检查？")
    checks.require(
        type(second[0]["data"]["configuration_updated"]) is bool
        and second[0]["data"]["configuration_updated"]
        and second[0]["data"]["configuration_revision_id"]
        != first[0]["data"]["configuration_revision_id"],
        "stream.configuration",
    )
    skill = s.call(
        "PATCH",
        f"/api/skills/{agent['skill_ids'][0]}",
        body={**SKILL, "instructions": "先提出观察提示，再请学生复查。"},
    )
    s.verify_resource(skill, "skills")
    s.call("POST", f"/api/agents/{agent['id']}/publish")
    third = s.stream(identifier, "ALPHA_FERN 再检查一次")
    checks.require(
        type(third[0]["data"]["configuration_updated"]) is bool
        and third[0]["data"]["configuration_updated"]
        and third[0]["data"]["configuration_revision_id"]
        != second[0]["data"]["configuration_revision_id"],
        "stream.configuration",
    )
    checks.require(s.messages(identifier)[:2] == previous, "database.revisions")
    # New conversations ensure earlier ALPHA evidence cannot mask ordinary absence.
    absent, _ = s.conversation()
    other, _ = s.conversation()
    no_evidence = s.stream(absent["id"], "UNINDEXED_ZEBRA")
    other_class = s.stream(other["id"], "BETA_CRYSTAL")
    checks.require(
        [item["event"] for item in no_evidence]
        == [item["event"] for item in other_class]
        == ["message.started", "answer.delta", "message.completed"]
        and no_evidence[1]["data"]["delta"] == other_class[1]["data"]["delta"] == REFUSAL
        and no_evidence[-1]["data"]["status"]
        == other_class[-1]["data"]["status"]
        == "insufficient_evidence",
        "response.refusal",
    )
    # Consume message.started before sending the conflicting request. The configured
    # fixture-delayed model provides a bounded 2s window, not a timing-only guess.
    concurrent, _ = s.conversation()
    concurrent_path = f"/api/conversations/{concurrent['id']}/messages"
    token = s.token("student.alpha")
    with context.client.http.stream(
        "POST",
        concurrent_path,
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "ALPHA_FERN"},
    ) as response:
        checks.require(
            response.status_code == 200
            and response.headers.get("content-type", "").startswith("text/event-stream"),
            "response.media_type",
        )
        chunks = response.iter_bytes()
        raw = bytearray()
        for chunk in chunks:
            raw.extend(chunk)
            if b"\n\n" in raw:
                break
        checks.require(
            b"event: message.started\n" in raw and len(s.messages(concurrent["id"])) == 2,
            "stream.order",
        )
        s.call(
            "POST",
            concurrent_path,
            account="student.alpha",
            body={"content": "second request"},
            status=409,
            code="turn_in_progress",
        )
        for chunk in chunks:
            checks.require(len(raw) + len(chunk) <= 2000000, "response.bounds")
            raw.extend(chunk)
    events = parse_sse(bytes(raw))
    s.verify_stream(events, "ALPHA_FERN")
    checks.require(
        len(s.messages(concurrent["id"])) == 2 and events[-1]["event"] == "message.completed",
        "database.messages",
    )
    terminal = events[-1]["data"]
    checks.require(
        datetime.fromisoformat(terminal["completed_at"]).tzinfo is not None, "stream.terminal"
    )
    checks.require(terminal["meta"]["tool_calls"] == [], "stream.tool_calls")
    server, bound_skill, bound = s.bound_conversation()
    successful = s.stream(bound["id"], "ALPHA_FERN 欧姆定律")
    s.verify_tool_turn(successful, server, "ok", "ok")
    checks.require(successful[-1]["data"]["status"] == "answered", "stream.answer")
    s.call("POST", f"/api/mcp/servers/{server['id']}/disconnect")
    s.discovery({**server, "state": "disconnected"})
    s.call(
        "PATCH",
        f"/api/skills/{bound_skill['id']}",
        body={**SKILL, "tools": bound_skill["tools"]},
        status=409,
        code="server_disconnected",
    )
    denied = s.stream(bound["id"], "ALPHA_FERN 欧姆定律 再检查一次")
    s.verify_tool_turn(denied, server, "denied", "server_disconnected")
    s.verify_tool_turn(successful, server, "ok", "ok")
    checks.require(denied[-1]["data"]["status"] == "answered", "stream.answer")
    no_material_server, _, no_material = s.bound_conversation()
    unsupported = s.stream(no_material["id"], "UNINDEXED_ZEBRA 欧姆定律")
    s.verify_tool_turn(unsupported, no_material_server, "ok", "ok")
    checks.require(
        unsupported[-1]["data"]["status"] == "insufficient_evidence"
        and unsupported[1]["data"]["delta"] == REFUSAL
        and [event["event"] for event in unsupported]
        == ["message.started", "answer.delta", "message.completed"],
        "response.refusal",
    )


OPERATION = Operation("POST", "/api/conversations/{conversation_id}/messages", run)
