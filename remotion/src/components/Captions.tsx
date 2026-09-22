import React from "react";
import { WordCaption } from "../types";

interface CaptionsProps {
  captions: WordCaption[];
  currentTime: number;
  aspectRatio: "9:16" | "16:9";
  captionStyle?: "hormozi" | "minimal" | "karaoke" | "news_ticker" | "cinematic";
  captionLevel?: number;
  captionFontSize?: number;
  captionUppercase?: boolean;
}

export const Captions: React.FC<CaptionsProps> = ({
  captions,
  currentTime,
  aspectRatio,
  captionStyle = "hormozi",
  captionLevel,
  captionFontSize,
  captionUppercase = true,
}) => {
  if (!captions || captions.length === 0) {
    return null;
  }

  // Find index of currently active word
  const activeIndex = captions.findIndex(
    (c) => currentTime >= c.start && currentTime <= c.end
  );

  // If no word is currently active, find closest upcoming or recent word
  const currentIndex =
    activeIndex !== -1
      ? activeIndex
      : captions.findIndex((c) => c.start > currentTime);

  const targetIndex = currentIndex !== -1 ? currentIndex : captions.length - 1;

  const isVertical = aspectRatio === "9:16";
  const windowSize = isVertical ? 4 : 6;
  const startIndex = Math.max(0, targetIndex - 2);
  const visibleWords = captions.slice(startIndex, startIndex + windowSize);

  // Dynamic vertical level (default: 30% for vertical shorts, 15% for horizontal landscape)
  const resolvedLevel = captionLevel ?? (isVertical ? 30 : 15);
  const baseFontSize = captionFontSize ?? (isVertical ? 48 : 40);

  const containerStyle: React.CSSProperties = {
    position: "absolute",
    bottom: `${resolvedLevel}%`,
    left: isVertical ? "6%" : "10%",
    right: isVertical ? "6%" : "10%",
    display: "flex",
    flexWrap: "wrap",
    justifyContent: "center",
    alignItems: "center",
    gap: isVertical ? "14px" : "18px",
    zIndex: 20,
    pointerEvents: "none",
  };

  if (captionStyle === "news_ticker") {
    containerStyle.backgroundColor = "rgba(10, 10, 10, 0.92)";
    containerStyle.border = "1px solid #27272a";
    containerStyle.borderRadius = "0px";
    containerStyle.padding = "10px 24px";
  }

  return (
    <div style={containerStyle}>
      {visibleWords.map((c, idx) => {
        const isActive = currentTime >= c.start && currentTime <= c.end;
        const isPast = currentTime > c.end;
        const cleanWord = c.word.replace(/^[^\w]+|[^\w]+$/g, "");
        const trailingPunct = c.word.match(/[.,!?;:]+$/)?.[0] || "";
        if (!cleanWord) return null;

        const displayedWord = captionUppercase ? cleanWord.toUpperCase() : cleanWord;

        let wordStyle: React.CSSProperties = {
          fontFamily:
            captionStyle === "cinematic"
              ? "Georgia, Cambria, 'Times New Roman', serif"
              : "'Inter', system-ui, -apple-system, sans-serif",
          fontSize: `${baseFontSize}px`,
          fontWeight: captionStyle === "cinematic" ? 700 : 900,
          textTransform: captionUppercase ? "uppercase" : "none",
          letterSpacing: captionStyle === "cinematic" ? "2px" : "0.5px",
          color: isActive ? "#ffffff" : isPast ? "#71717a" : "#a1a1aa",
          transition: "transform 0.08s ease-out",
        };

        if (captionStyle === "hormozi") {
          wordStyle = {
            ...wordStyle,
            backgroundColor: isActive ? "#000000" : "transparent",
            color: isActive ? "#ffffff" : isPast ? "#71717a" : "#d4d4d8",
            padding: isActive ? (isVertical ? "4px 14px" : "4px 12px") : "0px",
            borderRadius: "2px",
            border: isActive ? "1px solid #ffffff" : "1px solid transparent",
            transform: isActive ? "scale(1.10)" : "scale(1.0)",
            textShadow: "0 2px 8px rgba(0,0,0,0.8)",
          };
        } else if (captionStyle === "minimal") {
          wordStyle = {
            ...wordStyle,
            backgroundColor: "transparent",
            color: isActive ? "#ffffff" : isPast ? "#52525b" : "#a1a1aa",
            textShadow: "0 2px 10px rgba(0, 0, 0, 0.9)",
            transform: isActive ? "scale(1.06)" : "scale(1.0)",
          };
        } else if (captionStyle === "karaoke") {
          wordStyle = {
            ...wordStyle,
            color: isActive ? "#ffffff" : isPast ? "#52525b" : "#a1a1aa",
            borderBottom: isActive ? "3px solid #ffffff" : "3px solid transparent",
            paddingBottom: "2px",
            transform: isActive ? "scale(1.08)" : "scale(1.0)",
          };
        } else if (captionStyle === "news_ticker") {
          wordStyle = {
            ...wordStyle,
            fontSize: `${Math.round(baseFontSize * 0.85)}px`,
            color: isActive ? "#ffffff" : "#a1a1aa",
            fontWeight: 800,
            textShadow: "none",
          };
        } else if (captionStyle === "cinematic") {
          wordStyle = {
            ...wordStyle,
            color: isActive ? "#ffffff" : isPast ? "#52525b" : "#71717a",
            fontStyle: "italic",
            textShadow: "0 2px 12px rgba(0,0,0,0.9)",
          };
        }

        return (
          <span
            key={`${c.word}-${c.start}-${idx}`}
            style={{
              display: "inline-flex",
              alignItems: "baseline",
            }}
          >
            <span style={wordStyle}>
              {displayedWord}
              {!isActive && trailingPunct}
            </span>
            {trailingPunct && isActive && (
              <span
                style={{
                  fontFamily: wordStyle.fontFamily,
                  fontSize: `${baseFontSize}px`,
                  fontWeight: wordStyle.fontWeight,
                  color: "#ffffff",
                  marginLeft: "2px",
                }}
              >
                {trailingPunct}
              </span>
            )}
          </span>
        );
      })}
    </div>
  );
};
