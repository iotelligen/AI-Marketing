"use client";

import { useEffect, useState } from "react";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const WORKSPACES = [
  { slug: "iotelligen-marketing", label: "IoTelliGen Marketing" },
  { slug: "iotelligen", label: "IoTelliGen" },
];

type MarketingPost = {
  id: string;
  workspace_slug: string;
  topic: string;
  platform: string;
  target_audience?: string | null;
  objective?: string | null;
  language?: string;
  title: string;
  content: string;
  hashtags: string[];
  status: string;
  llm_model?: string;
  sources?: unknown[];
  caption_preview?: string;
  remote_post_id?: string | null;
  remote_url?: string | null;
  publish_error?: string | null;
  publish_metadata?: Record<string, unknown>;
  published_at?: string | null;
  created_at?: string;
  dry_run_default?: boolean;
  version_id?: string;
  version_number?: number;
  skills_used?: string[];
  publish_status?: string;
};

type PostForm = {
  topic: string;
  workspace: string;
  platform: string;
  target_audience: string;
  objective: string;
  language: string;
};

const EMPTY_FORM: PostForm = {
  topic: "Industrial motor condition monitoring using IoTelliGen gateway",
  workspace: WORKSPACES[0].slug,
  platform: "linkedin",
  target_audience: "Factory owners and maintenance managers",
  objective: "Generate awareness and leads",
  language: "English",
};

function errorMessage(err: unknown, fallback: string) {
  return err instanceof Error ? err.message : fallback;
}

function statusClass(status: string) {
  switch (status) {
    case "approved":
      return "bg-emerald-50 text-emerald-700";
    case "published":
      return "bg-sky-50 text-sky-700";
    case "dry_run":
      return "bg-amber-50 text-amber-700";
    case "draft":
      return "bg-slate-100 text-slate-600";
    default:
      return "bg-slate-100 text-slate-600";
  }
}

async function apiRequest(path: string, options: RequestInit = {}) {
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
    cache: "no-store",
  });

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

export default function MarketingPosts() {
  const [form, setForm] = useState<PostForm>(EMPTY_FORM);
  const [posts, setPosts] = useState<MarketingPost[]>([]);
  const [selected, setSelected] = useState<MarketingPost | null>(null);
  const [reviseInstructions, setReviseInstructions] = useState("");
  const [dryRunDefault, setDryRunDefault] = useState(true);
  const [loading, setLoading] = useState(true);
  const [generateBusy, setGenerateBusy] = useState(false);
  const [generatePublishBusy, setGeneratePublishBusy] = useState(false);
  const [reviseBusy, setReviseBusy] = useState(false);
  const [publishBusy, setPublishBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function loadPosts(selectId?: string) {
    try {
      const [listResult, platformsResult] = await Promise.all([
        apiRequest(
          `/marketing/posts?workspace=${encodeURIComponent(form.workspace)}&limit=20`
        ),
        apiRequest("/publish/platforms"),
      ]);

      const nextPosts = (listResult.posts ?? []) as MarketingPost[];
      setPosts(nextPosts);
      setDryRunDefault(
        Boolean(listResult.dry_run_default ?? platformsResult.dry_run_default)
      );

      if (selectId) {
        setSelected(
          nextPosts.find((post) => post.id === selectId) ?? nextPosts[0] ?? null
        );
      } else {
        setSelected((current) => {
          if (!current) return nextPosts[0] ?? null;
          return (
            nextPosts.find((post) => post.id === current.id) ??
            nextPosts[0] ??
            null
          );
        });
      }

      setError("");
    } catch (err) {
      setError(errorMessage(err, "Unable to load marketing posts."));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadPosts();
    // Reload when workspace filter changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.workspace]);

  async function generateOnly(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setGenerateBusy(true);
    setError("");
    setMessage("");

    try {
      const result = (await apiRequest("/marketing/posts/generate", {
        method: "POST",
        body: JSON.stringify(form),
      })) as MarketingPost;

      setSelected(result);
      setMessage(
        `Draft generated for ${result.platform}. Review it, revise if needed, then publish.`
      );
      await loadPosts(result.id);
    } catch (err) {
      setError(errorMessage(err, "Unable to generate post."));
    } finally {
      setGenerateBusy(false);
    }
  }

  async function generateAndPublish() {
    const confirmed = window.confirm(
      dryRunDefault
        ? "Generate a post and run a dry-run publish? Nothing will be posted to LinkedIn while PUBLISH_DRY_RUN is on."
        : "Generate a post and publish it live to LinkedIn now?"
    );

    if (!confirmed) return;

    setGeneratePublishBusy(true);
    setError("");
    setMessage("");

    try {
      const result = (await apiRequest("/marketing/posts/generate-and-publish", {
        method: "POST",
        body: JSON.stringify({
          ...form,
          requested_by: "dashboard",
        }),
      })) as MarketingPost;

      setSelected(result);

      if (result.status === "dry_run") {
        setMessage(
          `Post generated and dry-run published. Remote id: ${result.remote_post_id}. Nothing was posted to LinkedIn.`
        );
      } else if (result.status === "published") {
        setMessage(
          `Post generated and published to LinkedIn. Remote id: ${result.remote_post_id}.`
        );
      } else if (result.publish_error) {
        setMessage(
          `Post generated, but publish failed: ${result.publish_error}`
        );
      } else {
        setMessage(`Post generated with status: ${result.status}`);
      }

      await loadPosts(result.id);
    } catch (err) {
      setError(errorMessage(err, "Unable to generate and publish post."));
    } finally {
      setGeneratePublishBusy(false);
    }
  }

  async function reviseSelected() {
    if (!selected) return;

    setReviseBusy(true);
    setError("");
    setMessage("");

    try {
      const result = await apiRequest(`/marketing/posts/${selected.id}/revise`, {
        method: "POST",
        body: JSON.stringify({ instructions: reviseInstructions }),
      });

      setReviseInstructions("");
      setMessage(`Revision saved as version ${result.version_number}.`);
      await loadPosts(selected.id);
    } catch (err) {
      setError(errorMessage(err, "Unable to revise post."));
    } finally {
      setReviseBusy(false);
    }
  }

  async function publishSelected() {
    if (!selected) return;

    const confirmed = window.confirm(
      dryRunDefault
        ? "Publish this post in dry-run mode? Nothing will be posted to LinkedIn."
        : "Publish this post live to LinkedIn now?"
    );

    if (!confirmed) return;

    setPublishBusy(true);
    setError("");
    setMessage("");

    try {
      const result = (await apiRequest(
        `/marketing/posts/${selected.id}/publish`,
        {
          method: "POST",
          body: JSON.stringify({
            auto_approve: true,
            requested_by: "dashboard",
          }),
        }
      )) as MarketingPost;

      setSelected(result);

      if (result.status === "dry_run") {
        setMessage(
          `Dry-run publish completed. Remote id: ${result.remote_post_id}.`
        );
      } else if (result.status === "published") {
        setMessage(
          `Published to LinkedIn. Remote id: ${result.remote_post_id}.`
        );
      } else if (result.publish_error) {
        setMessage(`Publish failed: ${result.publish_error}`);
      } else {
        setMessage(`Publish finished with status: ${result.status}`);
      }

      await loadPosts(result.id);
    } catch (err) {
      setError(errorMessage(err, "Unable to publish post."));
    } finally {
      setPublishBusy(false);
    }
  }

  const canRevise = selected?.status === "draft";
  const canPublish =
    selected &&
    ["draft", "approved"].includes(selected.status);

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-[#E5EAF0] bg-white p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">
              Marketing posts
            </h2>
            <p className="mt-1 text-sm text-slate-500">
              Generate LinkedIn copy from your knowledge base, then publish it
              through the same LinkedIn accounts used for videos.
            </p>
          </div>
          <div className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">
            Publish mode:{" "}
            <span className="font-semibold">
              {dryRunDefault ? "dry-run (safe)" : "LIVE"}
            </span>
          </div>
        </div>
      </div>

      {(error || message) && (
        <div
          className={`rounded-xl border px-4 py-3 text-sm ${
            error
              ? "border-rose-200 bg-rose-50 text-rose-700"
              : "border-emerald-200 bg-emerald-50 text-emerald-700"
          }`}
        >
          {error || message}
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-[0.95fr_1.05fr]">
        <section className="rounded-xl border border-[#E5EAF0] bg-white p-6">
          <h3 className="font-semibold text-slate-900">Generate a post</h3>
          <p className="mt-1 text-sm text-slate-500">
            Create a draft to review, or generate and publish in one step.
          </p>

          <form onSubmit={generateOnly} className="mt-5 space-y-4">
            <label className="block">
              <span className="mb-2 block text-sm font-medium text-slate-700">
                Topic
              </span>
              <textarea
                required
                rows={3}
                value={form.topic}
                onChange={(e) => setForm({ ...form, topic: e.target.value })}
                className="form-input"
                placeholder="What should this post cover?"
              />
            </label>

            <div className="grid gap-4 sm:grid-cols-2">
              <label className="block">
                <span className="mb-2 block text-sm font-medium text-slate-700">
                  Workspace
                </span>
                <select
                  value={form.workspace}
                  onChange={(e) =>
                    setForm({ ...form, workspace: e.target.value })
                  }
                  className="form-input"
                >
                  {WORKSPACES.map((workspace) => (
                    <option key={workspace.slug} value={workspace.slug}>
                      {workspace.label}
                    </option>
                  ))}
                </select>
              </label>

              <label className="block">
                <span className="mb-2 block text-sm font-medium text-slate-700">
                  Platform
                </span>
                <select
                  value={form.platform}
                  onChange={(e) =>
                    setForm({ ...form, platform: e.target.value })
                  }
                  className="form-input"
                >
                  <option value="linkedin">LinkedIn</option>
                </select>
              </label>
            </div>

            <label className="block">
              <span className="mb-2 block text-sm font-medium text-slate-700">
                Target audience
              </span>
              <input
                value={form.target_audience}
                onChange={(e) =>
                  setForm({ ...form, target_audience: e.target.value })
                }
                className="form-input"
              />
            </label>

            <label className="block">
              <span className="mb-2 block text-sm font-medium text-slate-700">
                Objective
              </span>
              <input
                value={form.objective}
                onChange={(e) =>
                  setForm({ ...form, objective: e.target.value })
                }
                className="form-input"
              />
            </label>

            <div className="flex flex-wrap gap-3 pt-1">
              <button
                type="submit"
                disabled={generateBusy || generatePublishBusy}
                className="rounded-lg bg-[#119A78] px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-[#0e8266] disabled:opacity-60"
              >
                {generateBusy ? "Generating..." : "Generate draft"}
              </button>
              <button
                type="button"
                disabled={generateBusy || generatePublishBusy}
                onClick={() => void generateAndPublish()}
                className="rounded-lg border border-[#119A78] px-4 py-2.5 text-sm font-semibold text-[#119A78] transition hover:bg-emerald-50 disabled:opacity-60"
              >
                {generatePublishBusy
                  ? "Generating & publishing..."
                  : dryRunDefault
                    ? "Generate + dry-run publish"
                    : "Generate + publish live"}
              </button>
            </div>
          </form>
        </section>

        <section className="rounded-xl border border-[#E5EAF0] bg-white p-6">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h3 className="font-semibold text-slate-900">Selected post</h3>
              <p className="mt-1 text-sm text-slate-500">
                Review copy, revise the draft, then publish.
              </p>
            </div>
            {selected && (
              <span
                className={`rounded-full px-2.5 py-1 text-xs font-semibold capitalize ${statusClass(selected.status)}`}
              >
                {selected.status.replace("_", " ")}
              </span>
            )}
          </div>

          {!selected ? (
            <p className="mt-8 text-sm text-slate-500">
              {loading
                ? "Loading posts..."
                : "Generate a draft to preview it here."}
            </p>
          ) : (
            <div className="mt-5 space-y-4">
              <div>
                <div className="text-xs uppercase tracking-wide text-slate-400">
                  Title
                </div>
                <h4 className="mt-1 text-base font-semibold text-slate-900">
                  {selected.title}
                </h4>
              </div>

              <div className="whitespace-pre-wrap rounded-lg border border-slate-100 bg-slate-50 p-4 text-sm leading-6 text-slate-700">
                {selected.content}
              </div>

              {selected.hashtags?.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {selected.hashtags.map((tag) => (
                    <span
                      key={tag}
                      className="rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-600"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              )}

              {selected.publish_error && (
                <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
                  {selected.publish_error}
                </div>
              )}

              {selected.remote_post_id && (
                <div className="text-xs text-slate-500">
                  Remote post id: {selected.remote_post_id}
                </div>
              )}

              {canRevise && (
                <div className="space-y-3 border-t border-slate-100 pt-4">
                  <label className="block">
                    <span className="mb-2 block text-sm font-medium text-slate-700">
                      Revision instructions
                    </span>
                    <textarea
                      rows={3}
                      value={reviseInstructions}
                      onChange={(e) => setReviseInstructions(e.target.value)}
                      className="form-input"
                      placeholder="Make it shorter and more practical for plant managers..."
                    />
                  </label>
                  <button
                    type="button"
                    disabled={reviseBusy || reviseInstructions.trim().length < 3}
                    onClick={() => void reviseSelected()}
                    className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:opacity-60"
                  >
                    {reviseBusy ? "Revising..." : "Revise draft"}
                  </button>
                </div>
              )}

              {canPublish && (
                <div className="border-t border-slate-100 pt-4">
                  <button
                    type="button"
                    disabled={publishBusy}
                    onClick={() => void publishSelected()}
                    className="rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:opacity-60"
                  >
                    {publishBusy
                      ? "Publishing..."
                      : dryRunDefault
                        ? "Approve & dry-run publish"
                        : "Approve & publish live"}
                  </button>
                </div>
              )}
            </div>
          )}
        </section>
      </div>

      <section className="rounded-xl border border-[#E5EAF0] bg-white p-6">
        <h3 className="font-semibold text-slate-900">Recent posts</h3>
        <p className="mt-1 text-sm text-slate-500">
          Drafts and publish attempts for the selected workspace.
        </p>

        <div className="mt-4 overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="border-b border-slate-100 text-xs uppercase tracking-wide text-slate-400">
              <tr>
                <th className="px-2 py-2 font-medium">Title</th>
                <th className="px-2 py-2 font-medium">Platform</th>
                <th className="px-2 py-2 font-medium">Status</th>
                <th className="px-2 py-2 font-medium">Created</th>
              </tr>
            </thead>
            <tbody>
              {posts.length === 0 ? (
                <tr>
                  <td
                    colSpan={4}
                    className="px-2 py-6 text-center text-slate-500"
                  >
                    {loading ? "Loading..." : "No posts yet for this workspace."}
                  </td>
                </tr>
              ) : (
                posts.map((post) => (
                  <tr
                    key={post.id}
                    className={`cursor-pointer border-b border-slate-50 transition hover:bg-slate-50 ${
                      selected?.id === post.id ? "bg-emerald-50/40" : ""
                    }`}
                    onClick={() => setSelected(post)}
                  >
                    <td className="px-2 py-3 font-medium text-slate-800">
                      {post.title}
                    </td>
                    <td className="px-2 py-3 capitalize text-slate-600">
                      {post.platform}
                    </td>
                    <td className="px-2 py-3">
                      <span
                        className={`rounded-full px-2 py-0.5 text-xs font-semibold capitalize ${statusClass(post.status)}`}
                      >
                        {post.status.replace("_", " ")}
                      </span>
                    </td>
                    <td className="px-2 py-3 text-slate-500">
                      {post.created_at
                        ? new Date(post.created_at).toLocaleString(undefined, {
                            dateStyle: "medium",
                            timeStyle: "short",
                          })
                        : "—"}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
