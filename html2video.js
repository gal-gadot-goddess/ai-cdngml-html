const puppeteer = require('puppeteer');
const { execSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const os = require('os');

async function html2video(htmlPath, audioPath, outputPath) {
  htmlPath = path.resolve(htmlPath);
  audioPath = path.resolve(audioPath);
  outputPath = path.resolve(outputPath);

  if (!fs.existsSync(htmlPath)) throw new Error('HTML not found: ' + htmlPath);
  if (!fs.existsSync(audioPath)) throw new Error('Audio not found: ' + audioPath);

  // Get audio duration
  let audioDur = 0;
  try {
    const durOut = execSync(
      `ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "${audioPath}"`,
      { encoding: 'utf-8', timeout: 10000 }
    ).trim();
    audioDur = parseFloat(durOut) || 0;
  } catch (e) {
    console.warn('Warning: could not read audio duration, defaulting to 12s');
    audioDur = 0;
  }

  const MAX_DUR = 30;
  const videoDur = Math.min(MAX_DUR, Math.max(12, audioDur));
  console.log(`Audio: ${audioDur.toFixed(2)}s | Video: ${videoDur.toFixed(2)}s`);

  // Temp directory — ensure cleanup even on crash
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'h2v-'));
  const framesDir = path.join(tmpDir, 'f');
  let browser = null;

  try {
    fs.mkdirSync(framesDir);

    browser = await puppeteer.launch({
      headless: 'new',
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-gpu',
        '--disable-dev-shm-usage',
      ],
    });

    const page = await browser.newPage();
    await page.setViewport({ width: 1080, height: 1920 });
    await page.evaluateOnNewDocument(() => { window.__VIDEO_CAPTURE = true; });
    await page.goto('file://' + htmlPath, { waitUntil: 'networkidle0', timeout: 30000 });

    const fps = 30;
    const total = Math.ceil(videoDur * fps);
    const dt = 1 / fps;

    console.log(`Capturing ${total} frames @ ${fps}fps...`);
    await new Promise(r => setTimeout(r, 500));

    // Check if file supports frame-advance
    let useAdvance = false;
    try {
      const hasFn = await page.evaluate(() =>
        typeof window.__captureAdvance === 'function'
      );
      if (hasFn) {
        const len = await page.evaluate(() =>
          window.__captureAdvance.toString().length
        );
        useAdvance = len > 20;
      }
    } catch {
      useAdvance = false;
    }

    for (let i = 0; i < total; i++) {
      if (useAdvance) {
        await page.evaluate((d) => { window.__captureAdvance(d); }, dt);
      } else {
        await new Promise(r => setTimeout(r, 1000 / fps));
      }

      await page.screenshot({
        path: path.join(framesDir, `f_${String(i).padStart(6, '0')}.png`),
        type: 'png',
      });

      if (i % 30 === 0 || i === total - 1) process.stdout.write('.');
    }
    console.log(' done');

    await browser.close();
    browser = null;

    // ── Encode video ──────────────────────────────────────────────────────────
    const pattern = path.join(framesDir, 'f_%06d.png');
    const rawVid = path.join(tmpDir, 'raw.mp4');

    console.log('Encoding video...');
    execSync(
      `ffmpeg -y -framerate ${fps} -i "${pattern}" -c:v libx264 -pix_fmt yuv420p -preset medium -crf 18 -vf "pad=ceil(iw/2)*2:ceil(ih/2)*2" "${rawVid}"`,
      { stdio: 'pipe', timeout: 120000 }
    );

    if (!fs.existsSync(rawVid)) {
      throw new Error('FFmpeg failed to produce raw video');
    }

    // ── Add audio ─────────────────────────────────────────────────────────────
    console.log('Adding audio...');
    if (audioDur > 0 && audioDur < videoDur) {
      execSync(
        `ffmpeg -y -i "${rawVid}" -stream_loop -1 -i "${audioPath}" -shortest -c:v copy -c:a aac -b:a 192k "${outputPath}"`,
        { stdio: 'pipe', timeout: 120000 }
      );
    } else if (audioDur > 0) {
      execSync(
        `ffmpeg -y -i "${rawVid}" -i "${audioPath}" -c:v copy -c:a aac -b:a 192k -shortest "${outputPath}"`,
        { stdio: 'pipe', timeout: 120000 }
      );
    } else {
      // No valid audio — just copy video
      fs.copyFileSync(rawVid, outputPath);
    }

    if (!fs.existsSync(outputPath)) {
      throw new Error('FFmpeg failed to produce output video');
    }

    console.log('\n' + outputPath);
    return outputPath;

  } finally {
    // Always close browser
    if (browser) {
      try { await browser.close(); } catch {}
    }
    // Always clean up temp files
    try {
      if (fs.existsSync(tmpDir)) fs.rmSync(tmpDir, { recursive: true, force: true });
    } catch {}
  }
}

if (require.main === module) {
  const args = process.argv.slice(2);
  if (args.length < 2) {
    console.log('Usage: node html2video.js <html> <audio> [output.mp4]');
    process.exit(1);
  }
  const out = args[2] || path.basename(args[0], '.html') + '.mp4';
  html2video(args[0], args[1], out).catch(e => {
    console.error('\nError:', e.message);
    process.exit(1);
  });
}

module.exports = { html2video };
