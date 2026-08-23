import { Routes, Route } from "react-router-dom";
import LoginPage from "@/pages/Login";
import SignupPage from "@/pages/Signup";
import DashboardPage from "@/pages/Dashboard";
import DocumentPage from "@/pages/Document";
import SharedDocumentPage from "@/pages/SharedDocument";
import { ProtectedRoute } from "@/components/ProtectedRoute";

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<SignupPage />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <DashboardPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/documents/:id"
        element={
          <ProtectedRoute>
            <DocumentPage />
          </ProtectedRoute>
        }
      />
      {/* Public by design: guest share links carry their own token (§4). */}
      <Route path="/share/:token" element={<SharedDocumentPage />} />
    </Routes>
  );
}
