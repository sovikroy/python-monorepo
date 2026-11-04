// Render each demo in docs/demo/player.html to an MP4 and a GIF in docs/:
//
//   overview -> docs/demo.mp4,    docs/demo.gif      (README)
//   brokers  -> docs/brokers.mp4, docs/brokers.gif   (ARCHITECTURE.md, messaging)
//
//   node docs/demo/record.mjs              # every demo; needs playwright (Chromium) and ffmpeg
//   node docs/demo/record.mjs brokers      # just one
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
const OUTPUT = { overview: "demo", brokers: "brokers" };

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 960, height: 600 }, deviceScaleFactor: 2 });
const url = (demo) => pathToFileURL(join(here, "player.html")).href + `?record&demo=${demo}`;

await page.goto(url("overview"));
const known = await page.evaluate(() => window.DEMOS);
const wanted = process.argv.length > 2 ? process.argv.slice(2) : known;
for (const demo of wanted) {
  if (!known.includes(demo) || !OUTPUT[demo]) throw new Error(`unknown demo ${demo}; known: ${known}`);
}

for (const demo of wanted) {
  const frames = mkdtempSync(join(tmpdir(), `demo-${demo}-`));
  await page.goto(url(demo));
  await page.evaluate(() => document.fonts.ready);
  const duration = await page.evaluate(() => window.DURATION);
  const total = Math.ceil(duration * FPS);
  for (let i = 0; i < total; i++) {
    await page.evaluate((t) => window.seek(t), i / FPS);
    await page.screenshot({ path: join(frames, `f${String(i).padStart(5, "0")}.png`) });
  }
  console.log(`${demo}: rendered ${total} frames (${duration.toFixed(1)}s)`);

  const base = join(docs, OUTPUT[demo]);
  const input = ["-y", "-loglevel", "error", "-framerate", String(FPS), "-i", join(frames, "f%05d.png")];
  execFileSync("ffmpeg", [...input, "-vf", "scale=1280:-2:flags=lanczos", "-c:v", "libx264",
    "-pix_fmt", "yuv420p", "-crf", "23", "-preset", "slow", "-movflags", "+faststart",
    `${base}.mp4`], { stdio: "inherit" });
  execFileSync("ffmpeg", [...input, "-vf",
    "fps=10,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=64:stats_mode=diff[p];" +
    "[b][p]paletteuse=dither=none:diff_mode=rectangle",
    `${base}.gif`], { stdio: "inherit" });
  rmSync(frames, { recursive: true, force: true });
  console.log(`wrote docs/${OUTPUT[demo]}.mp4 and docs/${OUTPUT[demo]}.gif`);
}
await browser.close();
