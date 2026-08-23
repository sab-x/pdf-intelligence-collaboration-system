import { Suspense, lazy } from "react";
import { Routes, Route } from "react-router-dom";
import LoginPage from "@/pages/Login";
import SignupPage from "@/pages/Signup";
import DashboardPage from "@/pages/Dashboard";
import { ProtectedRoute } from "@/components/ProtectedRoute";

/**
 * Code splitting, deliberately only on these two routes.
 *
 * Both pull in pdf.js and react-markdown, which together dominate the
 * bundle. Statically imported they were downloaded and parsed by every
 * visitor before login could even render — a first-time signup was paying
 * for a PDF renderer it would not touch for another minute.
 *
 * Login, signup and the dashboard stay eagerly loaded: they're small, the
 * dashboard is the destination immediately after auth, and splitting them
 * would add a network round trip to the most common path in the app for no
 * meaningful byte saving.
 */
const DocumentPage = lazy(() => import("@/pages/Document"));
const SharedDocumentPage = lazy(() => import("@/pages/SharedDocument"));

/**
 * Text, not a spinner. This shows for a few hundred milliseconds while the
 * viewer chunk downloads, and a spinner appearing-then-vanishing that fast
 * reads as a flicker rather than as progress.
 */
function RouteFallback() {
  return (
    <div className="flex min-h-dvh items-center justify-center">
      <p className="meta">Loading…</p>
    </div>
  );
}

export function AppRoutes() {
  return (
    <Suspense fallback={<RouteFallback />}>
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
    </Suspense>
  );
}
