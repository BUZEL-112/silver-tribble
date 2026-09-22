import React from "react";
import { spring, useCurrentFrame, useVideoConfig } from "remotion";

interface OutroCardProps {
  aspectRatio: "9:16" | "16:9";
  subscribeTitle?: string;
  subscribeSubtitle?: string;
  subscribeButtonText?: string;
  subscribeStyle?: "card" | "lower_third" | "minimal_badge";
}

export const OutroCard: React.FC<OutroCardProps> = ({
  aspectRatio,
  subscribeTitle = "SUBSCRIBE FOR DAILY AI UPDATES",
  subscribeSubtitle = "@AINewsDesk | Engineering First",
  subscribeButtonText = "SUBSCRIBE",
  subscribeStyle = "card",
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const isVertical = aspectRatio === "9:16";

  const scale = spring({
    frame,
    fps,
    config: {
      damping: 14,
      mass: 0.9,
    },
  });

  if (subscribeStyle === "lower_third") {
    return (
      <div
        style={{
          position: "absolute",
          bottom: isVertical ? "40px" : "32px",
          left: isVertical ? "24px" : "48px",
          right: isVertical ? "24px" : "48px",
          backgroundColor: "rgba(10, 10, 10, 0.95)",
          border: "1px solid #3f3f46",
          borderRadius: "2px",
          padding: isVertical ? "20px 24px" : "18px 36px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          zIndex: 70,
          transform: `scale(${scale})`,
        }}
      >
        <div style={{ textAlign: "left" }}>
          <div
            style={{
              fontSize: isVertical ? "28px" : "24px",
              fontWeight: 900,
              color: "#ffffff",
              textTransform: "uppercase",
              letterSpacing: "1px",
              fontFamily: "'Inter', system-ui, sans-serif",
            }}
          >
            {subscribeTitle}
          </div>
          <div
            style={{
              fontSize: isVertical ? "18px" : "16px",
              color: "#a1a1aa",
              fontFamily: "'Inter', system-ui, sans-serif",
              marginTop: "4px",
            }}
          >
            {subscribeSubtitle}
          </div>
        </div>
        <div
          style={{
            backgroundColor: "#ffffff",
            color: "#000000",
            padding: isVertical ? "12px 28px" : "12px 32px",
            borderRadius: "2px",
            fontSize: isVertical ? "20px" : "18px",
            fontWeight: 900,
            textTransform: "uppercase",
            letterSpacing: "1.5px",
            fontFamily: "'Inter', system-ui, sans-serif",
            border: "1px solid #ffffff",
          }}
        >
          {subscribeButtonText}
        </div>
      </div>
    );
  }

  if (subscribeStyle === "minimal_badge") {
    return (
      <div
        style={{
          position: "absolute",
          bottom: isVertical ? "80px" : "40px",
          right: isVertical ? "32px" : "48px",
          backgroundColor: "#000000",
          border: "1px solid #ffffff",
          borderRadius: "2px",
          padding: "16px 28px",
          display: "flex",
          alignItems: "center",
          gap: "16px",
          zIndex: 70,
          transform: `scale(${scale})`,
        }}
      >
        <div style={{ textAlign: "left" }}>
          <div
            style={{
              fontSize: "18px",
              fontWeight: 900,
              color: "#ffffff",
              textTransform: "uppercase",
            }}
          >
            {subscribeTitle}
          </div>
          <div style={{ fontSize: "13px", color: "#a1a1aa" }}>{subscribeSubtitle}</div>
        </div>
        <div
          style={{
            backgroundColor: "#ffffff",
            color: "#000000",
            padding: "8px 18px",
            borderRadius: "2px",
            fontSize: "14px",
            fontWeight: 900,
            textTransform: "uppercase",
          }}
        >
          {subscribeButtonText}
        </div>
      </div>
    );
  }

  // Default: Full End Card
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
        backgroundColor: "rgba(10, 10, 10, 0.94)",
        backdropFilter: "blur(14px)",
        zIndex: 70,
      }}
    >
      {!isVertical ? (
        // 16:9 Horizontal YouTube End Screen Layout
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: "48px",
            width: "85%",
            transform: `scale(${scale})`,
          }}
        >
          {/* Left placeholder for YouTube recommended video */}
          <div
            style={{
              flex: 1,
              height: "360px",
              backgroundColor: "#121212",
              border: "1px dashed #3f3f46",
              borderRadius: "2px",
              display: "flex",
              flexDirection: "column",
              justifyContent: "center",
              alignItems: "center",
              color: "#71717a",
              fontFamily: "'Inter', system-ui, sans-serif",
            }}
          >
            <div style={{ fontSize: "14px", fontWeight: 700, letterSpacing: "1px" }}>
              [ YOUTUBE RECOMMENDED VIDEO ]
            </div>
            <div style={{ fontSize: "12px", color: "#52525b", marginTop: "6px" }}>
              Next Story in Queue
            </div>
          </div>

          {/* Right subscribe call to action */}
          <div
            style={{
              flex: 1,
              backgroundColor: "#0d0d0d",
              border: "1px solid #27272a",
              borderRadius: "2px",
              padding: "44px 36px",
              textAlign: "center",
            }}
          >
            <div
              style={{
                fontSize: "36px",
                fontWeight: 900,
                color: "#ffffff",
                textTransform: "uppercase",
                letterSpacing: "1.5px",
                marginBottom: "14px",
                fontFamily: "'Inter', system-ui, sans-serif",
              }}
            >
              {subscribeTitle}
            </div>

            <div
              style={{
                fontSize: "18px",
                color: "#a1a1aa",
                marginBottom: "32px",
                fontFamily: "'Inter', system-ui, sans-serif",
              }}
            >
              {subscribeSubtitle}
            </div>

            <div
              style={{
                display: "inline-block",
                backgroundColor: "#ffffff",
                color: "#000000",
                padding: "16px 44px",
                borderRadius: "2px",
                fontSize: "20px",
                fontWeight: 900,
                textTransform: "uppercase",
                letterSpacing: "1.5px",
                fontFamily: "'Inter', system-ui, sans-serif",
                border: "1px solid #ffffff",
              }}
            >
              {subscribeButtonText}
            </div>
          </div>
        </div>
      ) : (
        // 9:16 Vertical Shorts End Screen Layout
        <div
          style={{
            textAlign: "center",
            padding: "0 36px",
            width: "90%",
            transform: `scale(${scale})`,
          }}
        >
          <div
            style={{
              backgroundColor: "#0d0d0d",
              border: "1px solid #27272a",
              borderRadius: "2px",
              padding: "48px 32px",
            }}
          >
            <div
              style={{
                fontSize: "44px",
                fontWeight: 900,
                color: "#ffffff",
                textTransform: "uppercase",
                letterSpacing: "1.5px",
                marginBottom: "16px",
                fontFamily: "'Inter', system-ui, sans-serif",
                lineHeight: 1.15,
              }}
            >
              {subscribeTitle}
            </div>

            <div
              style={{
                fontSize: "22px",
                color: "#a1a1aa",
                marginBottom: "36px",
                fontFamily: "'Inter', system-ui, sans-serif",
                lineHeight: 1.3,
              }}
            >
              {subscribeSubtitle}
            </div>

            <div
              style={{
                display: "inline-block",
                backgroundColor: "#ffffff",
                color: "#000000",
                padding: "18px 48px",
                borderRadius: "2px",
                fontSize: "24px",
                fontWeight: 900,
                textTransform: "uppercase",
                letterSpacing: "2px",
                fontFamily: "'Inter', system-ui, sans-serif",
                border: "1px solid #ffffff",
              }}
            >
              {subscribeButtonText}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
