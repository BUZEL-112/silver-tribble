import React from "react";
import { Composition } from "remotion";
import { MainVideo } from "./compositions/MainVideo";
import { RenderProps } from "./types";

const defaultSampleProps: RenderProps = {
  videoTitle: "GPT-5 Rumors Debunked: What OpenAI Actually Built",
  aspectRatio: "9:16",
  audioPath: "",
  durationInSeconds: 15,
  fps: 30,
  beats: [
    {
      beat_number: 1,
      beat_type: "hook",
      on_screen_text: "THE HYPE CYCLE RETURNS",
      visual_direction: "Glitch title card",
      start_time: 0,
      end_time: 5,
    },
    {
      beat_number: 2,
      beat_type: "context",
      on_screen_text: "WHAT THE BENCHMARKS SAY",
      visual_direction: "Data center server rack",
      start_time: 5,
      end_time: 10,
    },
    {
      beat_number: 3,
      beat_type: "outro",
      on_screen_text: "SUBSCRIBE FOR REALITY",
      visual_direction: "Signature outro card",
      start_time: 10,
      end_time: 15,
    },
  ],
  captions: [
    { word: "OpenAI", start: 0.5, end: 1.0 },
    { word: "just", start: 1.0, end: 1.3 },
    { word: "dropped", start: 1.3, end: 1.7 },
    { word: "another", start: 1.7, end: 2.1 },
    { word: "benchmark", start: 2.1, end: 2.8 },
    { word: "and", start: 2.8, end: 3.0 },
    { word: "everyone", start: 3.0, end: 3.5 },
    { word: "lost", start: 3.5, end: 3.8 },
    { word: "their", start: 3.8, end: 4.1 },
    { word: "minds.", start: 4.1, end: 4.8 },
    { word: "Let", start: 5.2, end: 5.4 },
    { word: "us", start: 5.4, end: 5.6 },
    { word: "look", start: 5.6, end: 5.9 },
    { word: "at", start: 5.9, end: 6.1 },
    { word: "the", start: 6.1, end: 6.3 },
    { word: "actual", start: 6.3, end: 6.8 },
    { word: "code.", start: 6.8, end: 7.5 },
  ],
};

export const RemotionRoot: React.FC = () => {
  return (
    <>
      {/* 9:16 Vertical Short Composition */}
      <Composition
        id="AiNewsVideoVertical"
        component={MainVideo}
        durationInFrames={450} // 15 seconds at 30 fps default
        fps={30}
        width={1080}
        height={1920}
        defaultProps={defaultSampleProps}
        calculateMetadata={({ props }) => {
          const duration = props.durationInSeconds || 15;
          const fps = props.fps || 30;
          return {
            durationInFrames: Math.max(Math.round(duration * fps), 30),
            fps,
          };
        }}
      />

      {/* 16:9 Horizontal Widescreen Composition */}
      <Composition
        id="AiNewsVideoHorizontal"
        component={MainVideo}
        durationInFrames={450}
        fps={30}
        width={1920}
        height={1080}
        defaultProps={{
          ...defaultSampleProps,
          aspectRatio: "16:9",
        }}
        calculateMetadata={({ props }) => {
          const duration = props.durationInSeconds || 15;
          const fps = props.fps || 30;
          return {
            durationInFrames: Math.max(Math.round(duration * fps), 30),
            fps,
          };
        }}
      />
    </>
  );
};
