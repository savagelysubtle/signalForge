import { useState } from "react";
import { Navigate } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { motion } from "motion/react";
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
      <div className="flex items-center justify-center h-screen bg-bg-void">
        <Loader2 className="w-8 h-8 animate-spin text-accent-signal" />
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
    <div className="min-h-screen bg-bg-void relative overflow-hidden">
      {/* Background layers */}
      <div className="absolute inset-0 bg-urban-finance pointer-events-none" />
      <div className="absolute inset-0 bg-grid-fade pointer-events-none" />
      <div className="absolute inset-0 bg-noise pointer-events-none" />
      {/* Radial glow behind form area */}
      <div className="absolute top-1/2 left-[30%] -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] glow-signal pointer-events-none opacity-50" />

      <div className="relative z-10 mx-auto grid min-h-screen max-w-7xl gap-10 px-6 py-8 lg:grid-cols-[minmax(0,420px)_minmax(0,1fr)] lg:items-center lg:px-8">
        <div className="mx-auto flex w-full max-w-sm flex-col justify-center">
          <motion.img
            initial={{ opacity: 0, y: -12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, ease: "easeOut" }}
            src={logoHorizontal}
            alt="SignalForge"
            className="mb-4 w-full max-w-[280px]"
          />
          <motion.p
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, ease: "easeOut", delay: 0.1 }}
            className="mb-8 text-sm text-text-secondary font-body"
          >
            Precision signals forged from market structure, sentiment, and AI
            synthesis.
          </motion.p>

          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, ease: "easeOut", delay: 0.2 }}
            className="glass-panel rounded-2xl p-6 shadow-2xl shadow-black/30"
          >
            <h2 className="mb-1 text-lg font-semibold text-text-primary font-display">
              {isSignUp ? "Create account" : "Sign in"}
            </h2>
            <p className="mb-6 text-sm text-text-secondary">
              {isSignUp
                ? "Enter your email to get started"
                : "Enter your credentials to continue"}
            </p>

            {signUpSuccess ? (
              <div className="rounded-lg border border-accent-profit/20 bg-accent-profit-dim p-4 text-sm text-accent-profit">
                Account created. Check your email to confirm, then sign in.
              </div>
            ) : (
              <form onSubmit={handleSubmit} className="space-y-4">
                {error && (
                  <div className="rounded-lg border border-accent-loss/20 bg-accent-loss-dim p-3 text-sm text-accent-loss">
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
                    className="w-full rounded-lg border border-border-gutter bg-bg-concrete px-3 py-2 text-sm text-text-primary placeholder-text-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-signal/50 focus-visible:border-accent-signal transition-colors"
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
                    className="w-full rounded-lg border border-border-gutter bg-bg-concrete px-3 py-2 text-sm text-text-primary placeholder-text-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-signal/50 focus-visible:border-accent-signal transition-colors"
                    placeholder="At least 6 characters"
                  />
                </div>

                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="flex w-full items-center justify-center gap-2 rounded-lg bg-accent-signal py-2.5 text-sm font-medium text-bg-void transition-all hover:brightness-110 disabled:opacity-50 font-display"
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
                className="text-sm text-accent-signal hover:underline transition-colors"
              >
                {isSignUp
                  ? "Already have an account? Sign in"
                  : "Need an account? Sign up"}
              </button>
            </div>
          </motion.div>
        </div>

        <motion.div
          initial={{ opacity: 0, scale: 0.97 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.7, ease: "easeOut", delay: 0.35 }}
          className="hidden lg:block"
        >
          <div className="overflow-hidden rounded-[28px] border border-border-subtle bg-bg-asphalt/60 p-4 shadow-2xl shadow-black/30">
            <img
              src={heroArtwork}
              alt="SignalForge brand hero showing forged market signals"
              className="w-full rounded-3xl border border-border-subtle/60 bg-bg-void"
            />
          </div>
        </motion.div>
      </div>
    </div>
  );
}
