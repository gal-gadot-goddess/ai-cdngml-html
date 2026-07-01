/**
 * pipeline.js — HTML → Video Pipeline
 *
 * Scans a folder for HTML files, converts each to video with random audio,
 * and outputs processed videos.
 *
 * Usage:
 *   node pipeline.js <html-folder> [audio-folder] [output-folder]
 *
 * Defaults:
 *   html-folder  = ./
 *   audio-folder = ./viral/
 *   output-folder = ./Processed_Videos/
 */

const { html2video } = require('./html2video');
const path = require('path');
const fs = require('fs');

const HTML_FOLDER = path.resolve(process.argv[2] || '.');
const AUDIO_FOLDER = path.resolve(process.argv[3] || path.join(__dirname, 'viral'));
const OUTPUT_FOLDER = path.resolve(process.argv[4] || path.join(__dirname, 'Processed_Videos'));
const LOG_FILE = path.join(__dirname, 'published_html.json');

function getProcessed() {
  if (!fs.existsSync(LOG_FILE)) return [];
  try { return JSON.parse(fs.readFileSync(LOG_FILE, 'utf-8')); }
  catch { return []; }
}

function markProcessed(name) {
  const list = getProcessed();
  list.push({ file: name, date: new Date().toISOString() });
  fs.writeFileSync(LOG_FILE, JSON.stringify(list, null, 2));
}

function getHtmlFiles() {
  if (!fs.existsSync(HTML_FOLDER)) {
    console.error('HTML folder not found:', HTML_FOLDER);
    process.exit(1);
  }
  return fs.readdirSync(HTML_FOLDER)
    .filter(f => f.endsWith('.html'))
    .sort();
}

function getAudioFiles() {
  if (!fs.existsSync(AUDIO_FOLDER)) return [];
  return fs.readdirSync(AUDIO_FOLDER).filter(f => f.endsWith('.mp3'));
}

async function main() {
  if (!fs.existsSync(OUTPUT_FOLDER)) fs.mkdirSync(OUTPUT_FOLDER, { recursive: true });

  const htmlFiles = getHtmlFiles();
  const audioFiles = getAudioFiles();
  const processed = getProcessed();

  console.log(`\n=== HTML → Video Pipeline ===`);
  console.log(`HTML folder:  ${HTML_FOLDER}`);
  console.log(`Audio folder: ${AUDIO_FOLDER}`);
  console.log(`Output folder: ${OUTPUT_FOLDER}`);
  console.log(`\nHTML files found: ${htmlFiles.length}`);
  console.log(`Audio files found: ${audioFiles.length}`);
  console.log(`Already processed: ${processed.length}\n`);

  if (audioFiles.length === 0) {
    console.error('No MP3 audio files found in', AUDIO_FOLDER);
    process.exit(1);
  }

  const processedNames = new Set(processed.map(p => p.file));
  const pending = htmlFiles.filter(f => !processedNames.has(f));

  if (pending.length === 0) {
    console.log('All HTML files already processed. Nothing to do.');
    return;
  }

  console.log(`Pending: ${pending.length} file(s)\n`);

  for (let i = 0; i < pending.length; i++) {
    const htmlFile = pending[i];
    const audioFile = audioFiles[Math.floor(Math.random() * audioFiles.length)];
    const htmlPath = path.join(HTML_FOLDER, htmlFile);
    const audioPath = path.join(AUDIO_FOLDER, audioFile);
    const outName = htmlFile.replace(/\.html$/i, '.mp4');
    const outPath = path.join(OUTPUT_FOLDER, outName);

    console.log(`[${i + 1}/${pending.length}] ${htmlFile}`);
    console.log(`   Audio: ${audioFile}`);
    console.log(`   Output: ${outName}`);

    try {
      await html2video(htmlPath, audioPath, outPath);
      markProcessed(htmlFile);
      console.log(`   Done.\n`);
    } catch (err) {
      console.error(`   FAILED: ${err.message}\n`);
    }
  }

  console.log(`=== Pipeline complete. Videos in: ${OUTPUT_FOLDER} ===`);
}

if (require.main === module) main().catch(console.error);
module.exports = { main };
