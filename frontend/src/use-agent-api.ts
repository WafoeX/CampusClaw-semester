import { useMemo } from "react";
import { useAuth } from "./auth";
import { createAgentApi } from "./agent-api";

export function useAgentApi() {
  const { authorizationHeader, handleUnauthenticated } = useAuth();
  return useMemo(() => createAgentApi({ authorizationHeader, handleUnauthenticated }), [authorizationHeader, handleUnauthenticated]);
}
