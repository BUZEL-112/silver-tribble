import React from "react";
import { Audio, Img, Sequence, useCurrentFrame, useVideoConfig, Video } from "remotion";
import { AnimatedBackground } from "../components/AnimatedBackground";
import { Captions } from "../components/Captions";
import { OutroCard } from "../components/OutroCard";
import { TitleCard } from "../components/TitleCard";
import { Watermark } from "../components/Watermark";
import { RenderProps } from "../types";

export const MainVideo: React.FC<RenderProps> = ({
  videoTitle,
  aspectRatio,
  audioPath,
  beats = [],
  captions = [],
  watermark,
  mediaPlacements = [],
  introDelaySeconds = 0,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const currentTime = frame / fps;

  // Find active beat for current timestamp
  const currentBeat =
    beats.find((b) => currentTime >= b.start_time && currentTime < b.end_time) ||
    beats[beats.length - 1];

  const isOutro = currentBeat?.beat_type === "outro";

  // Find active sentence media for current timestamp
  const activeMedia = mediaPlacements.find(
    (m) => currentTime >= m.start_time && currentTime < m.end_time && m.local_path
  );

  const audioStartFrame = Math.max(0, Math.round((introDelaySeconds || 0) * fps));

  return (
    <div
      style={{
        position: "relative",
        width: "100%",
        height: "100%",
        backgroundColor: "#05070c",
        overflow: "hidden",
      }}
    >
      {/* Voice Narration Audio with intro offset delay */}
      {audioPath && (
        <Sequence from={audioStartFrame}>
          <Audio src={audioPath} />
        </Sequence>
      )}

      {/* Procedural Animated Background */}
      <AnimatedBackground
        aspectRatio={aspectRatio}
        beatType={currentBeat?.beat_type || "context"}
      />

      {/* Sentence-Level Visual Media (Pexels / Giphy) */}
      {activeMedia && activeMedia.local_path && (
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            width: "100%",
            height: "100%",
            zIndex: 6,
            opacity: 0.88,
          }}
        >
          {activeMedia.media_type === "video" ? (
            <Video
              src={activeMedia.local_path}
              style={{
                width: "100%",
                height: "100%",
                objectFit: "cover",
              }}
            />
          ) : (
            <Img
              src={activeMedia.local_path}
              style={{
                width: "100%",
                height: "100%",
                objectFit: "cover",
              }}
            />
          )}
        </div>
      )}

      {/* Stock or Generated B-Roll Video Clip when present and no active sentence media */}
      {!activeMedia && currentBeat?.broll_video_path && (
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            width: "100%",
            height: "100%",
            zIndex: 5,
            opacity: 0.85,
          }}
        >
          <Video
            src={currentBeat.broll_video_path}
            style={{
              width: "100%",
              height: "100%",
              objectFit: "cover",
            }}
          />
        </div>
      )}

      {/* Watermark Overlay */}
      {watermark && <Watermark config={watermark} />}

      {/* Dynamic Title and Lower-Third Card */}
      {!isOutro && (
        <TitleCard
          title={videoTitle}
          onScreenText={currentBeat?.on_screen_text || ""}
          aspectRatio={aspectRatio}
          beatType={currentBeat?.beat_type}
        />
      )}

      {/* Synchronized Word-Level Kinetic Captions */}
      {!isOutro && (
        <Captions
          captions={captions}
          currentTime={currentTime}
          aspectRatio={aspectRatio}
        />
      )}

      {/* Final Call to Action Card */}
      {isOutro && <OutroCard aspectRatio={aspectRatio} />}
    </div>
  );
};
