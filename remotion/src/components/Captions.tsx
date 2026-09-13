import React from "react";
import { WordCaption } from "../types";

interface CaptionsProps {
  captions: WordCaption[];
  currentTime: number;
  aspectRatio: "9:16" | "16:9";
}

export const Captions: React.FC<CaptionsProps> = ({
  captions,
  currentTime,
  aspectRatio,
}) => {
  if (!captions || captions.length === 0) {
    return null;
  }

  // Find index of currently active word
  const activeIndex = captions.findIndex(
    (c) => currentTime >= c.start && currentTime <= c.end
  );

  // If no word is currently active, find the closest upcoming or recent word
  const currentIndex =
    activeIndex !== -1
      ? activeIndex
      : captions.findIndex((c) => c.start > currentTime);

  const targetIndex = currentIndex !== -1 ? currentIndex : captions.length - 1;

  // Window of words: 2 before, active word, 2 after
  const windowSize = aspectRatio === "9:16" ? 4 : 6;
  const startIndex = Math.max(0, targetIndex - 2);
  const visibleWords = captions.slice(startIndex, startIndex + windowSize);

  const isVertical = aspectRatio === "9:16";

  return (
    <div
      style={{
        position: "absolute",
        bottom: isVertical ? "30%" : "15%",
        left: "5%",
        right: "5%",
        display: "flex",
        flexWrap: "wrap",
        justifyContent: "center",
        alignItems: "center",
        gap: isVertical ? "12px" : "16px",
        zIndex: 20,
        pointerEvents: "none",
      }}
    >
      {visibleWords.map((c, idx) => {
        const isActive = currentTime >= c.start && currentTime <= c.end;
        const isPast = currentTime > c.end;

        return (
          <span
            key={`${c.word}-${c.start}-${idx}`}
            style={{
              fontFamily: "'Inter', system-ui, -apple-system, sans-serif",
              fontSize: isVertical ? "48px" : "42px",
              fontWeight: 900,
              textTransform: "uppercase",
              letterSpacing: "1px",
              color: isActive ? "#fde047" : isPast ? "#94a3b8" : "#ffffff",
              backgroundColor: isActive ? "rgba(0, 0, 0, 0.75)" : "rgba(0, 0, 0, 0.4)",
              padding: isVertical ? "6px 16px" : "4px 14px",
              borderRadius: "8px",
              transform: isActive ? "scale(1.12)" : "scale(1.0)",
              transition: "transform 0.08s ease-out",
              border: isActive ? "2px solid #facc15" : "1px solid rgba(255,255,255,0.1)",
              textShadow: "0 4px 12px rgba(0,0,0,0.8)",
            }}
          >
            {c.word}
          </span>
        );
      })}
    </div>
  );
};
