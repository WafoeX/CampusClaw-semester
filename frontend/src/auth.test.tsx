import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";

const identity = { user_id: "user-1", account: "teacher.alpha", role: "teacher" as const, class_id: "class-1" };
const loginResponse = { ...identity, access_token: "header.payload.signature", token_type: "bearer" as const, expires_at: "2030-01-01T00:00:00Z" };

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function renderApp(path = "/materials") {
  return render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>);
}

beforeEach(() => window.localStorage.clear());
afterEach(() => vi.restoreAllMocks());

describe("authentication flow", () => {
  it("redirects an unauthenticated protected route to login with a return target", async () => {
    renderApp("/materials?tab=recent");
    expect(await screen.findByRole("heading", { name: /sign in/i })).toBeInTheDocument();
  });

  it("stores login token and sends it when navigating to a protected route", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response(loginResponse))
      .mockResolvedValueOnce(response([]));
    const user = userEvent.setup();
    renderApp("/login?returnTo=%2Fmaterials");
    await user.type(await screen.findByLabelText("Account"), "teacher.alpha");
    await user.type(screen.getByLabelText("Password"), "secret");
    await user.click(screen.getByRole("button", { name: "登录" }));
    expect(await screen.findByText(/teacher\.alpha/)).toBeInTheDocument();
    expect(window.localStorage.getItem("campusclaw.access-token")).toBe(loginResponse.access_token);
    await waitFor(() => expect(fetchMock).toHaveBeenLastCalledWith("/api/materials", { headers: { Authorization: `Bearer ${loginResponse.access_token}` } }));
  });

  it("restores a persisted token through the identity API", async () => {
    window.localStorage.setItem("campusclaw.access-token", loginResponse.access_token);
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response(identity))
      .mockResolvedValueOnce(response([]));
    renderApp("/materials");
    expect(await screen.findByText(/teacher\.alpha/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/auth/me", { headers: { Authorization: `Bearer ${loginResponse.access_token}` } });
  });

  it("shows a generic login failure", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(response({ detail: { message: "Invalid account or password" } }, 401));
    const user = userEvent.setup();
    renderApp("/login");
    await user.type(await screen.findByLabelText("Account"), "unknown");
    await user.type(screen.getByLabelText("Password"), "wrong");
    await user.click(screen.getByRole("button", { name: "登录" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid account or password");
  });

  it("clears the local token on logout", async () => {
    window.localStorage.setItem("campusclaw.access-token", loginResponse.access_token);
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response(identity))
      .mockResolvedValueOnce(response([]))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    const user = userEvent.setup();
    renderApp("/materials");
    await user.click(await screen.findByRole("button", { name: "退出登录" }));
    await waitFor(() => expect(screen.getByRole("heading", { name: /sign in/i })).toBeInTheDocument());
    expect(window.localStorage.getItem("campusclaw.access-token")).toBeNull();
    expect(fetchMock).toHaveBeenLastCalledWith("/api/auth/logout", { method: "POST", headers: { Authorization: `Bearer ${loginResponse.access_token}` } });
  });
});
