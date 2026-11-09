
import React from "react";

import {
  AbsoluteFill,
  Sequence,
  interpolate,
  useCurrentFrame,
  useVideoConfig
} from "remotion";

type PromoProps = {
  brandName: string;
  title: string;
  subtitle: string;
  cta: string;
  accentColor: string;
};

const Scene: React.FC<{
  brandName: string;
  heading: string;
  description: string;
  accentColor: string;
  sceneNumber: number;
  final?: boolean;
}> = ({
  brandName,
  heading,
  description,
  accentColor,
  sceneNumber,
  final = false
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  const opacity = interpolate(
    frame,
    [0, 18, durationInFrames - 18, durationInFrames],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const translateY = interpolate(
    frame,
    [0, 25],
    [70, 0],
    { extrapolateRight: "clamp" }
  );

  const pulse = 1 + Math.sin(frame / 18) * 0.025;

  return (
    <AbsoluteFill
      style={{
        backgroundColor: "#071522",
        color: "white",
        fontFamily: "Arial, sans-serif",
        padding: 80,
        justifyContent: "center",
        opacity
      }}
    >
      <AbsoluteFill
        style={{
          background:
            "radial-gradient(circle at 80% 20%, #12443F 0%, transparent 45%)",
          opacity: 0.8
        }}
      />

      <div
        style={{
          position: "absolute",
          top: 90,
          left: 80,
          fontSize: 36,
          fontWeight: 800,
          color: accentColor
        }}
      >
        {brandName}
      </div>

      <div
        style={{
          position: "absolute",
          top: 160,
          left: 80,
          fontSize: 22,
          letterSpacing: 8,
          color: "#8BA8B5"
        }}
      >
        INDUSTRIAL INTELLIGENCE
      </div>

      <div
        style={{
          position: "absolute",
          right: 80,
          top: 90,
          fontSize: 26,
          color: "#66808F"
        }}
      >
        0{sceneNumber} / 05
      </div>

      <div
        style={{
          transform: `translateY(${translateY}px) scale(${pulse})`,
          zIndex: 2
        }}
      >
        <div
          style={{
            width: 120,
            height: 8,
            backgroundColor: accentColor,
            marginBottom: 55,
            borderRadius: 8
          }}
        />

        <div
          style={{
            fontSize: final ? 92 : 84,
            fontWeight: 800,
            lineHeight: 1.12,
            maxWidth: 900,
            marginBottom: 45
          }}
        >
          {heading}
        </div>

        <div
          style={{
            fontSize: 38,
            color: "#B5C7D1",
            lineHeight: 1.5,
            maxWidth: 850
          }}
        >
          {description}
        </div>
      </div>

      <div
        style={{
          position: "absolute",
          bottom: 100,
          left: 80,
          right: 80,
          height: 5,
          backgroundColor: "#263D4B",
          borderRadius: 5
        }}
      >
        <div
          style={{
            width: `${((frame + 1) / durationInFrames) * 100}%`,
            height: "100%",
            backgroundColor: accentColor,
            borderRadius: 5
          }}
        />
      </div>
    </AbsoluteFill>
  );
};

export const IndustrialPromo: React.FC<PromoProps> = ({
  brandName,
  title,
  subtitle,
  cta,
  accentColor
}) => {
  return (
    <AbsoluteFill>
      <Sequence from={0} durationInFrames={180}>
        <Scene
          brandName={brandName}
          heading={title}
          description={subtitle}
          accentColor={accentColor}
          sceneNumber={1}
        />
      </Sequence>

      <Sequence from={180} durationInFrames={180}>
        <Scene
          brandName={brandName}
          heading="Are You in Control?"
          description="Unexpected energy consumption and machine downtime can affect factory profitability."
          accentColor={accentColor}
          sceneNumber={2}
        />
      </Sequence>

      <Sequence from={360} durationInFrames={180}>
        <Scene
          brandName={brandName}
          heading="Connect Every Machine"
          description="Industrial sensors, energy meters and IoT gateways bring your factory data together."
          accentColor={accentColor}
          sceneNumber={3}
        />
      </Sequence>

      <Sequence from={540} durationInFrames={180}>
        <Scene
          brandName={brandName}
          heading="Turn Data Into Decisions"
          description="Monitor equipment, analyze energy consumption and identify operational inefficiencies."
          accentColor={accentColor}
          sceneNumber={4}
        />
      </Sequence>

      <Sequence from={720} durationInFrames={180}>
        <Scene
          brandName={brandName}
          heading={cta}
          description="Build a smarter, more efficient industrial operation with IoTelliGen."
          accentColor={accentColor}
          sceneNumber={5}
          final
        />
      </Sequence>
    </AbsoluteFill>
  );
};
