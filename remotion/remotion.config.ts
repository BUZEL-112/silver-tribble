import { Config } from "@remotion/cli/config";

Config.setVideoImageFormat("jpeg");
Config.setOverwriteOutput(true);
Config.setChromiumOpenGlRenderer("angle");

// Disable Chromium sandbox for container environments
if (typeof (Config as any).setChromiumSandbox !== "function") {
  (Config as any).setChromiumSandbox = (_sandbox: boolean) => {};
}
Config.setChromiumSandbox(false);

