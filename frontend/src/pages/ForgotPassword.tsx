import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { AuthLayout } from "@/components/AuthLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export default function ForgotPasswordPage() {
  const { forgotPassword } = useAuth();

  const [email, setEmail] = useState("");
  const [emailError, setEmailError] = useState<string | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  // Set once the request succeeds, and never cleared — this screen has no
  // reason to return to the form after that, and doing so would invite a
  // second submission that just restarts the rate limit for no benefit.
  const [sentMessage, setSentMessage] = useState<string | null>(null);

  function validate(): boolean {
    const trimmed = email.trim();
    if (!trimmed) {
      setEmailError("Email is required.");
      return false;
    }
    if (!EMAIL_RE.test(trimmed)) {
      setEmailError("Enter a valid email address.");
      return false;
    }
    setEmailError(null);
    return true;
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setApiError(null);
    if (!validate()) return;

    setIsSubmitting(true);
    try {
      const message = await forgotPassword(email.trim());
      setSentMessage(message);
    } catch (err) {
      setApiError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <AuthLayout>
      <p className="meta mb-3 text-white/40">Reset password</p>
      <Card className="w-full border-white/10 shadow-2xl shadow-black/40 ring-1 ring-white/10">
        <CardHeader>
          <CardTitle className="font-display text-3xl font-normal tracking-tight">
            Forgot your password?
          </CardTitle>
          <CardDescription>
            Enter the email on your account and we'll send you a link to reset it.
          </CardDescription>
        </CardHeader>
        {sentMessage ? (
          <CardContent className="space-y-4">
            <p className="rounded-md border border-white/10 bg-white/5 px-3 py-2 text-sm text-white/80">
              {sentMessage}
            </p>
            <Link
              to="/login"
              className="inline-block text-sm font-medium text-foreground underline underline-offset-4"
            >
              Back to login
            </Link>
          </CardContent>
        ) : (
          <form onSubmit={handleSubmit} noValidate>
            <CardContent className="space-y-4">
              {apiError && (
                <p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
                  {apiError}
                </p>
              )}
              <div className="space-y-2">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  type="email"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  aria-invalid={Boolean(emailError)}
                />
                {emailError && <p className="text-sm text-destructive">{emailError}</p>}
              </div>
            </CardContent>
            <CardFooter className="flex flex-col gap-4">
              <Button type="submit" className="w-full" disabled={isSubmitting}>
                {isSubmitting ? "Sending…" : "Send reset link"}
              </Button>
              <p className="text-sm text-muted-foreground">
                Remembered it?{" "}
                <Link to="/login" className="font-medium text-foreground underline underline-offset-4">
                  Log in
                </Link>
              </p>
            </CardFooter>
          </form>
        )}
      </Card>
    </AuthLayout>
  );
}
