"use client";

import { getApiBase } from "@agrayian/sdk";
import { useParams } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

type Attribution = {
  utm_source: string;
  utm_medium: string;
  utm_campaign: string;
  campaign_id: string;
  ad_id: string;
};

type PublicField = {
  key: string;
  label: string;
  type: "text" | "email" | "tel" | "textarea" | "checkbox" | "select";
  required: boolean;
  placeholder: string;
  options: string[];
};

const DEFAULT_FIELDS: PublicField[] = [
  { key: "first_name", label: "First name", type: "text", required: true, placeholder: "", options: [] },
  { key: "last_name", label: "Last name", type: "text", required: true, placeholder: "", options: [] },
  { key: "email", label: "Work email", type: "email", required: true, placeholder: "", options: [] },
  { key: "phone", label: "Phone", type: "tel", required: false, placeholder: "", options: [] },
  { key: "company_name", label: "Company", type: "text", required: false, placeholder: "", options: [] },
  { key: "title", label: "Role", type: "text", required: false, placeholder: "", options: [] },
  { key: "request_note", label: "What do you want?", type: "textarea", required: true, placeholder: "Describe what you want next.", options: [] },
  { key: "consent_email", label: "I agree to be contacted about this request.", type: "checkbox", required: true, placeholder: "", options: [] },
];

function isFieldType(value: string): value is PublicField["type"] {
  return value === "text" || value === "email" || value === "tel" || value === "textarea" || value === "checkbox" || value === "select";
}

function CaptureField({ field }: { field: PublicField }) {
  switch (field.type) {
    case "checkbox":
      return (
        <label className="ds-flex small muted">
          <input className="checkbox" type="checkbox" name={field.key} value="true" required={field.required} />
          {field.label}
        </label>
      );
    case "textarea":
      return (
        <label className="field">
          {field.label}
          <textarea name={field.key} required={field.required} rows={5} placeholder={field.placeholder} />
        </label>
      );
    case "select":
      return (
        <label className="field">
          {field.label}
          <select name={field.key} required={field.required}>
            <option value="">Select</option>
            {field.options.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
      );
    case "text":
    case "email":
    case "tel":
      return (
        <label className="field">
          {field.label}
          <input name={field.key} type={field.type} required={field.required} placeholder={field.placeholder} />
        </label>
      );
    default: {
      const exhaustive: never = field.type;
      return exhaustive;
    }
  }
}

export default function PublicCapturePage() {
  const params = useParams<{ token: string }>();
  const token = String(params.token || "");
  const [status, setStatus] = useState("");
  const [pending, setPending] = useState(false);
  const [heading, setHeading] = useState("Tell us what you need");
  const [fields, setFields] = useState<PublicField[]>(DEFAULT_FIELDS);
  const [attribution, setAttribution] = useState<Attribution>({
    utm_source: "",
    utm_medium: "",
    utm_campaign: "",
    campaign_id: "",
    ad_id: "",
  });

  useEffect(() => {
    if (!token) return;
    const api = getApiBase();
    void fetch(`${api}/api/v1/public/forms/${encodeURIComponent(token)}/meta`)
      .then(async (response) => {
        if (!response.ok) return;
        const body = (await response.json()) as { data?: { name?: string; fields?: PublicField[] } };
        const name = body.data?.name?.trim();
        if (name) setHeading(name);
        const designed = (body.data?.fields ?? []).filter((field) => field && isFieldType(field.type) && field.key && field.label);
        if (designed.length) setFields(designed);
      })
      .catch(() => undefined);
  }, [token]);

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
    const query = new URLSearchParams(window.location.search);
    const api = getApiBase();
    try {
      const response = await fetch(`${api}/api/v1/public/forms/${encodeURIComponent(token)}/capture`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          first_name: data.first_name,
          last_name: data.last_name,
          email: data.email,
          phone: data.phone,
          company_name: data.company_name,
          title: data.title,
          request_note: [
            data.request_note,
            ...fields
              .filter((field) => field.key.startsWith("custom_"))
              .map((field) => {
                const answer = String(data[field.key] || "").trim();
                return answer ? `${field.label}: ${answer}` : "";
              }),
          ]
            .filter(Boolean)
            .join("\n"),
          consent_email: data.consent_email === "true",
          source: query.get("source") || "public_form",
          channel: query.get("channel") || "website",
          utm_source: attribution.utm_source,
          utm_medium: attribution.utm_medium,
          utm_campaign: attribution.utm_campaign,
          campaign_id: attribution.campaign_id || null,
          ad_id: attribution.ad_id,
          ad: query.get("ad") || "",
          publication: query.get("publication") || "",
          growth: query.get("growth") || "",
        }),
      });
      setStatus(response.ok ? "Received. A human will follow only if you consented." : "This form could not be submitted.");
    } catch {
      setStatus("This form could not be submitted. Refresh the page and try again.");
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="capture-page">
      <section className="panel capture-card">
        <div className="public-brand">
          <span className="brand-mark"><i /><i /><i /></span>
          AGRAYIAN AI LABS
        </div>
        <div className="eyebrow">Inbound</div>
        <h1>{heading}</h1>
        <p className="muted" style={{ margin: "15px 0 26px" }}>
          Share a few details and what you want. A human follows only if you consent.
        </p>
        <form className="stack" onSubmit={submit}>
          {fields.map((field) => (
            <CaptureField key={field.key} field={field} />
          ))}
          <button className="btn primary" disabled={pending} type="submit">
            {pending ? "Submitting…" : "Submit request"}
          </button>
        </form>
        {status ? <p className="small" style={{ marginTop: 16 }}>{status}</p> : null}
      </section>
    </main>
  );
}
