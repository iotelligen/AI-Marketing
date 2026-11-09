import React from "react";
import { Composition } from "remotion";

import { IndustrialPromo } from "./IndustrialPromo";
import {
  DynamicVideo,
  type DynamicVideoProps,
} from "./DynamicVideo";

const calculateDynamicMetadata = ({
  props,
}: {
  props: DynamicVideoProps;
}) => ({
  durationInFrames: props.duration_seconds * props.fps,
  fps: props.fps,
  width: props.width,
  height: props.height,
});

export const Root: React.FC = () => {
  return (
    <>
      <Composition
        id="IndustrialPromo"
        component={IndustrialPromo}
        durationInFrames={900}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{
          brandName: "IoTelliGen",
          title: "Make Your Factory Smarter",
          subtitle: "Monitor. Analyze. Optimize.",
          cta: "Discover Industrial IoT",
          accentColor: "#16C79A",
        }}
      />

      <Composition
        id="DynamicVideo"
        component={DynamicVideo}
        durationInFrames={900}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{
          title: "Industrial Video",
          brand_name: "IoTelliGen",
          accent_color: "#16C79A",
          fps: 30,
          width: 1080,
          height: 1920,
          duration_seconds: 30,
          scenes: [],
        }}
        calculateMetadata={calculateDynamicMetadata}
      />
    </>
  );
};
