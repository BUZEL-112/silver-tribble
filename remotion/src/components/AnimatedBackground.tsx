import React from "react";
import { interpolate, useCurrentFrame } from "remotion";

interface AnimatedBackgroundProps {
  aspectRatio: "9:16" | "16:9";
  beatType?: string;
}

export const AnimatedBackground: React.FC<AnimatedBackgroundProps> = ({
  aspectRatio,
  beatType = "context",
}) => {
  const frame = useCurrentFrame();

  const isVertical = aspectRatio === "9:16";

  // Cycle gradient angle slowly
  const angle = interpolate(frame, [0, 900], [0, 360], {
    extrapolateRight: "clamp",
  });

  // Pulse glow scale
  const glowScale = interpolate(
    Math.sin(frame / 20),
    [-1, 1],
    [0.9, 1.15]
  );

  // Dynamic tint based on beat type
  const getAccentColor = (type: string) => {
    switch (type) {
      case "hook":
        return "#f43f5e"; // Rose
      case "breakthrough":
        return "#06b6d4"; // Cyan
      case "skepticism":
        return "#f59e0b"; // Amber
      case "outro":
        return "#8b5cf6"; // Violet
      default:
        return "#3b82f6"; // Blue
    }
  };

  const accent = getAccentColor(beatType);

  return (
    <div
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        width: "100%",
        height: "100%",
        backgroundColor: "#090d16",
        overflow: "hidden",
        zIndex: 0,
      }}
    >
      {/* Dynamic Radial Glow */}
      <div
        style={{
          position: "absolute",
          top: "30%",
          left: "50%",
          width: isVertical ? "700px" : "1200px",
          height: isVertical ? "700px" : "1200px",
          transform: `translate(-50%, -50%) scale(${glowScale})`,
          borderRadius: "50%",
          background: `radial-gradient(circle, ${accent}33 0%, #1e1b4b11 50%, transparent 75%)`,
          filter: "blur(70px)",
        }}
      />

      {/* Cyber Grid Pattern */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          width: "200%",
          height: "200%",
          backgroundImage: `linear-gradient(to right, rgba(255,255,255,0.03) 1px, transparent 1px),
                            linear-gradient(to bottom, rgba(255,255,255,0.03) 1px, transparent 1px)`,
          backgroundSize: isVertical ? "60px 60px" : "80px 80px",
          transform: `translate(-15%, -15%) rotate(${angle * 0.05}deg)`,
        }}
      />

      {/* Vignette Overlay */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          width: "100%",
          height: "100%",
          background: "radial-gradient(circle at center, transparent 40%, rgba(5,7,12,0.85) 90%)",
        }}
      />
    </div>
  );
};
