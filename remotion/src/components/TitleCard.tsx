import React from "react";
import { spring, useCurrentFrame, useVideoConfig } from "remotion";

interface TitleCardProps {
  title: string;
  onScreenText: string;
  aspectRatio: "9:16" | "16:9";
  beatType?: string;
  channelBadgeText?: string;
}

export const TitleCard: React.FC<TitleCardProps> = ({
  title,
  onScreenText,
  aspectRatio,
  beatType = "context",
  channelBadgeText = "AI NEWS BY ESWAR",
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
        top: isVertical ? "10%" : "6%",
        left: isVertical ? "6%" : "6%",
        right: isVertical ? "6%" : "6%",
        zIndex: 50,
        transform: `translateY(${(1 - slideIn) * -30}px)`,
        opacity: slideIn,
      }}
    >
      {/* Top Channel Badge */}
      <div
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: "8px",
          backgroundColor: "#ffffff",
          color: "#000000",
          padding: "5px 12px",
          borderRadius: "2px",
          fontSize: isVertical ? "18px" : "15px",
          fontWeight: 900,
          textTransform: "uppercase",
          letterSpacing: "1.2px",
          marginBottom: "10px",
          border: "1px solid #ffffff",
        }}
      >
        <span
          style={{
            width: "8px",
            height: "8px",
            borderRadius: "0px",
            backgroundColor: "#000000",
            display: "inline-block",
          }}
        />
        {channelBadgeText}
      </div>

      {/* Main Kinetic Headline Box */}
      <div
        style={{
          backgroundColor: "rgba(10, 10, 10, 0.95)",
          borderLeft: "4px solid #ffffff",
          borderTop: "1px solid #27272a",
          borderRight: "1px solid #27272a",
          borderBottom: "1px solid #27272a",
          borderRadius: "2px",
          padding: isVertical ? "18px 22px" : "16px 22px",
          backdropFilter: "blur(12px)",
        }}
      >
        <div
          style={{
            color: "#ffffff",
            fontFamily: "'Inter', system-ui, sans-serif",
            fontSize: isVertical ? "30px" : "24px",
            fontWeight: 900,
            lineHeight: 1.25,
            marginBottom: onScreenText ? "6px" : "0px",
            letterSpacing: "0.2px",
          }}
        >
          {title}
        </div>

        {onScreenText && (
          <div
            style={{
              color: "#a1a1aa",
              fontFamily: "'Inter', system-ui, sans-serif",
              fontSize: isVertical ? "20px" : "16px",
              fontWeight: 700,
              textTransform: "uppercase",
              letterSpacing: "1px",
            }}
          >
            {onScreenText}
          </div>
        )}
      </div>
    </div>
  );
};
