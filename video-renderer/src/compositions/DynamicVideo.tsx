import React from "react";

import {
  AbsoluteFill,
  Audio,
  Sequence,
  Img,
  OffthreadVideo,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

export type DynamicScene = {
  scene_number: number;
  duration_seconds: number;
  visual_type: "image" | "video";
  src: string;
  // Optional ElevenLabs narration for this scene.
  audio_src?: string | null;
  // The "cta" beat is drawn as the branded end card.
  beat?:
    | "hook"
    | "pain_point"
    | "consequence"
    | "solution"
    | "benefit"
    | "cta"
    | null;
  narration?: string;
  on_screen_text?: string;
  transition?: "cut" | "fade" | "slide" | "zoom" | "dissolve";
  animation?: {
    type:
      | "slow_zoom_in"
      | "slow_zoom_out"
      | "pan_left"
      | "pan_right"
      | "none";
  };
};

// Verified brand facts from the stored brand profile. They are drawn
// by the renderer so they are never left to an image model.
export type DynamicBrand = {
  name: string;
  tagline?: string;
  website?: string;
  email?: string;
  phone?: string;
  logo_src?: string | null;
};

export type DynamicVideoProps = {
  title: string;
  brand_name: string;
  accent_color: string;
  brand?: DynamicBrand;
  fps: number;
  width: number;
  height: number;
  duration_seconds: number;
  scenes: DynamicScene[];
};

// A light plate keeps a logo legible on any photo or clip.
const LogoWatermark: React.FC<{ src: string }> = ({ src }) => (
  <div
    style={{
      position: "absolute",
      top: 56,
      left: 56,
      backgroundColor: "rgba(255,255,255,0.92)",
      borderRadius: 18,
      padding: "14px 20px",
    }}
  >
    <Img
      src={src}
      style={{
        display: "block",
        height: 64,
        width: "auto",
        maxWidth: 260,
        objectFit: "contain",
      }}
    />
  </div>
);

const EndCard: React.FC<{
  scene: DynamicScene;
  brand?: DynamicBrand;
  brandName: string;
  accentColor: string;
}> = ({ scene, brand, brandName, accentColor }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const appear = interpolate(frame, [0, Math.round(fps * 0.5)], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const contactLines = [brand?.website, brand?.phone, brand?.email].filter(
    (line): line is string => Boolean(line)
  );

  return (
    <AbsoluteFill
      style={{
        backgroundColor: "rgba(7,21,34,0.8)",
        justifyContent: "center",
        alignItems: "center",
        padding: 90,
      }}
    >
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          textAlign: "center",
          maxWidth: "100%",
          fontFamily: "Arial, sans-serif",
          color: "white",
          opacity: appear,
          transform: `translateY(${interpolate(appear, [0, 1], [30, 0])}px)`,
        }}
      >
        {brand?.logo_src ? (
          <div
            style={{
              backgroundColor: "rgba(255,255,255,0.96)",
              borderRadius: 28,
              padding: "28px 40px",
              marginBottom: 50,
            }}
          >
            <Img
              src={brand.logo_src}
              style={{
                display: "block",
                height: 180,
                width: "auto",
                maxWidth: 560,
                objectFit: "contain",
              }}
            />
          </div>
        ) : (
          <div
            style={{
              fontSize: 84,
              lineHeight: 1.1,
              fontWeight: 800,
              marginBottom: 40,
            }}
          >
            {brandName}
          </div>
        )}

        {brand?.tagline && (
          <div
            style={{
              fontSize: 36,
              lineHeight: 1.3,
              color: "rgba(255,255,255,0.8)",
              marginBottom: 46,
            }}
          >
            {brand.tagline}
          </div>
        )}

        {scene.on_screen_text && (
          <div
            style={{
              fontSize: 64,
              lineHeight: 1.15,
              fontWeight: 800,
              marginBottom: 36,
            }}
          >
            {scene.on_screen_text}
          </div>
        )}

        <div
          style={{
            width: 120,
            height: 7,
            backgroundColor: accentColor,
            borderRadius: 5,
            marginBottom: contactLines.length > 0 ? 40 : 0,
          }}
        />

        {contactLines.map((line) => (
          <div
            key={line}
            style={{
              fontSize: 40,
              lineHeight: 1.5,
              fontWeight: 600,
            }}
          >
            {line}
          </div>
        ))}
      </div>
    </AbsoluteFill>
  );
};

const Scene: React.FC<{
  scene: DynamicScene;
  accentColor: string;
  brand?: DynamicBrand;
  brandName: string;
}> = ({ scene, accentColor, brand, brandName }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  const fadeFrames = Math.min(15, Math.floor(durationInFrames / 4));

  const opacity =
    scene.transition === "fade" || scene.transition === "dissolve"
      ? interpolate(
          frame,
          [0, fadeFrames, durationInFrames - fadeFrames, durationInFrames],
          [0, 1, 1, 0],
          {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }
        )
      : 1;

  const progress = frame / Math.max(1, durationInFrames - 1);

  let scale = 1;
  let translateX = 0;

  switch (scene.animation?.type) {
    case "slow_zoom_in":
      scale = interpolate(progress, [0, 1], [1, 1.14]);
      break;

    case "slow_zoom_out":
      scale = interpolate(progress, [0, 1], [1.14, 1]);
      break;

    case "pan_left":
      scale = 1.12;
      translateX = interpolate(progress, [0, 1], [25, -25]);
      break;

    case "pan_right":
      scale = 1.12;
      translateX = interpolate(progress, [0, 1], [-25, 25]);
      break;

    default:
      scale = 1.04;
  }

  const slideY =
    scene.transition === "slide"
      ? interpolate(frame, [0, Math.min(20, durationInFrames)], [70, 0], {
          extrapolateRight: "clamp",
        })
      : 0;

  return (
    <AbsoluteFill style={{ backgroundColor: "#071522", opacity }}>
      {scene.audio_src ? <Audio src={scene.audio_src} /> : null}

      <AbsoluteFill
        style={{
          transform: `translate(${translateX}px, ${slideY}px) scale(${scale})`,
        }}
      >
        {scene.visual_type === "video" ? (
          <OffthreadVideo
            src={scene.src}
            volume={0}
            style={{
              width: "100%",
              height: "100%",
              objectFit: "cover",
            }}
          />
        ) : (
          <Img
            src={scene.src}
            style={{
              width: "100%",
              height: "100%",
              objectFit: "cover",
            }}
          />
        )}
      </AbsoluteFill>

      {scene.beat === "cta" ? (
        <EndCard
          scene={scene}
          brand={brand}
          brandName={brandName}
          accentColor={accentColor}
        />
      ) : (
        <>
          <AbsoluteFill
            style={{
              background:
                "linear-gradient(180deg, rgba(0,0,0,0.05) 35%, rgba(0,0,0,0.72) 100%)",
              justifyContent: "flex-end",
              padding: 80,
            }}
          >
            {scene.on_screen_text && (
              <div
                style={{
                  color: "white",
                  fontFamily: "Arial, sans-serif",
                  fontSize: 68,
                  lineHeight: 1.15,
                  fontWeight: 800,
                  maxWidth: "90%",
                  marginBottom: 35,
                  textShadow: "0 3px 15px rgba(0,0,0,0.5)",
                }}
              >
                {scene.on_screen_text}
              </div>
            )}

            <div
              style={{
                width: 100,
                height: 7,
                backgroundColor: accentColor,
                borderRadius: 5,
              }}
            />
          </AbsoluteFill>

          {brand?.logo_src && <LogoWatermark src={brand.logo_src} />}
        </>
      )}
    </AbsoluteFill>
  );
};

export const DynamicVideo: React.FC<DynamicVideoProps> = ({
  scenes,
  accent_color,
  brand,
  brand_name,
}) => {
  let currentFrame = 0;
  const { fps } = useVideoConfig();

  return (
    <AbsoluteFill style={{ backgroundColor: "#071522" }}>
      {scenes.map((scene) => {
        const from = currentFrame;
        const durationInFrames = scene.duration_seconds * fps;

        currentFrame += durationInFrames;

        return (
          <Sequence
            key={scene.scene_number}
            from={from}
            durationInFrames={durationInFrames}
          >
            <Scene
              scene={scene}
              accentColor={accent_color}
              brand={brand}
              brandName={brand?.name || brand_name}
            />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
