import { Navigate, useLocation } from "react-router-dom";
import type { ReactNode } from "react";

import { useAuth } from "@/lib/auth";

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-sm text-muted-foreground">Loading…</p>
      </div>
    );
  }

  if (!isAuthenticated) {
    // Carry where they were trying to go, so logging back in returns them
    // there instead of dumping them on the dashboard. `replace` keeps the
    // rejected URL out of history, so Back from /login doesn't bounce
    // straight through this redirect again.
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return <>{children}</>;
}
