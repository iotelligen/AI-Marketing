"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import AssetGallery from "@/components/AssetGallery";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type VideoJob = {
  id: string;
  title: string;
  prompt?: string | null;
  workspace_slug: string;
  template_id: string;
  status: string;
  progress: number;
  renderer_job_id?: string | null;
  output_file?: string | null;
  error_message?: string | null;
  created_at: string;
  updated_at?: string;
};

type VideoVersion = {
  id: string;
  job_id: string;
  version_number: number;
  filename: string;
  duration_seconds?: number;
  width?: number;
  height?: number;
  fps?: number;
  status: string;
};

type VideoScene = {
  scene_number: number;
  duration_seconds: number;
  purpose: string;
  narration: string;
  visual_prompt: string;
  on_screen_text: string;
  transition: "cut" | "fade" | "slide" | "zoom" | "dissolve";
};

type VideoPlan = {
  concept: string;
  title: string;
  duration_seconds: number;
  aspect_ratio: "9:16" | "16:9" | "1:1";
  language: string;
  target_audience: string;
  objective: string;
  cta: string;
  scenes: VideoScene[];
};


const navigation = [
  { label: "Overview", icon: "◫" },
  { label: "Video Studio", icon: "▣" },
  { label: "Video Library", icon: "▤" },
  { label: "Marketing", icon: "◈" },
  { label: "Knowledge Base", icon: "▧" },
  { label: "Workflows", icon: "⌘" },
];

function statusColor(status: string) {
  switch (status) {
    case "completed":
      return "bg-emerald-50 text-emerald-700";
    case "failed":
      return "bg-red-50 text-red-700";
    case "rendering":
    case "active":
      return "bg-blue-50 text-blue-700";
    default:
      return "bg-amber-50 text-amber-700";
  }
}

function formatDate(value: string) {
  if (!value) return "—";

  return new Date(value).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export default function Home() {
  const [jobs, setJobs] = useState<VideoJob[]>([]);
  const [selectedJob, setSelectedJob] = useState<VideoJob | null>(null);
  const [versions, setVersions] = useState<VideoVersion[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const [activeSection, setActiveSection] = useState("Overview");

  const [form, setForm] = useState({
    topic: "Industrial motor condition monitoring using IoTelliGen gateway",
    workspace: "iotelligen-marketing",
    platform: "linkedin",
    target_audience: "Factory owners and maintenance managers",
    objective: "Generate awareness and leads",
    language: "English",
    duration_seconds: 30,
    aspect_ratio: "9:16" as "9:16" | "16:9" | "1:1",
    tone: "Professional and engaging",
    additional_instructions: "",
  });
  const [videoPlan, setVideoPlan] = useState<VideoPlan | null>(null);
  const [planBusy, setPlanBusy] = useState(false);
  const [draftBusy, setDraftBusy] = useState(false);
  const [assetBusy, setAssetBusy] = useState(false);
  const [renderBusy, setRenderBusy] = useState(false);
  const [workflowMessage, setWorkflowMessage] = useState("");

const pollingRef = useRef(false);

const loadJobs = useCallback(async () => {
  if (pollingRef.current) return;

  pollingRef.current = true;

  try {
    const response = await fetch(`${API_URL}/videos/jobs?limit=100`, {
      cache: "no-store",
    });

    if (!response.ok) {
      throw new Error(`API returned HTTP ${response.status}`);
    }

    const data: VideoJob[] = await response.json();

    // Synchronize active jobs with the Remotion renderer.
    const updatedJobs = await Promise.all(
      data.map(async (job) => {
        const active = [
          "queued",
          "submitting",
          "rendering",
        ].includes(job.status);

        if (!active) return job;

        try {
          const statusResponse = await fetch(
            `${API_URL}/videos/jobs/${job.id}`,
            { cache: "no-store" }
          );

          if (!statusResponse.ok) return job;

          return (await statusResponse.json()) as VideoJob;
        } catch {
          return job;
        }
      })
    );

    setJobs(updatedJobs);

    setSelectedJob((current) => {
      if (current) {
        return updatedJobs.find(
          (job) => job.id === current.id
        ) ?? current;
      }

      return (
        updatedJobs.find((job) => job.status === "completed") ??
        updatedJobs[0] ??
        null
      );
    });

    setError("");
  } catch (err) {
    setError(
      err instanceof Error
        ? err.message
        : "Unable to connect to the FastAPI backend."
    );
  } finally {
    setLoading(false);
    pollingRef.current = false;
  }
}, []);


  const loadVersions = useCallback(async (jobId: string) => {
    try {
      const response = await fetch(
        `${API_URL}/videos/jobs/${jobId}/versions`,
        { cache: "no-store" }
      );

      if (!response.ok) {
        setVersions([]);
        return;
      }

      setVersions(await response.json());
    } catch {
      setVersions([]);
    }
  }, []);

  useEffect(() => {
    void loadJobs();

    const interval = window.setInterval(() => {
      void loadJobs();
    }, 5000);

    return () => window.clearInterval(interval);
  }, [loadJobs]);

  useEffect(() => {
  if (selectedJob?.status === "completed") {
    void loadVersions(selectedJob.id);
  } else {
    setVersions([]);
  }
}, [selectedJob?.id, selectedJob?.status, loadVersions]);

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
      const detail =
        typeof result?.detail === "string"
          ? result.detail
          : result?.detail
            ? JSON.stringify(result.detail)
            : `Request failed: HTTP ${response.status}`;
      throw new Error(detail);
    }
    return result;
  }

  async function generateStoryboard(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPlanBusy(true);
    setError("");
    setWorkflowMessage("");
    try {
      const result = await apiRequest("/videos/plan", {
        method: "POST",
        body: JSON.stringify({
          topic: form.topic,
          workspace_slug: form.workspace,
          platform: form.platform,
          target_audience: form.target_audience,
          objective: form.objective,
          language: form.language,
          duration_seconds: Number(form.duration_seconds),
          aspect_ratio: form.aspect_ratio,
          tone: form.tone,
          additional_instructions: form.additional_instructions || null,
        }),
      });
      setVideoPlan(result.plan as VideoPlan);
      setWorkflowMessage(
        `Storyboard generated with ${result.plan.scenes.length} scenes. Review it and save it as a draft.`
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Storyboard generation failed.");
    } finally {
      setPlanBusy(false);
    }
  }

  async function saveDraft() {
    if (!videoPlan) return;
    setDraftBusy(true);
    setError("");
    setWorkflowMessage("");
    try {
      const result = await apiRequest("/videos/jobs/from-plan", {
        method: "POST",
        body: JSON.stringify({
          workspace_slug: form.workspace,
          prompt: form.topic,
          plan: videoPlan,
        }),
      });
      const response = await fetch(`${API_URL}/videos/jobs/${result.job_id}`, {
        cache: "no-store",
      });
      const savedJob = response.ok ? ((await response.json()) as VideoJob) : null;
      await loadJobs();
      if (savedJob) setSelectedJob(savedJob);
      setWorkflowMessage(
        `Draft saved. Job ID: ${result.job_id}. You can now generate scene images.`
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save draft.");
    } finally {
      setDraftBusy(false);
    }
  }

  async function generateSceneAssets() {
    if (!selectedJob) {
      setError("Save the storyboard as a draft before generating scene images.");
      return;
    }
    setAssetBusy(true);
    setError("");
    setWorkflowMessage("");
    try {
      const result = await apiRequest(
        `/videos/jobs/${selectedJob.id}/assets/generate-from-plan`,
        { method: "POST" }
      );
      await loadJobs();
      setWorkflowMessage(
        `Scene image generation submitted. ${result.scene_count ?? ""} scenes processed. Review the generated assets below.`
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Image generation request failed.");
    } finally {
      setAssetBusy(false);
    }
  }

  async function renderApprovedVideo() {
    if (!selectedJob) {
      setError("Select or save a draft video job first.");
      return;
    }
    setRenderBusy(true);
    setError("");
    setWorkflowMessage("");
    try {
      const result = await apiRequest(
        `/videos/jobs/${selectedJob.id}/render`,
        { method: "POST" }
      );
      const response = await fetch(`${API_URL}/videos/jobs/${selectedJob.id}`, {
        cache: "no-store",
      });
      if (response.ok) setSelectedJob(await response.json());
      await loadJobs();
      setWorkflowMessage(
        `Render submitted successfully. Renderer job: ${result.renderer_job_id}.`
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Video rendering failed to start.");
    } finally {
      setRenderBusy(false);
    }
  }

  function updateScene<K extends keyof VideoScene>(
    sceneNumber: number,
    field: K,
    value: VideoScene[K]
  ) {
    setVideoPlan((current) => {
      if (!current) return current;
      return {
        ...current,
        scenes: current.scenes.map((scene) =>
          scene.scene_number === sceneNumber
            ? { ...scene, [field]: value }
            : scene
        ),
      };
    });
  }

  const completedJobs = jobs.filter(
    (job) => job.status === "completed"
  ).length;

  const activeJobs = jobs.filter(
    (job) => ["queued", "submitting", "rendering"].includes(job.status)
  ).length;

  const failedJobs = jobs.filter(
    (job) => job.status === "failed"
  ).length;

  const videoUrl = selectedJob
    ? `${API_URL}/videos/jobs/${selectedJob.id}/video`
    : null;

  return (
    <div className="min-h-screen lg:flex">
      {/* Sidebar */}
      <aside className="flex w-full flex-col bg-[#172033] text-white lg:fixed lg:inset-y-0 lg:w-[250px]">
        <div className="flex h-[76px] items-center gap-3 border-b border-white/10 px-6">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#16C79A] text-xl font-bold text-[#102B27]">
            I
          </div>

          <div>
            <div className="text-base font-semibold tracking-wide">
              IoTelliGen
            </div>
            <div className="text-xs text-slate-400">AI Studio</div>
          </div>
        </div>

        <div className="px-4 py-6">
          <div className="mb-3 px-3 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">
            Workspace
          </div>

          <nav className="space-y-1">
            {navigation.map((item) => {
              const active = activeSection === item.label;

              return (
                <button
                  key={item.label}
                  onClick={() => setActiveSection(item.label)}
                  className={`flex w-full items-center gap-3 rounded-lg px-3 py-3 text-left text-sm transition ${
                    active
                      ? "bg-[#16C79A]/15 text-[#51E0B6]"
                      : "text-slate-300 hover:bg-white/5 hover:text-white"
                  }`}
                >
                  <span className="w-5 text-center text-lg">{item.icon}</span>
                  {item.label}
                </button>
              );
            })}
          </nav>
        </div>

        <div className="mt-auto hidden border-t border-white/10 p-5 lg:block">
          <div className="rounded-xl bg-white/5 p-4">
            <div className="mb-2 text-xs font-semibold text-white">
              Platform status
            </div>
            <div className="flex items-center gap-2 text-xs text-emerald-400">
              <span className="h-2 w-2 rounded-full bg-emerald-400" />
              API connection monitored
            </div>
            <div className="mt-2 text-[11px] text-slate-500">
              Local development environment
            </div>
          </div>
        </div>
      </aside>

      {/* Main content */}
      <main className="min-w-0 flex-1 lg:ml-[250px]">
        {/* Top bar */}
        <header className="flex h-[76px] items-center justify-between border-b border-[#E5EAF0] bg-white px-5 sm:px-8">
          <div>
            <div className="text-sm font-semibold text-slate-800">
              AI Automation Platform
            </div>
            <div className="text-xs text-slate-400">
              IoTelliGen workspace
            </div>
          </div>

          <div className="flex items-center gap-3">
            <div className="hidden items-center gap-2 rounded-full bg-emerald-50 px-3 py-2 text-xs font-medium text-emerald-700 sm:flex">
              <span className="h-2 w-2 rounded-full bg-emerald-500" />
              Development
            </div>

            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-[#172033] text-sm font-semibold text-white">
              I
            </div>
          </div>
        </header>

        <div className="mx-auto max-w-[1500px] space-y-7 p-5 sm:p-8">
          {/* Page heading */}
          <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
            <div>
              <div className="text-xs font-semibold uppercase tracking-wider text-[#13A982]">
                Workspace / {activeSection}
              </div>
              <h1 className="mt-2 text-2xl font-semibold tracking-tight text-slate-900">
                {activeSection}
              </h1>
              <p className="mt-1 text-sm text-slate-500">
                Manage your AI-generated content and automation.
              </p>
            </div>

            <button
              onClick={() => setActiveSection("Video Studio")}
              className="rounded-lg bg-[#13A982] px-5 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-[#0f9270]"
            >
              + Create video
            </button>
          </div>

          {/* Error */}
          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
              <strong>Backend connection or request error:</strong> {error}
              <div className="mt-1 text-xs">
                API address: {API_URL}
              </div>
            </div>
          )}

          {/* Overview */}
          {activeSection === "Overview" && (
            <>
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                {[
                  {
                    label: "Total videos",
                    value: jobs.length,
                    icon: "▣",
                    color: "text-blue-600 bg-blue-50",
                  },
                  {
                    label: "Completed",
                    value: completedJobs,
                    icon: "✓",
                    color: "text-emerald-600 bg-emerald-50",
                  },
                  {
                    label: "Rendering / Queued",
                    value: activeJobs,
                    icon: "◷",
                    color: "text-amber-600 bg-amber-50",
                  },
                  {
                    label: "Failed",
                    value: failedJobs,
                    icon: "!",
                    color: "text-red-600 bg-red-50",
                  },
                ].map((item) => (
                  <div
                    key={item.label}
                    className="rounded-xl border border-[#E5EAF0] bg-white p-5"
                  >
                    <div className="flex items-center justify-between">
                      <div className="text-sm text-slate-500">
                        {item.label}
                      </div>
                      <div
                        className={`flex h-9 w-9 items-center justify-center rounded-lg text-lg font-semibold ${item.color}`}
                      >
                        {item.icon}
                      </div>
                    </div>
                    <div className="mt-4 text-3xl font-semibold text-slate-900">
                      {loading ? "—" : item.value}
                    </div>
                  </div>
                ))}
              </div>

              <div className="grid gap-6 xl:grid-cols-[1.5fr_1fr]">
                <section className="rounded-xl border border-[#E5EAF0] bg-white p-5">
                  <div className="mb-5 flex items-center justify-between">
                    <div>
                      <h2 className="font-semibold text-slate-900">
                        Recent videos
                      </h2>
                      <p className="mt-1 text-xs text-slate-500">
                        Latest video generation jobs
                      </p>
                    </div>

                    <button
                      onClick={() => setActiveSection("Video Library")}
                      className="text-xs font-semibold text-[#119A78]"
                    >
                      View all
                    </button>
                  </div>

                  <JobTable
                    jobs={jobs.slice(0, 6)}
                    loading={loading}
                    selectedId={selectedJob?.id}
                    onSelect={setSelectedJob}
                  />
                </section>

                <section className="rounded-xl border border-[#E5EAF0] bg-white p-5">
                  <h2 className="font-semibold text-slate-900">
                    Quick actions
                  </h2>
                  <p className="mt-1 text-xs text-slate-500">
                    Start a new automation task
                  </p>

                  <div className="mt-5 space-y-3">
                    <QuickAction
                      icon="▣"
                      title="Generate a video"
                      description="Create an industrial promotional video"
                      onClick={() => setActiveSection("Video Studio")}
                    />
                    <QuickAction
                      icon="◈"
                      title="Marketing content"
                      description="Use the Marketing Agent"
                      onClick={() => setActiveSection("Marketing")}
                    />
                    <QuickAction
                      icon="▧"
                      title="Knowledge base"
                      description="Manage company documents"
                      onClick={() => setActiveSection("Knowledge Base")}
                    />
                    <QuickAction
                      icon="⌘"
                      title="Workflow automation"
                      description="Manage n8n workflows"
                      onClick={() => setActiveSection("Workflows")}
                    />
                  </div>
                </section>
              </div>

              <VideoPreview
                job={selectedJob}
                videoUrl={videoUrl}
                versions={versions}
              />
            </>
          )}

          {/* Video Studio */}
          {activeSection === "Video Studio" && (
            <div className="space-y-6">
              <div className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
                <section className="rounded-xl border border-[#E5EAF0] bg-white p-6">
                  <h2 className="text-lg font-semibold text-slate-900">Create an AI video</h2>
                  <p className="mt-1 text-sm text-slate-500">
                    Generate a storyboard, review scene prompts, then create and approve images.
                  </p>

                  <form onSubmit={generateStoryboard} className="mt-6 space-y-4">
                    <FormField label="Video topic">
                      <textarea required rows={3} value={form.topic}
                        onChange={(e) => setForm({ ...form, topic: e.target.value })}
                        className="form-input" placeholder="Describe the video you want to create" />
                    </FormField>
                    <FormField label="Platform">
                      <select value={form.platform}
                        onChange={(e) => setForm({ ...form, platform: e.target.value })}
                        className="form-input">
                        <option value="linkedin">LinkedIn</option>
                        <option value="facebook">Facebook</option>
                        <option value="instagram">Instagram</option>
                        <option value="youtube">YouTube</option>
                        <option value="tiktok">TikTok</option>
                      </select>
                    </FormField>
                    <div className="grid gap-4 sm:grid-cols-2">
                      <FormField label="Duration (seconds)">
                        <input type="number" min={10} max={180} value={form.duration_seconds}
                          onChange={(e) => setForm({ ...form, duration_seconds: Number(e.target.value) })}
                          className="form-input" />
                      </FormField>
                      <FormField label="Aspect ratio">
                        <select value={form.aspect_ratio}
                          onChange={(e) => setForm({ ...form, aspect_ratio: e.target.value as "9:16" | "16:9" | "1:1" })}
                          className="form-input">
                          <option value="9:16">9:16 · Vertical</option>
                          <option value="16:9">16:9 · Landscape</option>
                          <option value="1:1">1:1 · Square</option>
                        </select>
                      </FormField>
                    </div>
                    <FormField label="Target audience">
                      <input value={form.target_audience}
                        onChange={(e) => setForm({ ...form, target_audience: e.target.value })}
                        className="form-input" />
                    </FormField>
                    <FormField label="Objective">
                      <input value={form.objective}
                        onChange={(e) => setForm({ ...form, objective: e.target.value })}
                        className="form-input" />
                    </FormField>
                    <div className="grid gap-4 sm:grid-cols-2">
                      <FormField label="Language">
                        <input value={form.language}
                          onChange={(e) => setForm({ ...form, language: e.target.value })}
                          className="form-input" />
                      </FormField>
                      <FormField label="Tone">
                        <input value={form.tone}
                          onChange={(e) => setForm({ ...form, tone: e.target.value })}
                          className="form-input" />
                      </FormField>
                    </div>
                    <FormField label="Additional instructions (optional)">
                      <textarea rows={3} value={form.additional_instructions}
                        onChange={(e) => setForm({ ...form, additional_instructions: e.target.value })}
                        className="form-input" placeholder="Visual style, number of scenes, product details..." />
                    </FormField>
                    <FormField label="Workspace">
                      <select value={form.workspace}
                        onChange={(e) => setForm({ ...form, workspace: e.target.value })}
                        className="form-input">
                        <option value="iotelligen-marketing">IoTelliGen Marketing</option>
                        <option value="iotelligen">IoTelliGen</option>
                      </select>
                    </FormField>
                    <button type="submit" disabled={planBusy}
                      className="w-full rounded-lg bg-[#13A982] px-5 py-3 text-sm font-semibold text-white transition hover:bg-[#0f9270] disabled:opacity-60">
                      {planBusy ? "Generating storyboard..." : "Generate storyboard"}
                    </button>
                  </form>
                </section>

                <section className="rounded-xl border border-[#E5EAF0] bg-white p-6">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <h2 className="text-lg font-semibold text-slate-900">Storyboard editor</h2>
                      <p className="mt-1 text-sm text-slate-500">
                        Review and edit narration, visuals and scene text before saving.
                      </p>
                    </div>
                    {videoPlan && (
                      <span className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700">
                        {videoPlan.scenes.length} scenes · {videoPlan.duration_seconds}s
                      </span>
                    )}
                  </div>
                  {!videoPlan ? (
                    <div className="mt-6 rounded-lg bg-slate-50 p-10 text-center text-sm text-slate-500">
                      Your generated storyboard will appear here.
                    </div>
                  ) : (
                    <div className="mt-5 space-y-5">
                      <FormField label="Video title">
                        <input value={videoPlan.title}
                          onChange={(e) => setVideoPlan({ ...videoPlan, title: e.target.value })}
                          className="form-input" />
                      </FormField>
                      <FormField label="Concept">
                        <textarea rows={2} value={videoPlan.concept}
                          onChange={(e) => setVideoPlan({ ...videoPlan, concept: e.target.value })}
                          className="form-input" />
                      </FormField>
                      {videoPlan.scenes.map((scene) => (
                        <article key={scene.scene_number}
                          className="space-y-3 rounded-xl border border-slate-200 p-4">
                          <div className="flex items-center justify-between">
                            <h3 className="font-semibold text-slate-800">
                              Scene {scene.scene_number} · {scene.purpose}
                            </h3>
                            <span className="text-xs text-slate-400">{scene.duration_seconds}s</span>
                          </div>
                          <FormField label="Narration">
                            <textarea rows={2} value={scene.narration}
                              onChange={(e) => updateScene(scene.scene_number, "narration", e.target.value)}
                              className="form-input" />
                          </FormField>
                          <FormField label="Visual prompt">
                            <textarea rows={3} value={scene.visual_prompt}
                              onChange={(e) => updateScene(scene.scene_number, "visual_prompt", e.target.value)}
                              className="form-input" />
                          </FormField>
                          <div className="grid gap-3 sm:grid-cols-2">
                            <FormField label="On-screen text">
                              <input value={scene.on_screen_text}
                                onChange={(e) => updateScene(scene.scene_number, "on_screen_text", e.target.value)}
                                className="form-input" />
                            </FormField>
                            <FormField label="Transition">
                              <select value={scene.transition}
                                onChange={(e) =>
                                  updateScene(
                                    scene.scene_number,
                                    "transition",
                                    e.target.value as VideoScene["transition"]
                                  )
                                }
                                className="form-input">
                                <option value="cut">Cut</option>
                                <option value="fade">Fade</option>
                                <option value="slide">Slide</option>
                                <option value="zoom">Zoom</option>
                                <option value="dissolve">Dissolve</option>
                              </select>
                            </FormField>
                          </div>
                        </article>
                      ))}
                      <FormField label="Call to action">
                        <input value={videoPlan.cta}
                          onChange={(e) => setVideoPlan({ ...videoPlan, cta: e.target.value })}
                          className="form-input" />
                      </FormField>
                      <button type="button" onClick={() => void saveDraft()} disabled={draftBusy}
                        className="w-full rounded-lg bg-[#172033] px-5 py-3 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-60">
                        {draftBusy ? "Saving draft..." : "Save storyboard as draft"}
                      </button>
                    </div>
                  )}
                </section>
              </div>

              {workflowMessage && (
                <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">
                  {workflowMessage}
                </div>
              )}

              <section className="rounded-xl border border-[#E5EAF0] bg-white p-5">
                <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
                  <div>
                    <h2 className="font-semibold text-slate-900">Production workflow</h2>
                    <p className="mt-1 text-xs text-slate-500">
                      Save a draft, generate images, approve each scene, then render.
                    </p>
                  </div>
                  <div className="min-w-[240px]">
                    <label className="mb-1 block text-xs text-slate-500">Selected video job</label>
                    <select
                      value={selectedJob?.id ?? ""}
                      onChange={(e) => {
                        const job = jobs.find((item) => item.id === e.target.value);
                        if (job) setSelectedJob(job);
                      }}
                      className="form-input"
                    >
                      <option value="">Select a video job</option>
                      {jobs.map((job) => (
                        <option key={job.id} value={job.id}>
                          {job.title} · {job.status}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
                <div className="mt-5 grid gap-3 md:grid-cols-3">
                  <button type="button" onClick={() => void generateSceneAssets()}
                    disabled={!selectedJob || assetBusy}
                    className="rounded-lg border border-slate-200 p-4 text-left hover:border-emerald-300 hover:bg-emerald-50/30 disabled:opacity-50">
                    <div className="text-sm font-semibold text-slate-800">
                      {assetBusy ? "Submitting..." : "1. Generate scene images"}
                    </div>
                    <p className="mt-1 text-xs text-slate-500">
                      Generate one FAL image for each storyboard scene.
                    </p>
                  </button>
                  <button type="button" onClick={() => setActiveSection("Video Library")}
                    disabled={!selectedJob}
                    className="rounded-lg border border-slate-200 p-4 text-left hover:border-emerald-300 hover:bg-emerald-50/30 disabled:opacity-50">
                    <div className="text-sm font-semibold text-slate-800">2. Review and approve assets</div>
                    <p className="mt-1 text-xs text-slate-500">
                      Open the asset gallery to approve or regenerate images.
                    </p>
                  </button>
                  <button type="button" onClick={() => void renderApprovedVideo()}
                    disabled={!selectedJob || renderBusy}
                    className="rounded-lg bg-[#13A982] p-4 text-left text-white hover:bg-[#0f9270] disabled:opacity-50">
                    <div className="text-sm font-semibold">
                      {renderBusy ? "Submitting render..." : "3. Render approved video"}
                    </div>
                    <p className="mt-1 text-xs text-white/80">
                      Backend verifies that every scene has an approved image.
                    </p>
                  </button>
                </div>
                {selectedJob && (
                  <div className="mt-4 flex flex-wrap items-center gap-3 text-xs text-slate-500">
                    <span>Job status: <strong className="text-slate-700">{selectedJob.status}</strong></span>
                    <span>Progress: <strong className="text-slate-700">{selectedJob.progress ?? 0}%</strong></span>
                    <button type="button" onClick={() => setActiveSection("Video Library")}
                      className="font-semibold text-[#119A78]">
                      Open selected job in Video Library
                    </button>
                  </div>
                )}
              </section>

              <AssetGallery jobId={selectedJob?.id ?? null} />
              <VideoPreview job={selectedJob} videoUrl={videoUrl} versions={versions} />
            </div>
          )}

          {/* Video Library */}
          {activeSection === "Video Library" && (
            <section className="rounded-xl border border-[#E5EAF0] bg-white p-5">
              <div className="mb-5 flex items-center justify-between">
                <div>
                  <h2 className="font-semibold text-slate-900">
                    Video library
                  </h2>
                  <p className="mt-1 text-xs text-slate-500">
                    Videos generated by your platform
                  </p>
                </div>

                <button
                  onClick={() => void loadJobs()}
                  className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-medium text-slate-600 hover:bg-slate-50"
                >
                  Refresh
                </button>
              </div>

              <JobTable
                jobs={jobs}
                loading={loading}
                selectedId={selectedJob?.id}
                onSelect={setSelectedJob}
              />

              <div className="mt-6">
                <VideoPreview
                  job={selectedJob}
                  videoUrl={videoUrl}
                  versions={versions}
                />
              </div>
              <div className="mt-6">
               <AssetGallery jobId={selectedJob?.id ?? null} />
              </div>
            </section>
          )}

          {/* Placeholder sections */}
          {![
            "Overview",
            "Video Studio",
            "Video Library",
          ].includes(activeSection) && (
            <section className="rounded-xl border border-[#E5EAF0] bg-white p-10 text-center">
              <div className="text-3xl text-slate-300">◈</div>
              <h2 className="mt-4 text-lg font-semibold text-slate-800">
                {activeSection}
              </h2>
              <p className="mx-auto mt-2 max-w-md text-sm text-slate-500">
                This module will be integrated with the existing backend and
                automation workflows in a later development stage.
              </p>
            </section>
          )}

          <footer className="border-t border-[#E5EAF0] pt-5 text-xs text-slate-400">
            IoTelliGen AI Studio · Development environment
          </footer>
        </div>
      </main>
    </div>
  );
}

function JobTable({
  jobs,
  loading,
  selectedId,
  onSelect,
}: {
  jobs: VideoJob[];
  loading: boolean;
  selectedId?: string;
  onSelect: (job: VideoJob) => void;
}) {
  if (loading) {
    return (
      <div className="py-10 text-center text-sm text-slate-400">
        Loading video jobs...
      </div>
    );
  }

  if (jobs.length === 0) {
    return (
      <div className="rounded-lg bg-slate-50 py-10 text-center text-sm text-slate-500">
        No video jobs found. Create your first video in Video Studio.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[600px] text-left text-sm">
        <thead>
          <tr className="border-b border-slate-100 text-xs text-slate-400">
            <th className="pb-3 font-medium">Video</th>
            <th className="pb-3 font-medium">Created</th>
            <th className="pb-3 font-medium">Progress</th>
            <th className="pb-3 font-medium">Status</th>
          </tr>
        </thead>

        <tbody>
          {jobs.map((job) => (
            <tr
              key={job.id}
              onClick={() => onSelect(job)}
              className={`cursor-pointer border-b border-slate-50 transition hover:bg-slate-50 ${
                selectedId === job.id ? "bg-emerald-50/50" : ""
              }`}
            >
              <td className="py-4 pr-4">
                <div className="font-medium text-slate-800">
                  {job.title}
                </div>
                <div className="mt-1 text-xs text-slate-400">
                  {job.template_id}
                </div>
              </td>

              <td className="py-4 pr-4 text-xs text-slate-500">
                {formatDate(job.created_at)}
              </td>

              <td className="w-32 py-4 pr-4">
                <div className="h-1.5 overflow-hidden rounded-full bg-slate-100">
                  <div
                    className="h-full rounded-full bg-[#13A982]"
                    style={{
                      width: `${Math.min(100, Math.max(0, job.progress || 0))}%`,
                    }}
                  />
                </div>
                <div className="mt-1 text-[10px] text-slate-400">
                  {job.progress || 0}%
                </div>
              </td>

              <td className="py-4">
                <span
                  className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${statusColor(job.status)}`}
                >
                  {job.status}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function VideoPreview({
  job,
  videoUrl,
  versions,
}: {
  job: VideoJob | null;
  videoUrl: string | null;
  versions: VideoVersion[];
}) {
  if (!job) {
    return null;
  }

  return (
    <section className="rounded-xl border border-[#E5EAF0] bg-white p-5">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
        <div>
          <h2 className="font-semibold text-slate-900">
            Video preview
          </h2>
          <p className="mt-1 text-xs text-slate-500">
            {job.title}
          </p>
        </div>

        <span
          className={`w-fit rounded-full px-3 py-1 text-xs font-medium ${statusColor(job.status)}`}
        >
          {job.status}
        </span>
      </div>

      <div className="mt-5 grid gap-6 lg:grid-cols-[280px_1fr]">
        <div className="flex min-h-[250px] items-center justify-center rounded-xl bg-[#172033] p-3">
          {job.status === "completed" && videoUrl ? (
            <video
              key={videoUrl}
              src={videoUrl}
              controls
              playsInline
              preload="metadata"
              className="max-h-[450px] w-full rounded-lg object-contain"
            />
          ) : (
            <div className="text-center text-white">
              <div className="text-4xl">▣</div>
              <div className="mt-3 text-sm font-medium">
                {job.status === "failed"
                  ? "Rendering failed"
                  : job.status === "draft"
                    ? "Draft saved — ready for asset generation"
                    : ["assets_pending", "assets_ready"].includes(job.status)
                      ? "Review scene assets"
                      : "Video is rendering"}
              </div>
              <div className="mt-2 text-xs text-slate-400">
                {job.progress || 0}% completed
              </div>
              <div className="mx-auto mt-4 h-1.5 w-40 overflow-hidden rounded-full bg-white/20">
                <div
                  className="h-full bg-[#16C79A]"
                  style={{
                    width: `${Math.min(100, job.progress || 0)}%`,
                  }}
                />
              </div>
            </div>
          )}
        </div>

        <div className="space-y-4">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">
              Job details
            </div>

            <div className="mt-3 grid grid-cols-2 gap-4">
              <Detail label="Template" value={job.template_id} />
              <Detail label="Workspace" value={job.workspace_slug} />
              <Detail label="Renderer job" value={job.renderer_job_id || "—"} />
              <Detail label="Output file" value={job.output_file || "—"} />
              <Detail label="Created" value={formatDate(job.created_at)} />
              <Detail label="Progress" value={`${job.progress || 0}%`} />
            </div>
          </div>

          {job.error_message && (
            <div className="rounded-lg bg-red-50 p-3 text-xs text-red-700">
              {job.error_message}
            </div>
          )}

          <div>
            <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">
              Versions
            </div>

            {versions.length > 0 ? (
              <div className="mt-2 space-y-2">
                {versions.map((version) => (
                  <div
                    key={version.id}
                    className="flex items-center justify-between rounded-lg bg-slate-50 p-3"
                  >
                    <div>
                      <div className="text-sm font-medium text-slate-700">
                        Version {version.version_number}
                      </div>
                      <div className="text-xs text-slate-400">
                        {version.filename}
                      </div>
                    </div>
                    <span className="text-xs text-emerald-700">
                      {version.width} × {version.height}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="mt-2 text-xs text-slate-400">
                No completed versions yet.
              </p>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-slate-400">{label}</div>
      <div className="mt-1 break-all text-sm font-medium text-slate-700">
        {value}
      </div>
    </div>
  );
}

function QuickAction({
  icon,
  title,
  description,
  onClick,
}: {
  icon: string;
  title: string;
  description: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="flex w-full items-center gap-3 rounded-lg border border-slate-100 p-3 text-left transition hover:border-emerald-200 hover:bg-emerald-50/40"
    >
      <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-slate-100 text-lg text-slate-700">
        {icon}
      </div>
      <div>
        <div className="text-sm font-medium text-slate-800">{title}</div>
        <div className="mt-1 text-xs text-slate-400">{description}</div>
      </div>
    </button>
  );
}

function FormField({
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
