import { useState } from "react";
import { useAuth } from "../../context/AuthContext";
import { Navigate } from "react-router-dom";
import { Loader2, Zap } from "lucide-react";

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
    <div className="flex items-center justify-center min-h-screen bg-bg-primary">
      <div className="w-full max-w-sm">
        <div className="flex items-center justify-center gap-2 mb-8">
          <Zap className="w-8 h-8 text-accent-blue" />
          <h1 className="text-3xl font-bold text-text-primary">SignalForge</h1>
        </div>

        <div className="bg-bg-secondary border border-border rounded-lg p-6">
          <h2 className="text-lg font-semibold text-text-primary mb-1">
            {isSignUp ? "Create account" : "Sign in"}
          </h2>
          <p className="text-sm text-text-secondary mb-6">
            {isSignUp
              ? "Enter your email to get started"
              : "Enter your credentials to continue"}
          </p>

          {signUpSuccess ? (
            <div className="bg-accent-green/10 text-accent-green p-4 rounded-lg border border-accent-green/20 text-sm">
              Account created. Check your email to confirm, then sign in.
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              {error && (
                <div className="bg-accent-red/10 text-accent-red p-3 rounded-lg border border-accent-red/20 text-sm">
                  {error}
                </div>
              )}

              <div>
                <label
                  htmlFor="email"
                  className="block text-sm font-medium text-text-secondary mb-1.5"
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
                  className="w-full px-3 py-2 bg-bg-tertiary border border-border rounded-lg text-text-primary placeholder-text-secondary focus:outline-none focus:ring-2 focus:ring-accent-blue/50 focus:border-accent-blue text-sm"
                  placeholder="you@example.com"
                />
              </div>

              <div>
                <label
                  htmlFor="password"
                  className="block text-sm font-medium text-text-secondary mb-1.5"
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
                  className="w-full px-3 py-2 bg-bg-tertiary border border-border rounded-lg text-text-primary placeholder-text-secondary focus:outline-none focus:ring-2 focus:ring-accent-blue/50 focus:border-accent-blue text-sm"
                  placeholder="At least 6 characters"
                />
              </div>

              <button
                type="submit"
                disabled={isSubmitting}
                className="w-full py-2.5 bg-accent-blue hover:bg-accent-blue/90 text-white font-medium rounded-lg text-sm transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
              >
                {isSubmitting && (
                  <Loader2 className="w-4 h-4 animate-spin" />
                )}
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
    </div>
  );
}
