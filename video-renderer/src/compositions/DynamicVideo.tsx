import React from "react";

import {
  AbsoluteFill,
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

export type DynamicVideoProps = {
  title: string;
  brand_name: string;
  accent_color: string;
  fps: number;
  width: number;
  height: number;
  duration_seconds: number;
  scenes: DynamicScene[];
};

const Scene: React.FC<{
  scene: DynamicScene;
  accentColor: string;
}> = ({ scene, accentColor }) => {
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
    </AbsoluteFill>
  );
};

export const DynamicVideo: React.FC<DynamicVideoProps> = ({
  scenes,
  accent_color,
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
            <Scene scene={scene} accentColor={accent_color} />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
