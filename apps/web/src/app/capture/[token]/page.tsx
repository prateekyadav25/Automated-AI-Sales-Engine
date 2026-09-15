"use client";

import { useParams } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

type Attribution = {
  utm_source: string;
  utm_medium: string;
  utm_campaign: string;
  campaign_id: string;
  ad_id: string;
};

export default function PublicCapturePage() {
  const params = useParams<{ token: string }>();
  const token = String(params.token || "");
  const [status, setStatus] = useState("");
  const [pending, setPending] = useState(false);
  const [attribution, setAttribution] = useState<Attribution>({
    utm_source: "",
    utm_medium: "",
    utm_campaign: "",
    campaign_id: "",
    ad_id: "",
  });

  useEffect(() => {
    const query = new URLSearchParams(window.location.search);
    setAttribution({
      utm_source: query.get("utm_source") || "",
      utm_medium: query.get("utm_medium") || "",
      utm_campaign: query.get("utm_campaign") || "",
      campaign_id: query.get("campaign_id") || "",
      ad_id: query.get("ad_id") || query.get("adid") || "",
    });
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setStatus("");
    const data = Object.fromEntries(new FormData(event.currentTarget).entries());
    const api = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
    const response = await fetch(`${api}/api/v1/public/forms/${token}/capture`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        first_name: data.first_name,
        last_name: data.last_name,
        email: data.email,
        company_name: data.company_name,
        consent_email: data.consent_email === "true",
        utm_source: attribution.utm_source,
        utm_medium: attribution.utm_medium,
        utm_campaign: attribution.utm_campaign,
        campaign_id: attribution.campaign_id || null,
        ad_id: attribution.ad_id,
      }),
    });
    setPending(false);
    setStatus(response.ok ? "Received. A human will follow only if you consented." : "This form could not be submitted.");
  }

  return (
    <main className="mx-auto max-w-md px-6 py-16">
      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-brand">Inbound</p>
      <h1 className="mt-3 text-2xl font-semibold text-navy">Talk to us</h1>
      <form className="mt-8 space-y-4" onSubmit={submit}>
        <label className="block text-sm">First name<input className="mt-1 w-full rounded-md border px-3 py-2" name="first_name" required /></label>
        <label className="block text-sm">Last name<input className="mt-1 w-full rounded-md border px-3 py-2" name="last_name" required /></label>
        <label className="block text-sm">Email<input className="mt-1 w-full rounded-md border px-3 py-2" name="email" type="email" required /></label>
        <label className="block text-sm">Company<input className="mt-1 w-full rounded-md border px-3 py-2" name="company_name" /></label>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" name="consent_email" value="true" /> I consent to email</label>
        <button className="w-full rounded-md bg-navy px-4 py-2 text-white" disabled={pending} type="submit">
          Submit
        </button>
      </form>
      {status ? <p className="mt-4 text-sm">{status}</p> : null}
    </main>
  );
}
