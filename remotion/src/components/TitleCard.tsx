import React from "react";
import { spring, useCurrentFrame, useVideoConfig } from "remotion";

interface TitleCardProps {
  title: string;
  onScreenText: string;
  aspectRatio: "9:16" | "16:9";
  beatType?: string;
}

export const TitleCard: React.FC<TitleCardProps> = ({
  title,
  onScreenText,
  aspectRatio,
  beatType = "context",
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const isVertical = aspectRatio === "9:16";

  const slideIn = spring({
    frame,
    fps,
    config: {
      damping: 14,
      stiffness: 120,
    },
  });

  return (
    <div
      style={{
        position: "absolute",
        top: isVertical ? "12%" : "8%",
        left: isVertical ? "6%" : "5%",
        right: isVertical ? "6%" : "5%",
        zIndex: 15,
        transform: `translateY(${(1 - slideIn) * -40}px)`,
        opacity: slideIn,
      }}
    >
      {/* Top Channel Badge */}
      <div
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: "8px",
          backgroundColor: "#0284c7",
          color: "#ffffff",
          padding: "6px 14px",
          borderRadius: "6px",
          fontSize: isVertical ? "20px" : "16px",
          fontWeight: 800,
          textTransform: "uppercase",
          letterSpacing: "1.5px",
          marginBottom: "12px",
          boxShadow: "0 4px 14px rgba(2,132,199,0.4)",
        }}
      >
        <span
          style={{
            width: "10px",
            height: "10px",
            borderRadius: "50%",
            backgroundColor: "#22c55e",
            display: "inline-block",
          }}
        />
        AI NEWS BY ESWAR
      </div>

      {/* Main Kinetic Headline Box */}
      <div
        style={{
          backgroundColor: "rgba(15, 23, 42, 0.9)",
          borderLeft: "6px solid #38bdf8",
          borderTop: "1px solid rgba(255,255,255,0.1)",
          borderRight: "1px solid rgba(255,255,255,0.1)",
          borderBottom: "1px solid rgba(255,255,255,0.1)",
          borderRadius: "8px",
          padding: isVertical ? "20px 24px" : "18px 24px",
          backdropFilter: "blur(12px)",
          boxShadow: "0 10px 30px rgba(0, 0, 0, 0.6)",
        }}
      >
        <div
          style={{
            color: "#f8fafc",
            fontFamily: "'Inter', system-ui, sans-serif",
            fontSize: isVertical ? "32px" : "26px",
            fontWeight: 800,
            lineHeight: 1.25,
            marginBottom: "6px",
          }}
        >
          {title}
        </div>

        {onScreenText && (
          <div
            style={{
              color: "#38bdf8",
              fontFamily: "'Inter', system-ui, sans-serif",
              fontSize: isVertical ? "22px" : "18px",
              fontWeight: 700,
              textTransform: "uppercase",
              letterSpacing: "1.2px",
            }}
          >
            {onScreenText}
          </div>
        )}
      </div>
    </div>
  );
};
