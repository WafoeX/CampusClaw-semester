import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";

const identity = {
  user_id: "user-1",
  account: "teacher.alpha",
  role: "teacher" as const,
  class_id: "class-1",
  csrf_token: "csrf-1",
  expires_at: "2030-01-01T00:00:00Z",
};

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function renderApp(path = "/materials") {
  return render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>);
}

afterEach(() => vi.restoreAllMocks());

describe("authentication flow", () => {
  it("redirects an unauthenticated protected route to login with a return target", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(response({ detail: "unauthenticated" }, 401));
    renderApp("/materials?tab=recent");
    expect(await screen.findByRole("heading", { name: /sign in/i })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/");
    expect(screen.getByLabelText("Account")).toBeInTheDocument();
  });

  it("logs in, returns to the protected route, and keeps csrf only in memory", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response({ detail: "unauthenticated" }, 401))
      .mockResolvedValueOnce(response(identity));
    const user = userEvent.setup();
    renderApp("/login?returnTo=%2Fmaterials");
    await user.type(await screen.findByLabelText("Account"), "teacher.alpha");
    await user.type(screen.getByLabelText("Password"), "secret");
    await user.click(screen.getByRole("button", { name: "登录" }));
    expect(await screen.findByText(/teacher\.alpha/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/auth/login", expect.objectContaining({ method: "POST" }));
    expect(screen.queryByText("csrf-1")).not.toBeInTheDocument();
  });

  it("shows a generic login failure", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response({ detail: "unauthenticated" }, 401))
      .mockResolvedValueOnce(response({ detail: { message: "Invalid account or password" } }, 401));
    const user = userEvent.setup();
    renderApp("/login");
    await user.type(await screen.findByLabelText("Account"), "unknown");
    await user.type(screen.getByLabelText("Password"), "wrong");
    await user.click(screen.getByRole("button", { name: "登录" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid account or password");
  });

  it("logs out with csrf and same-origin headers", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response(identity))
      .mockResolvedValueOnce(response([]))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    const user = userEvent.setup();
    renderApp("/materials");
    expect(await screen.findByText(/teacher\.alpha/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "退出登录" }));
    await waitFor(() => expect(screen.getByRole("heading", { name: /sign in/i })).toBeInTheDocument());
    const logoutCall = fetchMock.mock.calls.find(([url]) => url === "/api/auth/logout");
    expect(logoutCall?.[0]).toBe("/api/auth/logout");
    expect(logoutCall?.[1]).toEqual(expect.objectContaining({
      headers: { Origin: window.location.origin, "x-csrf-token": "csrf-1" },
    }));
  });
});
