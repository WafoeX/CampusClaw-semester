import { Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, LoginPage, ProtectedRoute } from "./auth";
import { MaterialsLibrary, UploadPage } from "./materials";

export function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/materials/upload" element={<ProtectedRoute><UploadPage /></ProtectedRoute>} />
        <Route path="/materials" element={<ProtectedRoute><MaterialsLibrary /></ProtectedRoute>} />
        <Route path="*" element={<Navigate to="/materials" replace />} />
      </Routes>
    </AuthProvider>
  );
}
