"use client";

import { GlassMotif } from "@/components/glass-motif";
import { Button, Field, Input } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

export default function LoginPage() {
  const { login } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("admin@agrayian.demo");
  const [password, setPassword] = useState("Agrarian!Demo1");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError("");
    try {
      await login(email, password);
      router.replace("/");
    } catch {
      setError("Those credentials were declined.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <section className="relative hidden overflow-hidden bg-navy p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="pointer-events-none absolute inset-0">
          <div className="absolute -left-16 -top-16 h-72 w-72 rounded-full bg-azure-600/40 blur-3xl" />
          <div className="absolute bottom-8 right-0 h-80 w-80 rounded-full bg-brand/30 blur-3xl" />
          <GlassMotif tone="dark" className="absolute right-0 top-24 w-[520px] opacity-80" />
        </div>
        <div className="relative">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-sky-200">AGRAYIAN AI Labs</p>
          <p className="mt-2 text-sm text-slate-300">Revenue operating system</p>
        </div>
        <div className="relative">
          <h1 className="max-w-lg text-4xl font-semibold leading-tight">
            Run the full revenue lifecycle in one workspace.
          </h1>
          <p className="mt-5 max-w-md text-sm leading-7 text-slate-300">
            Find accounts, run campaigns, coach deals, and keep customers. Humans own the relationship. The system keeps the rhythm.
          </p>
          <div className="mt-10 grid grid-cols-3 gap-4 text-sm">
            {[
              ["01", "Acquire"],
              ["02", "Close"],
              ["03", "Expand"],
            ].map(([step, label]) => (
              <div key={step} className="rounded-xl border border-white/15 bg-white/10 px-3 py-3 backdrop-blur-md">
                <p className="text-xs text-sky-200">{step}</p>
                <p className="mt-1 font-medium">{label}</p>
              </div>
            ))}
          </div>
        </div>
        <p className="relative text-xs text-slate-400">Private preview · tenant-isolated</p>
      </section>
      <section className="relative flex items-center justify-center p-8">
        <form onSubmit={onSubmit} className="glass-strong relative w-full max-w-md rounded-2xl p-8 shadow-lift">
          <p className="text-xs font-semibold uppercase tracking-wide text-azure-600">Sign in</p>
          <h1 className="mt-1 text-2xl font-semibold text-navy">Welcome back</h1>
          <p className="mt-1 text-sm text-[var(--muted)]">Use your workspace credentials to continue.</p>
          <div className="mt-8 space-y-4">
            <Field label="Email">
              <Input value={email} onChange={(e) => setEmail(e.target.value)} />
            </Field>
            <Field label="Password">
              <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
            </Field>
          </div>
          {error ? <p className="mt-4 text-sm text-rose-700">{error}</p> : null}
          <Button disabled={pending} className="mt-8 w-full">
            {pending ? "Signing in…" : "Sign in"}
          </Button>
        </form>
      </section>
    </div>
  );
}
