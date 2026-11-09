// Run inside the renderer image, from /app:
//   node --test tests/
//
// The validator reads its configuration when server.js is imported,
// so the environment is prepared first and the module is imported
// dynamically. RENDERER_SKIP_STARTUP keeps Redis, the worker and the
// HTTP server out of the test.

import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { before, test } from "node:test";

let validateDynamicManifest;
let assetDir;
let outsideLogo;

before(async () => {
  const root = await fs.realpath(
    await fs.mkdtemp(path.join(os.tmpdir(), "renderer-test-"))
  );

  assetDir = path.join(root, "assets");
  outsideLogo = path.join(root, "outside.png");

  await fs.mkdir(path.join(assetDir, "job", "scene_01"), { recursive: true });
  await fs.mkdir(path.join(assetDir, "job", "scene_02"), { recursive: true });
  await fs.mkdir(path.join(assetDir, "brand", "profile"), { recursive: true });

  await fs.writeFile(path.join(assetDir, "job", "scene_01", "image.png"), "x");
  await fs.writeFile(path.join(assetDir, "job", "scene_02", "image.png"), "x");
  await fs.writeFile(path.join(assetDir, "brand", "profile", "logo.png"), "x");
  await fs.writeFile(path.join(assetDir, "brand", "profile", "logo.svg"), "x");
  await fs.writeFile(outsideLogo, "x");

  process.env.RENDERER_SKIP_STARTUP = "1";
  process.env.ASSET_STORAGE = assetDir;
  process.env.PORT = "8100";

  ({ validateDynamicManifest } = await import("../src/server.js"));
});

function manifest(overrides = {}) {
  return {
    composition_id: "DynamicVideo",
    title: "Motor monitoring",
    brand_name: "IoTelliGen",
    accent_color: "#0A84FF",
    fps: 30,
    width: 1080,
    height: 1920,
    duration_seconds: 10,
    scenes: [
      {
        scene_number: 1,
        duration_seconds: 6,
        visual_type: "image",
        asset_path: path.join(assetDir, "job", "scene_01", "image.png"),
        beat: "hook",
        on_screen_text: "Motors fail",
        transition: "fade",
      },
      {
        scene_number: 2,
        duration_seconds: 4,
        visual_type: "image",
        asset_path: path.join(assetDir, "job", "scene_02", "image.png"),
        beat: "cta",
        on_screen_text: "Talk to us",
        transition: "fade",
      },
    ],
    ...overrides,
  };
}

function brand(overrides = {}) {
  return {
    name: "IoTelliGen",
    accent_color: "#0A84FF",
    tagline: "Smarter factories",
    website: "iotelligen.example",
    email: "sales@iotelligen.example",
    phone: "+880 1700 000000",
    logo_path: path.join(assetDir, "brand", "profile", "logo.png"),
    ...overrides,
  };
}

test("brand block and beats reach the composition", async () => {
  const result = await validateDynamicManifest(manifest({ brand: brand() }));

  assert.equal(result.brand_name, "IoTelliGen");
  assert.equal(result.accent_color, "#0A84FF");
  assert.deepEqual(result.brand, {
    name: "IoTelliGen",
    tagline: "Smarter factories",
    website: "iotelligen.example",
    email: "sales@iotelligen.example",
    phone: "+880 1700 000000",
    logo_src: "http://127.0.0.1:8100/assets/brand/profile/logo.png",
  });
  assert.deepEqual(
    result.scenes.map((scene) => scene.beat),
    ["hook", "cta"]
  );
});

test("manifests without a brand block or beats still validate", async () => {
  const input = manifest();

  for (const scene of input.scenes) {
    delete scene.beat;
  }

  const result = await validateDynamicManifest(input);

  assert.equal(result.brand.name, "IoTelliGen");
  assert.equal(result.brand.logo_src, null);
  assert.deepEqual(
    result.scenes.map((scene) => scene.beat),
    [null, null]
  );
});

test("an unknown beat is dropped rather than trusted", async () => {
  const input = manifest();
  input.scenes[0].beat = "testimonial";

  const result = await validateDynamicManifest(input);

  assert.equal(result.scenes[0].beat, null);
});

test("a logo outside the asset directory is rejected", async () => {
  await assert.rejects(
    validateDynamicManifest(
      manifest({ brand: brand({ logo_path: outsideLogo }) })
    ),
    /outside the asset storage directory/
  );
});

test("a logo that is not a raster image is rejected", async () => {
  await assert.rejects(
    validateDynamicManifest(
      manifest({
        brand: brand({
          logo_path: path.join(assetDir, "brand", "profile", "logo.svg"),
        }),
      })
    ),
    /Unsupported brand logo format/
  );
});

test("an invalid accent colour is rejected", async () => {
  await assert.rejects(
    validateDynamicManifest(manifest({ accent_color: "green" })),
    /Invalid accent_color/
  );
});

test("overlong brand text is rejected", async () => {
  await assert.rejects(
    validateDynamicManifest(
      manifest({ brand: brand({ tagline: "x".repeat(201) }) })
    ),
    /Invalid brand tagline/
  );
});
