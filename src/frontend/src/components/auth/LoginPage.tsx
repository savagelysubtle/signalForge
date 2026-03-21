import { useState } from "react";
import { Navigate } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { useAuth } from "../../context/AuthContext";
import heroArtwork from "../../assets/signalforge-hero.svg";
import logoHorizontal from "../../assets/signalforge-logo-horizontal.svg";

export function LoginPage() {
  const { user, isLoading: authLoading, signIn, signUp } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isSignUp, setIsSignUp] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [signUpSuccess, setSignUpSuccess] = useState(false);

  if (authLoading) {
    return (
      <div className="flex items-center justify-center h-screen bg-bg-primary">
        <Loader2 className="w-8 h-8 animate-spin text-accent-blue" />
      </div>
    );
  }

  if (user) {
    return <Navigate to="/" replace />;
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);

    const result = isSignUp
      ? await signUp(email, password)
      : await signIn(email, password);

    setIsSubmitting(false);

    if (result) {
      setError(result);
    } else if (isSignUp) {
      setSignUpSuccess(true);
    }
  };

  return (
    <div className="min-h-screen bg-bg-primary">
      <div className="mx-auto grid min-h-screen max-w-7xl gap-10 px-6 py-8 lg:grid-cols-[minmax(0,420px)_minmax(0,1fr)] lg:items-center lg:px-8">
        <div className="mx-auto flex w-full max-w-sm flex-col justify-center">
          <img
            src={logoHorizontal}
            alt="SignalForge"
            className="mb-4 w-full max-w-[280px]"
          />
          <p className="mb-8 text-sm text-text-secondary">
            Precision signals forged from market structure, sentiment, and AI
            synthesis.
          </p>

          <div className="rounded-2xl border border-border bg-bg-secondary p-6 shadow-lg shadow-black/20">
            <h2 className="mb-1 text-lg font-semibold text-text-primary">
              {isSignUp ? "Create account" : "Sign in"}
            </h2>
            <p className="mb-6 text-sm text-text-secondary">
              {isSignUp
                ? "Enter your email to get started"
                : "Enter your credentials to continue"}
            </p>

            {signUpSuccess ? (
              <div className="rounded-lg border border-accent-green/20 bg-accent-green/10 p-4 text-sm text-accent-green">
                Account created. Check your email to confirm, then sign in.
              </div>
            ) : (
              <form onSubmit={handleSubmit} className="space-y-4">
                {error && (
                  <div className="rounded-lg border border-accent-red/20 bg-accent-red/10 p-3 text-sm text-accent-red">
                    {error}
                  </div>
                )}

                <div>
                  <label
                    htmlFor="email"
                    className="mb-1.5 block text-sm font-medium text-text-secondary"
                  >
                    Email
                  </label>
                  <input
                    id="email"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    autoComplete="email"
                    className="w-full rounded-lg border border-border bg-bg-tertiary px-3 py-2 text-sm text-text-primary placeholder-text-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-blue/50 focus-visible:border-accent-blue"
                    placeholder="you@example.com"
                  />
                </div>

                <div>
                  <label
                    htmlFor="password"
                    className="mb-1.5 block text-sm font-medium text-text-secondary"
                  >
                    Password
                  </label>
                  <input
                    id="password"
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    minLength={6}
                    autoComplete={isSignUp ? "new-password" : "current-password"}
                    className="w-full rounded-lg border border-border bg-bg-tertiary px-3 py-2 text-sm text-text-primary placeholder-text-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-blue/50 focus-visible:border-accent-blue"
                    placeholder="At least 6 characters"
                  />
                </div>

                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="flex w-full items-center justify-center gap-2 rounded-lg bg-accent-blue py-2.5 text-sm font-medium text-white transition-colors hover:bg-accent-blue/90 disabled:opacity-50"
                >
                  {isSubmitting && <Loader2 className="h-4 w-4 animate-spin" />}
                  {isSignUp ? "Create account" : "Sign in"}
                </button>
              </form>
            )}

            <div className="mt-4 text-center">
              <button
                onClick={() => {
                  setIsSignUp(!isSignUp);
                  setError(null);
                  setSignUpSuccess(false);
                }}
                className="text-sm text-accent-blue hover:underline"
              >
                {isSignUp
                  ? "Already have an account? Sign in"
                  : "Need an account? Sign up"}
              </button>
            </div>
          </div>
        </div>

        <div className="hidden lg:block">
          <div className="overflow-hidden rounded-[28px] border border-border bg-bg-secondary/60 p-4 shadow-2xl shadow-black/20">
            <img
              src={heroArtwork}
              alt="SignalForge brand hero showing forged market signals"
              className="w-full rounded-3xl border border-border/60 bg-bg-primary"
            />
          </div>
        </div>
      </div>
    </div>
  );
}
