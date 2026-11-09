
import express from "express";
import path from "node:path";
import fs from "node:fs/promises";
import { fileURLToPath } from "node:url";

import { Queue, Worker } from "bullmq";
import { bundle } from "@remotion/bundler";
import {
  renderMedia,
  selectComposition
} from "@remotion/renderer";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const PORT = Number(process.env.PORT || 8100);
const OUTPUT_DIR = process.env.VIDEO_OUTPUT_DIR || "/data/videos";

const ASSET_DIR = path.resolve(
  process.env.ASSET_STORAGE || "/data/assets"
);

const REDIS_CONNECTION = {
  host: process.env.REDIS_HOST || "redis",
  port: Number(process.env.REDIS_PORT || 6379),
  password: process.env.REDIS_PASSWORD || undefined,
  maxRetriesPerRequest: null
};

const QUEUE_NAME = "iotelligen-video-render";

const app = express();
app.use(express.json({ limit: "1mb" }));

app.use(
  "/assets",
  express.static(ASSET_DIR, {
    dotfiles: "deny",
    index: false,
    fallthrough: false,
  })
);

let renderQueue;
let rendererWorker;
let bundledSite;

function validateRequest(body) {
  const {
    brandName,
    title,
    subtitle,
    cta,
    accentColor
  } = body || {};

  const values = {
    brandName: brandName ?? "IoTelliGen",
    title: title ?? "Make Your Factory Smarter",
    subtitle: subtitle ?? "Monitor. Analyze. Optimize.",
    cta: cta ?? "Discover Industrial IoT",
    accentColor: accentColor ?? "#16C79A"
  };

  for (const [key, value] of Object.entries(values)) {
    if (typeof value !== "string" || value.length > 200) {
      throw new Error(`Invalid value for ${key}`);
    }
  }

  if (!/^#[0-9a-fA-F]{6}$/.test(values.accentColor)) {
    throw new Error("Invalid accentColor. Expected #RRGGBB.");
  }

  return values;
}

async function validateDynamicManifest(body) {
  if (!body || body.composition_id !== "DynamicVideo") {
    throw new Error("Invalid composition_id");
  }

  const fps = Number(body.fps || 30);
  const width = Number(body.width || 1080);
  const height = Number(body.height || 1920);
  const durationSeconds = Number(body.duration_seconds);

  if (![24, 25, 30, 50, 60].includes(fps)) {
    throw new Error("Unsupported frame rate");
  }

  if (
    !Number.isInteger(width) ||
    !Number.isInteger(height) ||
    width < 320 ||
    height < 320 ||
    width > 1920 ||
    height > 1920
  ) {
    throw new Error("Invalid video dimensions");
  }

  if (
    !Number.isInteger(durationSeconds) ||
    durationSeconds < 1 ||
    durationSeconds > 180
  ) {
    throw new Error("Invalid video duration");
  }

  if (!Array.isArray(body.scenes) || body.scenes.length === 0) {
    throw new Error("At least one scene is required");
  }

  if (body.scenes.length > 30) {
    throw new Error("Maximum 30 scenes allowed");
  }

  const assetRoot = await fs.realpath(ASSET_DIR);
  let totalDuration = 0;

  const scenes = [];

  for (let index = 0; index < body.scenes.length; index++) {
    const scene = body.scenes[index];

    if (scene.scene_number !== index + 1) {
      throw new Error("Scene numbers must be sequential");
    }

    if (
      !Number.isInteger(scene.duration_seconds) ||
      scene.duration_seconds < 1 ||
      scene.duration_seconds > 60
    ) {
      throw new Error(
        `Invalid duration for scene ${scene.scene_number}`
      );
    }

    if (scene.visual_type !== "image") {
      throw new Error(
        `Scene ${scene.scene_number}: only image scenes are currently supported`
      );
    }

    if (typeof scene.asset_path !== "string") {
      throw new Error(
        `Missing asset path for scene ${scene.scene_number}`
      );
    }

    const realAssetPath = await fs.realpath(scene.asset_path);
    const relativePath = path.relative(assetRoot, realAssetPath);

    if (
      !relativePath ||
      relativePath.startsWith("..") ||
      path.isAbsolute(relativePath)
    ) {
      throw new Error("Asset path is outside the asset storage directory");
    }

    const extension = path.extname(realAssetPath).toLowerCase();

    if (![".jpg", ".jpeg", ".png", ".webp"].includes(extension)) {
      throw new Error("Unsupported image format");
    }

    const stat = await fs.stat(realAssetPath);

    if (!stat.isFile()) {
      throw new Error("Asset path is not a file");
    }

    const encodedPath = relativePath
      .split(path.sep)
      .map(encodeURIComponent)
      .join("/");

    totalDuration += scene.duration_seconds;

    scenes.push({
      scene_number: scene.scene_number,
      duration_seconds: scene.duration_seconds,
      visual_type: "image",
      src: `http://127.0.0.1:${PORT}/assets/${encodedPath}`,
      narration: scene.narration || "",
      on_screen_text: scene.on_screen_text || "",
      transition: scene.transition || "fade",
      animation: scene.animation || {
        type: "slow_zoom_in",
      },
    });
  }

  if (totalDuration !== durationSeconds) {
    throw new Error(
      `Scene durations total ${totalDuration}s, expected ${durationSeconds}s`
    );
  }

  return {
    composition_id: "DynamicVideo",
    title: body.title || "Industrial Video",
    brand_name: body.brand_name || "IoTelliGen",
    accent_color: body.accent_color || "#16C79A",
    fps,
    width,
    height,
    duration_seconds: durationSeconds,
    scenes,
  };
}

// Health endpoint
app.get("/health", async (_req, res) => {
  try {
    await renderQueue.client;

    res.json({
      status: "healthy",
      service: "iotelligen-video-renderer",
      queue: QUEUE_NAME
    });
  } catch {
    res.status(503).json({
      status: "unhealthy"
    });
  }
});

// Submit a video rendering job
app.post("/render", async (req, res) => {
  try {
    const input =
      req.body?.composition_id === "DynamicVideo"
        ? await validateDynamicManifest(req.body)
        : validateRequest(req.body);

    const compositionId =
      input.composition_id || "IndustrialPromo";

    const job = await renderQueue.add(
      `render-${compositionId}`,
      input,
      {
        removeOnComplete: false,
        removeOnFail: false,
      }
    );

    res.status(202).json({
      job_id: job.id,
      status: "queued",
      template: compositionId,
      format: "mp4",
      resolution: `${input.width || 1080}x${input.height || 1920}`,
      duration_seconds: input.duration_seconds || 30,
      status_url: `/jobs/${job.id}`,
      video_url: null,
    });
  } catch (error) {
    res.status(400).json({
      detail: error.message,
    });
  }
});

// Get job status
app.get("/jobs/:id", async (req, res) => {
  try {
    const job = await renderQueue.getJob(req.params.id);

    if (!job) {
      return res.status(404).json({
        detail: "Video job not found"
      });
    }

    const state = await job.getState();

    res.json({
      job_id: job.id,
      status: state,
      progress: job.progress || 0,
      result: job.returnvalue || null,
      error: job.failedReason || null
    });
  } catch (error) {
    res.status(500).json({
      detail: error.message
    });
  }
});

// Download completed video
app.get("/videos/:id", async (req, res) => {
  try {
    const job = await renderQueue.getJob(req.params.id);

    if (!job || await job.getState() !== "completed") {
      return res.status(404).json({
        detail: "Completed video not found"
      });
    }

    const outputPath = path.join(
      OUTPUT_DIR,
      `${req.params.id}.mp4`
    );

    await fs.access(outputPath);

    res.type("mp4");
    res.sendFile(outputPath);
  } catch {
    res.status(404).json({
      detail: "Video file not found"
    });
  }
});

async function startRenderer() {
  await fs.mkdir(OUTPUT_DIR, { recursive: true });

  console.log("Bundling Remotion compositions...");

  bundledSite = await bundle({
    entryPoint: path.resolve(
      __dirname,
      "index.tsx"
    ),
    publicDir: path.resolve(
      __dirname,
      "../public"
    )
  });

  console.log("Remotion bundle ready.");

  renderQueue = new Queue(QUEUE_NAME, {
    connection: REDIS_CONNECTION
  });

  rendererWorker = new Worker(
    QUEUE_NAME,
    async (job) => {
      console.log(`Starting video job ${job.id}`);

      await job.updateProgress(5);

const inputProps = { ...job.data };

await job.updateProgress(5);

const compositionId =
  inputProps.composition_id || "IndustrialPromo";

delete inputProps.composition_id;

const composition = await selectComposition({
  serveUrl: bundledSite,
  id: compositionId,
  inputProps,
});
      const outputPath = path.join(
        OUTPUT_DIR,
        `${job.id}.mp4`
      );

      await renderMedia({
        composition,
        serveUrl: bundledSite,
        codec: "h264",
        outputLocation: outputPath,
        inputProps,
        crf: 23,
        concurrency: 2,
        chromiumOptions: {
          enableMultiProcessOnLinux: true
        },
        onProgress: async ({ progress }) => {
          await job.updateProgress(
            Math.min(99, Math.round(progress * 100))
          );
        }
      });

      console.log(`Completed video job ${job.id}`);

return {
  output_file: `${job.id}.mp4`,
  download_url: `/videos/${job.id}`,
  resolution: `${composition.width}x${composition.height}`,
  duration_seconds: Math.round(
    composition.durationInFrames / composition.fps
  ),
  fps: composition.fps,
  format: "mp4",
  composition_id: compositionId,
};
    },
    {
      connection: REDIS_CONNECTION,
      concurrency: 1
    }
  );

  rendererWorker.on("failed", (job, error) => {
    console.error(
      `Video job ${job?.id} failed:`,
      error
    );
  });

  app.listen(PORT, "0.0.0.0", () => {
    console.log(
      `Video renderer API listening on port ${PORT}`
    );
  });
}

async function shutdown() {
  console.log("Shutting down video renderer...");

  await rendererWorker?.close();
  await renderQueue?.close();

  process.exit(0);
}

process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);

startRenderer().catch((error) => {
  console.error("Renderer startup failed:", error);
  process.exit(1);
});
