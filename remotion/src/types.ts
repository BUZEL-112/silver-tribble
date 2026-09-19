export interface WordCaption {
  word: string;
  start: number;
  end: number;
  confidence?: number;
}

export interface RenderBeatProp {
  beat_number: number;
  beat_type: string;
  on_screen_text: string;
  visual_direction: string;
  broll_video_path?: string | null;
  start_time: number;
  end_time: number;
}

export interface WatermarkConfig {
  text?: string;
  image_path?: string;
  position?: "top-right" | "top-left" | "bottom-right" | "bottom-left";
  opacity?: number;
}

export interface SentenceMediaItem {
  sentence_index: number;
  start_time: number;
  end_time: number;
  keywords: string[];
  media_type: "image" | "video" | "gif";
  local_path: string;
  source_url: string;
  provider: "pexels" | "giphy" | "fallback";
}

export interface RenderProps {
  videoTitle: string;
  aspectRatio: "9:16" | "16:9";
  audioPath: string;
  durationInSeconds: number;
  fps: number;
  beats: RenderBeatProp[];
  captions: WordCaption[];
  watermark?: WatermarkConfig;
  mediaPlacements?: SentenceMediaItem[];
  introDelaySeconds?: number;
  outroDurationSeconds?: number;
}
