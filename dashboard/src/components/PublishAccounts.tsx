"use client";

import { useEffect, useState } from "react";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const WORKSPACES = [
  { slug: "iotelligen-marketing", label: "IoTelliGen Marketing" },
  { slug: "iotelligen", label: "IoTelliGen" },
];

type PublishAccount = {
  account_id: string;
  workspace_slug: string;
  platform: string;
  display_name: string;
  status: string;
  has_access_token: boolean;
  has_author_urn: boolean;
  author_urn?: string | null;
  last_verified_at?: string | null;
  created_at?: string;
  updated_at?: string;
};

type AccountForm = {
  workspace_slug: string;
  platform: "linkedin";
  display_name: string;
  access_token: string;
  author_urn: string;
};

const EMPTY_FORM: AccountForm = {
  workspace_slug: WORKSPACES[0].slug,
  platform: "linkedin",
  display_name: "IoTelliGen LinkedIn",
  access_token: "",
  author_urn: "",
};

function errorMessage(err: unknown, fallback: string) {
  return err instanceof Error ? err.message : fallback;
}

async function readJson(response: Response) {
  const result = await response.json().catch(() => null);

  if (!response.ok) {
    const detail = result?.detail;

    if (typeof detail === "string") {
      throw new Error(detail);
    }

    if (Array.isArray(detail)) {
      throw new Error(
        detail
          .map((item) => item?.msg)
          .filter(Boolean)
          .join("; ") || `Request failed: HTTP ${response.status}`
      );
    }

    throw new Error(`Request failed: HTTP ${response.status}`);
  }

  return result;
}

export default function PublishAccounts() {
  const [accounts, setAccounts] = useState<PublishAccount[]>([]);
  const [form, setForm] = useState<AccountForm>(EMPTY_FORM);
  const [dryRunDefault, setDryRunDefault] = useState(true);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function load() {
    try {
      const [accountsResult, platformsResult] = await Promise.all([
        readJson(
          await fetch(`${API_URL}/publish/accounts?platform=linkedin`, {
            cache: "no-store",
          })
        ),
        readJson(
          await fetch(`${API_URL}/publish/platforms`, {
            cache: "no-store",
          })
        ),
      ]);

      setAccounts(accountsResult.accounts ?? []);
      setDryRunDefault(Boolean(platformsResult.dry_run_default));
      setError("");
    } catch (err) {
      setError(errorMessage(err, "Unable to load publish accounts."));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function saveAccount(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");
    setMessage("");

    try {
      await readJson(
        await fetch(`${API_URL}/publish/accounts`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(form),
        })
      );

      setForm({
        ...EMPTY_FORM,
        workspace_slug: form.workspace_slug,
        display_name: form.display_name,
      });
      setMessage(
        "LinkedIn account saved. Tokens are stored for local development only."
      );
      await load();
    } catch (err) {
      setError(errorMessage(err, "Unable to save the LinkedIn account."));
    } finally {
      setSaving(false);
    }
  }

  async function disableAccount(accountId: string) {
    setBusyId(accountId);
    setError("");
    setMessage("");

    try {
      await readJson(
        await fetch(`${API_URL}/publish/accounts/${accountId}`, {
          method: "DELETE",
        })
      );
      setMessage("Account disabled.");
      await load();
    } catch (err) {
      setError(errorMessage(err, "Unable to disable the account."));
    } finally {
      setBusyId(null);
    }
  }

  const activeAccounts = accounts.filter(
    (account) => account.status === "active"
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

      <section className="rounded-xl border border-[#E5EAF0] bg-white p-6">
        <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">
              Publishing
            </h2>
            <p className="mt-1 text-sm text-slate-500">
              Store LinkedIn credentials used by FastAPI when n8n or the
              dashboard requests a publish. Dry-run is{" "}
              <strong>{dryRunDefault ? "ON" : "OFF"}</strong> in the API.
            </p>
          </div>
          <span
            className={`w-fit rounded-full px-3 py-1 text-xs font-medium ${
              dryRunDefault
                ? "bg-amber-50 text-amber-700"
                : "bg-emerald-50 text-emerald-700"
            }`}
          >
            {dryRunDefault ? "Dry-run default" : "Live publishing enabled"}
          </span>
        </div>
      </section>

      <div className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
        <section className="rounded-xl border border-[#E5EAF0] bg-white p-6">
          <h2 className="text-lg font-semibold text-slate-900">
            Add LinkedIn account
          </h2>
          <p className="mt-1 text-sm text-slate-500">
            Paste an access token and the author URN for a person or company
            page. Example: <code>urn:li:organization:123456</code>
          </p>

          <form onSubmit={saveAccount} className="mt-6 space-y-4">
            <Field label="Workspace">
              <select
                value={form.workspace_slug}
                onChange={(e) =>
                  setForm({ ...form, workspace_slug: e.target.value })
                }
                className="form-input"
              >
                {WORKSPACES.map((item) => (
                  <option key={item.slug} value={item.slug}>
                    {item.label}
                  </option>
                ))}
              </select>
            </Field>

            <Field label="Display name">
              <input
                required
                maxLength={200}
                value={form.display_name}
                onChange={(e) =>
                  setForm({ ...form, display_name: e.target.value })
                }
                className="form-input"
              />
            </Field>

            <Field label="Author URN">
              <input
                required
                maxLength={200}
                placeholder="urn:li:organization:123456"
                value={form.author_urn}
                onChange={(e) =>
                  setForm({ ...form, author_urn: e.target.value })
                }
                className="form-input"
              />
            </Field>

            <Field label="Access token">
              <textarea
                required
                rows={4}
                minLength={10}
                value={form.access_token}
                onChange={(e) =>
                  setForm({ ...form, access_token: e.target.value })
                }
                className="form-input font-mono text-xs"
                placeholder="LinkedIn OAuth access token"
              />
            </Field>

            <p className="text-xs text-slate-500">
              Tokens are stored as plain JSON in Postgres for local use.
              Do not use this outside a trusted machine.
            </p>

            <button
              type="submit"
              disabled={saving}
              className="w-full rounded-lg bg-[#13A982] px-5 py-3 text-sm font-semibold text-white transition hover:bg-[#0f9270] disabled:opacity-60"
            >
              {saving ? "Saving..." : "Save LinkedIn account"}
            </button>
          </form>
        </section>

        <section className="rounded-xl border border-[#E5EAF0] bg-white p-6">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-slate-900">
                Saved accounts
              </h2>
              <p className="mt-1 text-sm text-slate-500">
                Active accounts are used for live LinkedIn publishing.
              </p>
            </div>
            <button
              type="button"
              onClick={() => {
                setLoading(true);
                void load();
              }}
              className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-medium text-slate-600 hover:bg-slate-50"
            >
              Refresh
            </button>
          </div>

          {loading ? (
            <p className="mt-6 text-sm text-slate-400">Loading accounts...</p>
          ) : accounts.length === 0 ? (
            <p className="mt-6 rounded-lg bg-slate-50 p-6 text-sm text-slate-500">
              No LinkedIn accounts saved yet.
            </p>
          ) : (
            <div className="mt-5 space-y-3">
              {accounts.map((account) => (
                <article
                  key={account.account_id}
                  className="rounded-xl border border-slate-200 p-4"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-semibold text-slate-800">
                        {account.display_name}
                      </div>
                      <div className="mt-1 text-xs text-slate-500">
                        {account.workspace_slug} · {account.platform}
                      </div>
                    </div>
                    <span
                      className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${
                        account.status === "active"
                          ? "bg-emerald-50 text-emerald-700"
                          : "bg-slate-100 text-slate-500"
                      }`}
                    >
                      {account.status}
                    </span>
                  </div>

                  <div className="mt-3 break-all text-xs text-slate-500">
                    {account.author_urn || "No author URN"}
                  </div>
                  <div className="mt-1 text-xs text-slate-400">
                    Access token:{" "}
                    {account.has_access_token ? "saved" : "missing"}
                  </div>

                  {account.status === "active" && (
                    <button
                      type="button"
                      disabled={busyId === account.account_id}
                      onClick={() => void disableAccount(account.account_id)}
                      className="mt-4 rounded-lg border border-slate-200 px-3 py-2 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-60"
                    >
                      {busyId === account.account_id
                        ? "Disabling..."
                        : "Disable"}
                    </button>
                  )}
                </article>
              ))}
            </div>
          )}

          <div className="mt-5 rounded-lg bg-slate-50 p-4 text-xs text-slate-500">
            Active LinkedIn accounts:{" "}
            <strong className="text-slate-700">{activeAccounts.length}</strong>
            . With dry-run ON, publish requests never call LinkedIn even if an
            account is saved.
          </div>
        </section>
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
