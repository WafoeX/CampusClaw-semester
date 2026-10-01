import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";

const token = "header.payload.signature";
const teacher = { user_id: "teacher-1", account: "teacher.alpha", role: "teacher" as const, class_id: "class-1" };
const student = { ...teacher, user_id: "student-1", account: "student.alpha", role: "student" as const };

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function renderApp(path: string) {
  window.localStorage.setItem("campusclaw.access-token", token);
  return render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>);
}

beforeEach(() => window.localStorage.clear());
afterEach(() => vi.restoreAllMocks());

describe("material library", () => {
  it("shows class materials and fetches downloads with a Bearer token", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(teacher))
      .mockResolvedValueOnce(jsonResponse([{ id: "material-1", title: "Week one", original_filename: "week-one.pdf", content_type: "application/pdf", byte_size: 2048, sha256: "a".repeat(64), uploader_id: "teacher-1", created_at: "2030-01-01T00:00:00Z" }]))
      .mockResolvedValueOnce(new Response(new Blob(["file"]), { status: 200 }));
    vi.stubGlobal("URL", { createObjectURL: vi.fn(() => "blob:test"), revokeObjectURL: vi.fn() });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    renderApp("/materials");
    await userEvent.setup().click(await screen.findByRole("button", { name: /下载文件/ }));
    expect(fetchMock).toHaveBeenLastCalledWith("/api/materials/material-1/download", { headers: { Authorization: `Bearer ${token}` } });
    expect(click).toHaveBeenCalled();
  });

  it("does not offer upload controls to students", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(jsonResponse(student)).mockResolvedValueOnce(jsonResponse([]));
    renderApp("/materials");
    expect(await screen.findByRole("heading", { name: /teaching materials/i })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "上传资料" })).not.toBeInTheDocument();
  });

  it("submits an independent single-turn knowledge question without class scope", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(student))
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(jsonResponse({
        status: "answered",
        answer: "答案 [S1]",
        citations: ["S1"],
        requested_mode: "hybrid",
        effective_mode: "hybrid",
        sources: [{ source_id: "S1", material_id: "m1", title: "课程", original_filename: "a.txt", excerpt: "答案", page: null, line_start: 1, line_end: 2, section: null, action: "/api/materials/m1/download" }],
      }))
      .mockResolvedValueOnce(new Response(new Blob(["source"]), { status: 200 }));
    vi.stubGlobal("URL", { createObjectURL: vi.fn(() => "blob:source"), revokeObjectURL: vi.fn() });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    const user = userEvent.setup();
    renderApp("/materials");
    await user.type(await screen.findByLabelText("问题"), "课程问题");
    await user.click(screen.getByRole("button", { name: "提交问题" }));
    await screen.findByRole("link", { name: "[S1]" });
    const [, , [, options]] = fetchMock.mock.calls;
    expect(JSON.parse(String(options?.body))).toEqual({ question: "课程问题", result_limit: 10, mode: "hybrid" });
    expect(String(options?.body)).not.toContain("class_id");
    const citation = screen.getByRole("link", { name: "[S1]" });
    expect(citation).toHaveAttribute("href", "#source-S1");
    await user.click(citation);
    expect(document.getElementById("source-S1")).toHaveFocus();
    await user.click(screen.getByRole("button", { name: /打开授权资料/ }));
    expect(fetchMock).toHaveBeenLastCalledWith("/api/materials/m1/download", {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(click).toHaveBeenCalled();
  });

  it("uploads one file with a Bearer header and returns to the library", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(teacher))
      .mockResolvedValueOnce(jsonResponse({ id: "material-2" }, 201))
      .mockResolvedValueOnce(jsonResponse([]));
    const user = userEvent.setup();
    renderApp("/materials/upload");
    await user.type(await screen.findByLabelText("Title"), "Lecture notes");
    await user.upload(screen.getByLabelText("File"), new File(["notes"], "notes.txt", { type: "text/plain" }));
    await user.click(screen.getByRole("button", { name: "上传资料" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    const [, options] = fetchMock.mock.calls[1] ?? [];
    expect(options).toEqual(expect.objectContaining({ method: "POST", headers: { Authorization: `Bearer ${token}` } }));
    expect(options?.body).toBeInstanceOf(FormData);
  });
});
