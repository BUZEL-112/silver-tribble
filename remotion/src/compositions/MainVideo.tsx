import React from "react";
import { Audio, Img, Sequence, staticFile, useCurrentFrame, useVideoConfig, Video } from "remotion";
import { AnimatedBackground } from "../components/AnimatedBackground";
import { Captions } from "../components/Captions";
import { OutroCard } from "../components/OutroCard";
import { TitleCard } from "../components/TitleCard";
import { Watermark } from "../components/Watermark";
import { RenderProps } from "../types";

export const resolveMediaSrc = (pathOrUrl?: string): string => {
  if (!pathOrUrl) return "";
  if (
    pathOrUrl.startsWith("http://") ||
    pathOrUrl.startsWith("https://") ||
    pathOrUrl.startsWith("data:") ||
    pathOrUrl.startsWith("blob:")
  ) {
    return pathOrUrl;
  }
  const filename = pathOrUrl.split("/").pop();
  if (filename) {
    return staticFile(`media/${filename}`);
  }
  return pathOrUrl;
};

export const MainVideo: React.FC<RenderProps> = ({
  videoTitle,
  aspectRatio,
  audioPath,
  beats = [],
  captions = [],
  watermark,
  mediaPlacements = [],
  durationInSeconds = 30,
  introDelaySeconds = 0,
  outroDurationSeconds = 3.5,
  channelBadgeText = "AI NEWS BY ESWAR",
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const currentTime = frame / fps;

  // Spoken narration timeline
  const lastCaption = captions.length > 0 ? captions[captions.length - 1] : null;
  const lastCaptionEnd = lastCaption ? lastCaption.end : Math.max(0, durationInSeconds - outroDurationSeconds);

  // Outro card displays only after spoken voiceover completes
  const isOutroCardVisible = currentTime >= (lastCaptionEnd + 0.2);

  // Find active beat for current timestamp
  const currentBeat =
    beats.find((b) => currentTime >= b.start_time && currentTime < b.end_time) ||
    beats[beats.length - 1];

  const audioStartFrame = Math.max(0, Math.round((introDelaySeconds || 0) * fps));

  // Voice narration activity for background music ducking
  const isNarrationSpeaking =
    currentTime >= (introDelaySeconds || 0) && currentTime <= (lastCaptionEnd + 0.3);

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
      {/* Ambient Background Music Bed with Voice Ducking */}
      <Audio
        src={staticFile("music/tech_ambient.mp3")}
        volume={() => {
          if (currentTime > durationInSeconds - 2.0) {
            const fadeRatio = Math.max(0, (durationInSeconds - currentTime) / 2.0);
            return 0.22 * fadeRatio;
          }
          return isNarrationSpeaking ? 0.09 : 0.22;
        }}
        loop
      />

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

      {/* Visual Media Tracks with frame buffering and zero-gap overlap */}
      {mediaPlacements.map((m, idx) => {
        const fromFrame = Math.max(0, Math.round(m.start_time * fps));
        // Give 4 frames overlap so outgoing video never unmounts before incoming video displays
        const durationFrames = Math.max(
          1,
          Math.round((m.end_time - m.start_time) * fps) + 4
        );
        const mediaSrc = resolveMediaSrc(m.local_path || m.source_url);
        if (!mediaSrc) return null;

        return (
          <Sequence
            key={`media-seq-${idx}-${m.local_path || m.source_url}`}
            from={fromFrame}
            durationInFrames={durationFrames}
            style={{
              zIndex: 6 + idx,
              position: "absolute",
              top: 0,
              left: 0,
              width: "100%",
              height: "100%",
              overflow: "hidden",
            }}
          >
            {m.media_type === "video" ? (
              <>
                {/* Blurred background expansion for video */}
                <Video
                  src={mediaSrc}
                  style={{
                    position: "absolute",
                    top: "-5%",
                    left: "-5%",
                    width: "110%",
                    height: "110%",
                    objectFit: "cover",
                    filter: "blur(28px) brightness(0.5)",
                  }}
                />
                {/* Crisp foreground video */}
                <Video
                  src={mediaSrc}
                  style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    width: "100%",
                    height: "100%",
                    objectFit: "cover",
                  }}
                />
              </>
            ) : (
              <>
                {/* Blurred background expansion for GIFs / images */}
                <Img
                  src={mediaSrc}
                  style={{
                    position: "absolute",
                    top: "-5%",
                    left: "-5%",
                    width: "110%",
                    height: "110%",
                    objectFit: "cover",
                    filter: "blur(28px) brightness(0.5)",
                  }}
                />
                {/* Crisp foreground layer with uncropped contain fit */}
                <Img
                  src={mediaSrc}
                  style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    width: "100%",
                    height: "100%",
                    objectFit: "contain",
                  }}
                />
              </>
            )}
          </Sequence>
        );
      })}

      {/* Stock or Generated B-Roll Video Clip when present and no active media placements */}
      {mediaPlacements.length === 0 && currentBeat?.broll_video_path && (
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
            src={resolveMediaSrc(currentBeat.broll_video_path)}
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
      {!isOutroCardVisible && (
        <TitleCard
          title={videoTitle}
          onScreenText={currentBeat?.on_screen_text || ""}
          aspectRatio={aspectRatio}
          beatType={currentBeat?.beat_type}
          channelBadgeText={channelBadgeText}
        />
      )}

      {/* Synchronized Word-Level Kinetic Captions - always visible while speech is active */}
      {currentTime <= (lastCaptionEnd + 0.4) && (
        <Captions
          captions={captions}
          currentTime={currentTime}
          aspectRatio={aspectRatio}
        />
      )}

      {/* Final Call to Action Card - appears only after speech concludes */}
      {isOutroCardVisible && <OutroCard aspectRatio={aspectRatio} />}
    </div>
  );
};
