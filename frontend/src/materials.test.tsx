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
