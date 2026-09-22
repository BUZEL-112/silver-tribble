import React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { WatermarkConfig } from "../types";

interface WatermarkProps {
  config?: WatermarkConfig;
}

export const Watermark: React.FC<WatermarkProps> = ({ config }) => {
  const frame = useCurrentFrame();

  if (!config || (!config.text && !config.image_path)) {
    return null;
  }

  const targetOpacity = config.opacity ?? 0.8;
  const opacity = interpolate(frame, [0, 15], [0, targetOpacity], {
    extrapolateRight: "clamp",
  });

  const position = config.position || "top-right";

  const positionStyle: React.CSSProperties = {
    position: "absolute",
    zIndex: 50,
    pointerEvents: "none",
    opacity,
    display: "flex",
    alignItems: "center",
    gap: "8px",
    padding: "6px 14px",
    backgroundColor: "rgba(0, 0, 0, 0.85)",
    backdropFilter: "blur(4px)",
    borderRadius: "2px",
    border: "1px solid #3f3f46",
  };

  switch (position) {
    case "top-left":
      positionStyle.top = "32px";
      positionStyle.left = "32px";
      break;
    case "bottom-left":
      positionStyle.bottom = "40px";
      positionStyle.left = "32px";
      break;
    case "bottom-right":
      positionStyle.bottom = "40px";
      positionStyle.right = "32px";
      break;
    case "top-right":
    default:
      positionStyle.top = "32px";
      positionStyle.right = "32px";
      break;
  }

  return (
    <div style={positionStyle}>
      {config.image_path && (
        <img
          src={config.image_path}
          alt="Watermark Logo"
          style={{ height: "24px", width: "auto", objectFit: "contain" }}
        />
      )}
      {config.text && (
        <span
          style={{
            color: "#ffffff",
            fontFamily: "'Inter', system-ui, -apple-system, sans-serif",
            fontSize: "16px",
            fontWeight: 700,
            letterSpacing: "0.5px",
            textShadow: "0 2px 4px rgba(0,0,0,0.6)",
          }}
        >
          {config.text}
        </span>
      )}
    </div>
  );
};
