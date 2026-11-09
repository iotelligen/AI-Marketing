
"use client";

import { useCallback, useEffect, useState } from "react";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type VideoAsset = {
  asset_id: string;
  job_id: string;
  scene_number: number | null;
  asset_type: string;
  provider: string | null;
  model: string | null;
  status: string;
  filename: string;
  mime_type: string | null;
  error_message: string | null;
  metadata: Record<string, unknown>;
  review_status: string;
  reviewed_at: string | null;
  review_note: string | null;
  created_at: string;
  file_url: string | null;
};

type AssetGalleryProps = {
  jobId: string | null;
};

function statusStyle(status: string) {
  switch (status) {
    case "completed":
    case "approved":
      return "bg-emerald-50 text-emerald-700";
    case "failed":
    case "rejected":
      return "bg-red-50 text-red-700";
    case "generating":
      return "bg-blue-50 text-blue-700";
    default:
      return "bg-amber-50 text-amber-700";
  }
}

export default function AssetGallery({ jobId }: AssetGalleryProps) {
  const [assets, setAssets] = useState<VideoAsset[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [filter, setFilter] = useState("all");
  const [preview, setPreview] = useState<VideoAsset | null>(null);

  const loadAssets = useCallback(async () => {
    if (!jobId) {
      setAssets([]);
      return;
    }

    try {
      const response = await fetch(
        `${API_URL}/videos/jobs/${jobId}/assets?limit=100`,
        { cache: "no-store" }
      );

      if (!response.ok) {
        throw new Error(`Asset API returned HTTP ${response.status}`);
      }

      const data = await response.json();
      setAssets(data.assets ?? []);
      setError("");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Unable to load assets."
      );
    } finally {
      setLoading(false);
    }
  }, [jobId]);

  useEffect(() => {
    setLoading(true);
    void loadAssets();

    const interval = window.setInterval(() => {
      void loadAssets();
    }, 5000);

    return () => window.clearInterval(interval);
  }, [loadAssets]);

  async function performAction(
    assetId: string,
    action: () => Promise<Response>
  ) {
    setBusyId(assetId);
    setError("");

    try {
      const response = await action();

      if (!response.ok) {
        const result = await response.json().catch(() => null);
        throw new Error(
          result?.detail || `Request failed: HTTP ${response.status}`
        );
      }

      await loadAssets();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Asset operation failed."
      );
    } finally {
      setBusyId(null);
    }
  }

  async function reviewAsset(
    asset: VideoAsset,
    decision: "approved" | "rejected"
  ) {
    const note = window.prompt(
      decision === "approved"
        ? "Approval note (optional):"
        : "Reason for rejection (optional):"
    );

    if (note === null) return;

    await performAction(asset.asset_id, () =>
      fetch(`${API_URL}/videos/assets/${asset.asset_id}/review`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          decision,
          note: note.trim() || null,
        }),
      })
    );
  }

  async function regenerateAsset(asset: VideoAsset) {
    if (
      !window.confirm(
        `Generate another image for scene ${asset.scene_number ?? "—"}?`
      )
    ) {
      return;
    }

    await performAction(asset.asset_id, () =>
      fetch(
        `${API_URL}/videos/assets/${asset.asset_id}/regenerate`,
        { method: "POST" }
      )
    );
  }

  async function deleteAsset(asset: VideoAsset) {
    if (
      !window.confirm(
        `Permanently delete ${asset.filename} and its stored file?`
      )
    ) {
      return;
    }

    await performAction(asset.asset_id, () =>
      fetch(`${API_URL}/videos/assets/${asset.asset_id}`, {
        method: "DELETE",
      })
    );

    if (preview?.asset_id === asset.asset_id) {
      setPreview(null);
    }
  }

  const filteredAssets = assets.filter((asset) => {
    if (filter === "all") return true;
    if (filter === "approved") return asset.review_status === "approved";
    if (filter === "pending") return asset.review_status === "pending";
    if (filter === "rejected") return asset.review_status === "rejected";
    if (filter === "failed") return asset.status === "failed";
    return true;
  });

  const completedCount = assets.filter(
    (asset) => asset.status === "completed"
  ).length;

  const approvedCount = assets.filter(
    (asset) => asset.review_status === "approved"
  ).length;

  const pendingCount = assets.filter(
    (asset) => asset.review_status === "pending"
  ).length;

  if (!jobId) {
    return (
      <section className="rounded-xl border border-[#E5EAF0] bg-white p-8 text-center">
        <h2 className="font-semibold text-slate-800">Generated assets</h2>
        <p className="mt-2 text-sm text-slate-500">
          Select a video job above to manage its generated images.
        </p>
      </section>
    );
  }

  return (
    <section className="rounded-xl border border-[#E5EAF0] bg-white p-5">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
        <div>
          <h2 className="font-semibold text-slate-900">
            Generated assets
          </h2>
          <p className="mt-1 text-xs text-slate-500">
            Review and manage images generated for this video.
          </p>
        </div>

        <button
          onClick={() => {
            setLoading(true);
            void loadAssets();
          }}
          className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-medium text-slate-600 hover:bg-slate-50"
        >
          Refresh assets
        </button>
      </div>

      <div className="mt-5 grid grid-cols-3 gap-3">
        <div className="rounded-lg bg-slate-50 p-3">
          <div className="text-xs text-slate-500">Generated</div>
          <div className="mt-1 text-xl font-semibold text-slate-900">
            {completedCount}
          </div>
        </div>

        <div className="rounded-lg bg-emerald-50 p-3">
          <div className="text-xs text-emerald-700">Approved</div>
          <div className="mt-1 text-xl font-semibold text-emerald-800">
            {approvedCount}
          </div>
        </div>

        <div className="rounded-lg bg-amber-50 p-3">
          <div className="text-xs text-amber-700">Needs review</div>
          <div className="mt-1 text-xl font-semibold text-amber-800">
            {pendingCount}
          </div>
        </div>
      </div>

      <div className="mt-5 flex flex-wrap gap-2">
        {[
          ["all", "All"],
          ["pending", "Needs review"],
          ["approved", "Approved"],
          ["rejected", "Rejected"],
          ["failed", "Failed"],
        ].map(([value, label]) => (
          <button
            key={value}
            onClick={() => setFilter(value)}
            className={`rounded-full px-3 py-2 text-xs font-medium ${
              filter === value
                ? "bg-[#172033] text-white"
                : "bg-slate-100 text-slate-600 hover:bg-slate-200"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {error && (
        <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {loading && assets.length === 0 ? (
        <div className="py-12 text-center text-sm text-slate-400">
          Loading generated assets...
        </div>
      ) : filteredAssets.length === 0 ? (
        <div className="mt-5 rounded-lg bg-slate-50 py-12 text-center">
          <div className="text-sm font-medium text-slate-600">
            No assets found
          </div>
          <p className="mt-2 text-xs text-slate-400">
            Generated assets for this video will appear here.
          </p>
        </div>
      ) : (
        <div className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {filteredAssets.map((asset) => (
            <article
              key={asset.asset_id}
              className="overflow-hidden rounded-xl border border-slate-200 bg-white"
            >
              <button
                onClick={() => {
                  if (asset.file_url) setPreview(asset);
                }}
                disabled={!asset.file_url}
                className="relative flex aspect-[9/12] w-full items-center justify-center overflow-hidden bg-slate-100"
              >
                {asset.file_url ? (
                  <img
                    src={`${API_URL}${asset.file_url}`}
                    alt={`Scene ${asset.scene_number ?? ""}`}
                    className="h-full w-full object-cover transition hover:scale-[1.02]"
                  />
                ) : (
                  <div className="p-4 text-center text-sm text-slate-500">
                    {asset.status === "failed"
                      ? "Generation failed"
                      : "Image is being generated"}
                    <div className="mt-2 text-xs">
                      {asset.status}
                    </div>
                  </div>
                )}
              </button>

              <div className="space-y-3 p-4">
                <div className="flex items-center justify-between gap-2">
                  <div className="text-sm font-semibold text-slate-800">
                    Scene {asset.scene_number ?? "—"}
                  </div>

                  <span
                    className={`rounded-full px-2 py-1 text-[10px] font-medium ${statusStyle(asset.status)}`}
                  >
                    {asset.status}
                  </span>
                </div>

                <div className="flex flex-wrap gap-2">
                  <span
                    className={`rounded-full px-2 py-1 text-[10px] font-medium ${statusStyle(asset.review_status)}`}
                  >
                    {asset.review_status}
                  </span>

                  <span className="rounded-full bg-slate-100 px-2 py-1 text-[10px] text-slate-600">
                    {asset.provider ?? "Unknown provider"}
                  </span>
                </div>

                {asset.review_note && (
                  <p className="text-xs text-slate-500">
                    Note: {asset.review_note}
                  </p>
                )}

                {asset.error_message && (
                  <p className="text-xs text-red-600">
                    {asset.error_message}
                  </p>
                )}

                {asset.status === "completed" && (
                  <div className="grid grid-cols-2 gap-2">
                    <button
                      disabled={busyId === asset.asset_id}
                      onClick={() => void reviewAsset(asset, "approved")}
                      className="rounded-lg bg-emerald-50 px-2 py-2 text-xs font-semibold text-emerald-700 hover:bg-emerald-100"
                    >
                      Approve
                    </button>

                    <button
                      disabled={busyId === asset.asset_id}
                      onClick={() => void reviewAsset(asset, "rejected")}
                      className="rounded-lg bg-red-50 px-2 py-2 text-xs font-semibold text-red-700 hover:bg-red-100"
                    >
                      Reject
                    </button>

                    <button
                      disabled={busyId === asset.asset_id}
                      onClick={() => void regenerateAsset(asset)}
                      className="rounded-lg border border-slate-200 px-2 py-2 text-xs font-medium text-slate-600 hover:bg-slate-50"
                    >
                      Regenerate
                    </button>

                    <a
                      href={`${API_URL}${asset.file_url}`}
                      target="_blank"
                      rel="noreferrer"
                      className="rounded-lg border border-slate-200 px-2 py-2 text-center text-xs font-medium text-slate-600 hover:bg-slate-50"
                    >
                      Open image
                    </a>

                    <button
                      disabled={busyId === asset.asset_id}
                      onClick={() => void deleteAsset(asset)}
                      className="col-span-2 rounded-lg border border-red-200 px-2 py-2 text-xs font-medium text-red-600 hover:bg-red-50"
                    >
                      Delete asset
                    </button>
                  </div>
                )}

                {(asset.status === "failed") && (
                  <div className="flex gap-2">
                    <button
                      disabled={busyId === asset.asset_id}
                      onClick={() => void regenerateAsset(asset)}
                      className="flex-1 rounded-lg bg-[#13A982] px-2 py-2 text-xs font-semibold text-white hover:bg-[#0f9270]"
                    >
                      Retry generation
                    </button>

                    <button
                      disabled={busyId === asset.asset_id}
                      onClick={() => void deleteAsset(asset)}
                      className="rounded-lg border border-red-200 px-3 py-2 text-xs text-red-600"
                    >
                      Delete
                    </button>
                  </div>
                )}

                {busyId === asset.asset_id && (
                  <div className="text-center text-xs text-slate-400">
                    Processing...
                  </div>
                )}
              </div>
            </article>
          ))}
        </div>
      )}

      {preview && preview.file_url && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4"
          onClick={() => setPreview(null)}
        >
          <div
            className="relative max-h-[90vh] max-w-4xl"
            onClick={(event) => event.stopPropagation()}
          >
            <button
              onClick={() => setPreview(null)}
              className="absolute -right-3 -top-3 z-10 flex h-9 w-9 items-center justify-center rounded-full bg-white text-lg text-slate-800 shadow"
              aria-label="Close preview"
            >
              ×
            </button>

            <img
              src={`${API_URL}${preview.file_url}`}
              alt={`Scene ${preview.scene_number ?? ""}`}
              className="max-h-[85vh] max-w-full rounded-xl object-contain"
            />

            <div className="mt-2 text-center text-sm text-white">
              Scene {preview.scene_number} · {preview.filename}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
