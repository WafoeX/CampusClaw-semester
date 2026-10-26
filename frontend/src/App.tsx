import { Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, LoginPage, ProtectedRoute } from "./auth";
import { MaterialsLibrary, UploadPage } from "./materials";
import { AgentManagement } from "./agents";
import { McpManagement } from "./mcp";
import { McpAudits } from "./mcp-audits";
import { ConversationHome, ConversationPage, CreatorAuditPage } from "./conversations";

export function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/materials/upload" element={<ProtectedRoute><UploadPage /></ProtectedRoute>} />
        <Route path="/materials" element={<ProtectedRoute><MaterialsLibrary /></ProtectedRoute>} />
        <Route path="/mcp/audits" element={<ProtectedRoute><McpAudits /></ProtectedRoute>} />
        <Route path="/mcp" element={<ProtectedRoute><McpManagement /></ProtectedRoute>} />
        <Route path="/agents/manage" element={<ProtectedRoute><AgentManagement /></ProtectedRoute>} />
        <Route path="/conversations" element={<ProtectedRoute><ConversationHome /></ProtectedRoute>} />
        <Route path="/conversations/:conversationId" element={<ProtectedRoute><ConversationPage /></ProtectedRoute>} />
        <Route path="/agents/:agentId/audit" element={<ProtectedRoute><CreatorAuditPage /></ProtectedRoute>} />
        <Route path="/agents/:agentId/audit/:conversationId" element={<ProtectedRoute><CreatorAuditPage /></ProtectedRoute>} />
        <Route path="*" element={<Navigate to="/materials" replace />} />
      </Routes>
    </AuthProvider>
  );
}
