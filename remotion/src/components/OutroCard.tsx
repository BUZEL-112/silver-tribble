import React from "react";
import { spring, useCurrentFrame, useVideoConfig } from "remotion";

interface OutroCardProps {
  aspectRatio: "9:16" | "16:9";
}

export const OutroCard: React.FC<OutroCardProps> = ({ aspectRatio }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const isVertical = aspectRatio === "9:16";

  const scale = spring({
    frame,
    fps,
    config: {
      damping: 12,
      mass: 0.8,
    },
  });

  return (
    <div
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        alignItems: "center",
        backgroundColor: "rgba(10, 15, 29, 0.85)",
        backdropFilter: "blur(16px)",
        zIndex: 30,
        transform: `scale(${scale})`,
      }}
    >
      <div
        style={{
          textAlign: "center",
          padding: isVertical ? "0 40px" : "0 80px",
        }}
      >
        <div
          style={{
            fontSize: isVertical ? "56px" : "44px",
            fontWeight: 900,
            color: "#ffffff",
            textTransform: "uppercase",
            letterSpacing: "2px",
            marginBottom: "20px",
            fontFamily: "'Inter', system-ui, sans-serif",
          }}
        >
          STAY CURIOUS. STAY SKEPTICAL.
        </div>

        <div
          style={{
            fontSize: isVertical ? "28px" : "22px",
            color: "#94a3b8",
            marginBottom: "36px",
            fontFamily: "'Inter', system-ui, sans-serif",
          }}
        >
          The fastest daily breakdown of actual AI engineering without the marketing spin.
        </div>

        <div
          style={{
            display: "inline-block",
            backgroundColor: "#e11d48",
            color: "#ffffff",
            padding: isVertical ? "18px 48px" : "14px 40px",
            borderRadius: "50px",
            fontSize: isVertical ? "28px" : "22px",
            fontWeight: 900,
            textTransform: "uppercase",
            letterSpacing: "1.5px",
            boxShadow: "0 0 30px rgba(225, 29, 72, 0.6)",
          }}
        >
          SUBSCRIBE
        </div>
      </div>
    </div>
  );
};
