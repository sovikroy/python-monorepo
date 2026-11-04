// Render docs/demo/player.html to docs/demo.mp4 and docs/demo.gif.
//
//   node docs/demo/record.mjs            # needs playwright (Chromium) and ffmpeg
//
// Frames are rendered deterministically via window.seek(t), so the result does
// not depend on how fast the machine is.
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const here = dirname(fileURLToPath(import.meta.url));
const docs = dirname(here);
const FPS = 15;
const frames = mkdtempSync(join(tmpdir(), "demo-frames-"));

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 960, height: 600 }, deviceScaleFactor: 2 });
await page.goto(pathToFileURL(join(here, "player.html")).href + "?record");
await page.evaluate(() => document.fonts.ready);
const duration = await page.evaluate(() => window.DURATION);
const total = Math.ceil(duration * FPS);
for (let i = 0; i < total; i++) {
  await page.evaluate((t) => window.seek(t), i / FPS);
  await page.screenshot({ path: join(frames, `f${String(i).padStart(5, "0")}.png`) });
}
await browser.close();
console.log(`rendered ${total} frames (${duration.toFixed(1)}s)`);

const input = ["-y", "-loglevel", "error", "-framerate", String(FPS), "-i", join(frames, "f%05d.png")];
execFileSync("ffmpeg", [...input, "-vf", "scale=1280:-2:flags=lanczos", "-c:v", "libx264",
  "-pix_fmt", "yuv420p", "-crf", "23", "-preset", "slow", "-movflags", "+faststart",
  join(docs, "demo.mp4")], { stdio: "inherit" });
execFileSync("ffmpeg", [...input, "-vf",
  "fps=10,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=64:stats_mode=diff[p];" +
  "[b][p]paletteuse=dither=none:diff_mode=rectangle",
  join(docs, "demo.gif")], { stdio: "inherit" });
rmSync(frames, { recursive: true, force: true });
console.log("wrote docs/demo.mp4 and docs/demo.gif");
