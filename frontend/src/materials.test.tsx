import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";

const teacher = {
  user_id: "teacher-1",
  account: "teacher.alpha",
  role: "teacher" as const,
  class_id: "class-1",
  csrf_token: "csrf-1",
  expires_at: "2030-01-01T00:00:00Z",
};

const student = { ...teacher, user_id: "student-1", account: "student.alpha", role: "student" as const };

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function renderApp(path: string) {
  return render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>);
}

afterEach(() => vi.restoreAllMocks());

describe("material library", () => {
  it("shows class materials and a download action to a teacher", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(teacher))
      .mockResolvedValueOnce(jsonResponse([{
        id: "material-1",
        title: "Week one",
        original_filename: "week-one.pdf",
        content_type: "application/pdf",
        byte_size: 2048,
        sha256: "a".repeat(64),
        uploader_id: "teacher-1",
        created_at: "2030-01-01T00:00:00Z",
      }]));

    renderApp("/materials");

    expect(await screen.findByRole("heading", { name: "Week one" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /下载文件/ })).toHaveAttribute(
      "href",
      "/api/materials/material-1/download",
    );
    expect(screen.getByRole("link", { name: "上传资料" })).toBeInTheDocument();
  });

  it("does not offer upload controls to students", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(student))
      .mockResolvedValueOnce(jsonResponse([]));

    renderApp("/materials");

    expect(await screen.findByRole("heading", { name: /teaching materials/i })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "上传资料" })).not.toBeInTheDocument();
  });

  it("uploads one file with csrf and returns to the refreshed library", async () => {
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
    expect(options).toEqual(expect.objectContaining({ method: "POST" }));
    expect(options?.headers).toEqual({ Origin: window.location.origin, "x-csrf-token": "csrf-1" });
    expect(options?.body).toBeInstanceOf(FormData);
    expect((options?.body as FormData).get("title")).toBe("Lecture notes");
    expect((options?.body as FormData).get("file")).toBeInstanceOf(File);
  });
});
