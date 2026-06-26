#!/usr/bin/env node
/* Render an SVG export and a candidate HTML to PNG, then build side-by-side
 * comparison strips so you can verify the rebuild section by section.
 *
 * Usage:
 *   node render_compare.js ORIGINAL.(html|svg) CANDIDATE.html OUTDIR [width=393] [bandHeight=1000]
 *
 * Requires Node + puppeteer (`npm i puppeteer`). Set CHROME_PATH to use an
 * existing Chrome/Chromium instead of puppeteer's bundled one.
 *
 * Output: OUTDIR/original.png, OUTDIR/candidate.png, OUTDIR/compare_*.png
 *   compare strips put ORIGINAL on the left, CANDIDATE on the right.
 * Tip: the original SVG, when opened as raw HTML, may pick a wider fallback
 * font than your Segoe-UI target -- compare on a machine with the real font
 * for a true check, or embed a metric-compatible font in the candidate.
 */
const fs = require("fs");
const path = require("path");

async function main() {
  const [, , original, candidate, outdir, widthArg, bandArg] = process.argv;
  if (!original || !candidate || !outdir) {
    console.error("Usage: node render_compare.js ORIGINAL CANDIDATE OUTDIR [width] [bandHeight]");
    process.exit(1);
  }
  const width = parseInt(widthArg || "393", 10);
  const band = parseInt(bandArg || "1000", 10);
  fs.mkdirSync(outdir, { recursive: true });

  let puppeteer;
  try { puppeteer = require("puppeteer"); }
  catch (e) { console.error("puppeteer not found. Run: npm i puppeteer"); process.exit(1); }

  // original might be a bare .svg or HTML-wrapped; wrap with margin:0 for a fair compare
  let origUrl;
  const origTxt = fs.readFileSync(original, "utf8");
  if (origTxt.includes("<svg") && !origTxt.includes("<body")) {
    const tmp = path.join(outdir, "_orig.html");
    fs.writeFileSync(tmp, `<!DOCTYPE html><html><head><meta charset="UTF-8"><style>*{margin:0;padding:0}</style></head><body>${origTxt}</body></html>`);
    origUrl = "file://" + path.resolve(tmp);
  } else if (origTxt.includes("<svg")) {
    origUrl = "file://" + path.resolve(original);
  } else {
    origUrl = "file://" + path.resolve(original);
  }

  const launch = { headless: "new", args: ["--no-sandbox", "--disable-setuid-sandbox"] };
  if (process.env.CHROME_PATH) launch.executablePath = process.env.CHROME_PATH;
  const browser = await puppeteer.launch(launch);

  async function shoot(url, file) {
    const page = await browser.newPage();
    await page.setViewport({ width, height: 900, deviceScaleFactor: 1 });
    await page.goto(url, { waitUntil: "networkidle0", timeout: 60000 });
    // Neutralize the browser's default body margin (8px). SVG-export sources are
    // often wrapped in a full <body> with no CSS reset, which would shift the
    // whole page 8px and desync the comparison; our outputs already reset it.
    await page.addStyleTag({ content: "html,body{margin:0!important;padding:0!important}" }).catch(() => {});
    await new Promise((r) => setTimeout(r, 400));
    await page.screenshot({ path: path.join(outdir, file), fullPage: true });
    await page.close();
  }
  await shoot(origUrl, "original.png");
  await shoot("file://" + path.resolve(candidate), "candidate.png");
  await browser.close();
  console.log("[ok] original.png + candidate.png written to", outdir);
  console.log("Now stitch comparison strips (needs Python + Pillow):");
  console.log(`     python ${path.join(__dirname, "stitch.py")} ${outdir} ${band}`);
}
main().catch((e) => { console.error(e); process.exit(1); });
