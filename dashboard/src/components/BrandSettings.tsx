"use client";

import { useEffect, useRef, useState } from "react";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const WORKSPACES = [
  { slug: "iotelligen-marketing", label: "IoTelliGen Marketing" },
  { slug: "iotelligen", label: "IoTelliGen" },
];

const DEFAULT_ACCENT_COLOR = "#16C79A";

type BrandProfile = {
  workspace: string;
  configured: boolean;
  brand_name: string;
  tagline: string | null;
  accent_color: string;
  website: string | null;
  email: string | null;
  phone: string | null;
  has_logo: boolean;
  logo_filename: string | null;
  logo_url: string | null;
};

type BrandForm = {
  brand_name: string;
  tagline: string;
  accent_color: string;
  website: string;
  email: string;
  phone: string;
};

const EMPTY_FORM: BrandForm = {
  brand_name: "",
  tagline: "",
  accent_color: DEFAULT_ACCENT_COLOR,
  website: "",
  email: "",
  phone: "",
};

function toForm(profile: BrandProfile): BrandForm {
  return {
    brand_name: profile.brand_name,
    tagline: profile.tagline ?? "",
    accent_color: profile.accent_color,
    website: profile.website ?? "",
    email: profile.email ?? "",
    phone: profile.phone ?? "",
  };
}

async function readBrand(response: Response): Promise<BrandProfile> {
  const result = await response.json().catch(() => null);

  if (!response.ok) {
    const detail = result?.detail;

    if (typeof detail === "string") {
      throw new Error(detail);
    }

    // FastAPI reports field validation errors as a list.
    if (Array.isArray(detail)) {
      throw new Error(
        detail
          .map((item) => item?.msg)
          .filter(Boolean)
          .join("; ") || "The brand details are not valid."
      );
    }

    throw new Error(`Request failed: HTTP ${response.status}`);
  }

  return result as BrandProfile;
}

function errorMessage(err: unknown, fallback: string) {
  return err instanceof Error ? err.message : fallback;
}

export default function BrandSettings() {
  const [workspace, setWorkspace] = useState(WORKSPACES[0].slug);
  const [profile, setProfile] = useState<BrandProfile | null>(null);
  const [form, setForm] = useState<BrandForm>(EMPTY_FORM);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [logoBusy, setLogoBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const data = await readBrand(
          await fetch(`${API_URL}/workspaces/${workspace}/brand`, {
            cache: "no-store",
          })
        );

        if (cancelled) return;

        setProfile(data);
        setForm(toForm(data));
        setError("");
      } catch (err) {
        if (cancelled) return;

        setProfile(null);
        setError(errorMessage(err, "Unable to load the brand profile."));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void load();

    return () => {
      cancelled = true;
    };
  }, [workspace]);

  function changeWorkspace(slug: string) {
    setLoading(true);
    setMessage("");
    setError("");
    setWorkspace(slug);
  }

  async function saveProfile(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");
    setMessage("");

    try {
      const data = await readBrand(
        await fetch(`${API_URL}/workspaces/${workspace}/brand`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(form),
        })
      );

      setProfile(data);
      setForm(toForm(data));
      setMessage("Brand profile saved. New renders will use it.");
    } catch (err) {
      setError(errorMessage(err, "Unable to save the brand profile."));
    } finally {
      setSaving(false);
    }
  }

  // Logo changes update the stored profile only, so text the user has
  // typed but not yet saved stays in the form.
  async function uploadLogo(file: File) {
    setLogoBusy(true);
    setError("");
    setMessage("");

    try {
      const body = new FormData();
      body.append("file", file);

      const data = await readBrand(
        await fetch(`${API_URL}/workspaces/${workspace}/brand/logo`, {
          method: "POST",
          body,
        })
      );

      setProfile(data);
      setMessage("Logo uploaded. New renders will use it.");
    } catch (err) {
      setError(errorMessage(err, "Unable to upload the logo."));
    } finally {
      setLogoBusy(false);

      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function removeLogo() {
    setLogoBusy(true);
    setError("");
    setMessage("");

    try {
      const data = await readBrand(
        await fetch(`${API_URL}/workspaces/${workspace}/brand/logo`, {
          method: "DELETE",
        })
      );

      setProfile(data);
      setMessage("Logo removed.");
    } catch (err) {
      setError(errorMessage(err, "Unable to remove the logo."));
    } finally {
      setLogoBusy(false);
    }
  }

  const logoSrc = profile?.logo_url ? `${API_URL}${profile.logo_url}` : null;

  const accentColor = /^#[0-9a-fA-F]{6}$/.test(form.accent_color)
    ? form.accent_color
    : DEFAULT_ACCENT_COLOR;

  const contactLines = [form.website, form.phone, form.email].filter(
    (line) => line.trim() !== ""
  );

  return (
    <div className="space-y-6">
      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {message && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">
          {message}
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
        <section className="rounded-xl border border-[#E5EAF0] bg-white p-6">
          <h2 className="text-lg font-semibold text-slate-900">
            Brand profile
          </h2>
          <p className="mt-1 text-sm text-slate-500">
            The renderer draws these details onto every video. They are
            never written by an AI agent or drawn by an image model.
          </p>

          <form onSubmit={saveProfile} className="mt-6 space-y-4">
            <Field label="Workspace">
              <select
                value={workspace}
                onChange={(e) => changeWorkspace(e.target.value)}
                className="form-input"
              >
                {WORKSPACES.map((item) => (
                  <option key={item.slug} value={item.slug}>
                    {item.label}
                  </option>
                ))}
              </select>
            </Field>

            <Field label="Brand name">
              <input
                required
                maxLength={150}
                value={form.brand_name}
                onChange={(e) =>
                  setForm({ ...form, brand_name: e.target.value })
                }
                className="form-input"
              />
            </Field>

            <Field label="Tagline (optional)">
              <input
                maxLength={200}
                value={form.tagline}
                onChange={(e) => setForm({ ...form, tagline: e.target.value })}
                className="form-input"
              />
            </Field>

            <Field label="Accent colour">
              <div className="flex items-center gap-3">
                <input
                  type="color"
                  aria-label="Pick accent colour"
                  value={accentColor}
                  onChange={(e) =>
                    setForm({ ...form, accent_color: e.target.value })
                  }
                  className="h-11 w-14 cursor-pointer rounded-lg border border-slate-200 bg-white p-1"
                />
                <input
                  aria-label="Accent colour hex value"
                  pattern="#[0-9a-fA-F]{6}"
                  title="Six-digit hex colour, for example #16C79A"
                  value={form.accent_color}
                  onChange={(e) =>
                    setForm({ ...form, accent_color: e.target.value })
                  }
                  className="form-input"
                />
              </div>
            </Field>

            <div className="border-t border-slate-100 pt-4">
              <div className="text-sm font-semibold text-slate-800">
                Contact details
              </div>
              <p className="mt-1 text-xs text-slate-500">
                Shown on the end card of each video. Leave a field empty to
                hide it.
              </p>
            </div>

            <Field label="Website">
              <input
                maxLength={200}
                value={form.website}
                onChange={(e) => setForm({ ...form, website: e.target.value })}
                className="form-input"
              />
            </Field>

            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Phone">
                <input
                  maxLength={50}
                  value={form.phone}
                  onChange={(e) => setForm({ ...form, phone: e.target.value })}
                  className="form-input"
                />
              </Field>

              <Field label="Email">
                <input
                  type="email"
                  maxLength={200}
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                  className="form-input"
                />
              </Field>
            </div>

            <button
              type="submit"
              disabled={loading || saving || !profile}
              className="w-full rounded-lg bg-[#13A982] px-5 py-3 text-sm font-semibold text-white transition hover:bg-[#0f9270] disabled:opacity-60"
            >
              {saving ? "Saving..." : "Save brand profile"}
            </button>
          </form>
        </section>

        <div className="space-y-6">
          <section className="rounded-xl border border-[#E5EAF0] bg-white p-6">
            <h2 className="text-lg font-semibold text-slate-900">Logo</h2>
            <p className="mt-1 text-sm text-slate-500">
              Shown in the corner of every scene and on the end card. PNG,
              JPEG or WebP, up to 5 MB. A PNG with a transparent background
              works best.
            </p>

            <div className="mt-5 flex min-h-[120px] items-center justify-center rounded-lg border border-dashed border-slate-200 bg-slate-50 p-5">
              {logoSrc ? (
                <img
                  src={logoSrc}
                  alt={`${form.brand_name || "Brand"} logo`}
                  className="max-h-24 max-w-full object-contain"
                />
              ) : (
                <span className="text-sm text-slate-400">
                  {loading ? "Loading..." : "No logo uploaded"}
                </span>
              )}
            </div>

            {profile?.logo_filename && (
              <div className="mt-2 break-all text-xs text-slate-400">
                {profile.logo_filename}
              </div>
            )}

            <input
              ref={fileInputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void uploadLogo(file);
              }}
            />

            <div className="mt-4 flex flex-wrap gap-3">
              <button
                type="button"
                disabled={loading || logoBusy || !profile}
                onClick={() => fileInputRef.current?.click()}
                className="rounded-lg bg-[#172033] px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-60"
              >
                {logoBusy
                  ? "Working..."
                  : logoSrc
                    ? "Replace logo"
                    : "Upload logo"}
              </button>

              {logoSrc && (
                <button
                  type="button"
                  disabled={logoBusy}
                  onClick={() => void removeLogo()}
                  className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-60"
                >
                  Remove
                </button>
              )}
            </div>
          </section>

          <section className="rounded-xl border border-[#E5EAF0] bg-white p-6">
            <h2 className="text-lg font-semibold text-slate-900">
              End card preview
            </h2>
            <p className="mt-1 text-sm text-slate-500">
              An approximation of the last scene. The call to action comes
              from each video&apos;s script.
            </p>

            <div className="mt-5 flex flex-col items-center rounded-xl bg-[#071522] px-6 py-10 text-center text-white">
              {logoSrc ? (
                <div className="rounded-xl bg-white/95 px-5 py-3">
                  <img
                    src={logoSrc}
                    alt=""
                    className="max-h-16 max-w-[220px] object-contain"
                  />
                </div>
              ) : (
                <div className="text-3xl font-extrabold">
                  {form.brand_name || "Brand name"}
                </div>
              )}

              {form.tagline.trim() !== "" && (
                <div className="mt-4 text-sm text-white/80">
                  {form.tagline}
                </div>
              )}

              <div className="mt-4 text-xl font-extrabold">
                Call to action
              </div>

              <div
                className="mt-4 h-1 w-12 rounded-full"
                style={{ backgroundColor: accentColor }}
              />

              {contactLines.length > 0 && (
                <div className="mt-4 space-y-1 text-sm font-semibold">
                  {contactLines.map((line) => (
                    <div key={line} className="break-all">
                      {line}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-2 block text-sm font-medium text-slate-700">
        {label}
      </span>
      {children}
    </label>
  );
}
