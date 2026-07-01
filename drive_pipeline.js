/**
 * drive_pipeline.js — Google Drive → HTML → Video → Publish
 *
 * Fetches HTML files from Google Drive, converts to video with audio,
 * and prepares for social media publishing.
 *
 * Setup required:
 *   1. Google Cloud service account with Drive API enabled
 *   2. Share your Drive folder with the service account email
 *   3. Set env vars or pass as args:
 *
 * Usage:
 *   node drive_pipeline.js [--folder FOLDER_ID] [--audio ./viral] [--output ./Processed_Videos]
 *
 * Environment variables (or .env file):
 *   GOOGLE_SERVICE_ACCOUNT_KEY  — path to service-account.json
 *   GOOGLE_DRIVE_FOLDER_ID      — Drive folder containing HTML files
 */

const { html2video } = require('./html2video');
const path = require('path');
const fs = require('fs');
const os = require('os');

// Simple .env loader
if (fs.existsSync(path.join(__dirname, '.env'))) {
  const env = fs.readFileSync(path.join(__dirname, '.env'), 'utf-8');
  for (const line of env.split('\n')) {
    const m = line.match(/^\s*([^#=]+?)\s*=\s*(.*?)\s*$/);
    if (m) process.env[m[1]] = m[2].replace(/^["']|["']$/g, '');
  }
}

const AUDIO_FOLDER = path.resolve(findArg('--audio') || process.env.AUDIO_FOLDER || path.join(__dirname, 'viral'));
const OUTPUT_FOLDER = path.resolve(findArg('--output') || process.env.OUTPUT_FOLDER || path.join(__dirname, 'Processed_Videos'));
const DOWNLOAD_FOLDER = path.resolve(findArg('--download') || process.env.DOWNLOAD_FOLDER || path.join(__dirname, 'downloads'));
const LOG_FILE = path.join(__dirname, 'published_html.json');
const SERVICE_ACCOUNT_KEY = findArg('--key') || process.env.GOOGLE_SERVICE_ACCOUNT_KEY;
const DRIVE_FOLDER_ID = findArg('--folder') || process.env.GOOGLE_DRIVE_FOLDER_ID;

function findArg(name) {
  const idx = process.argv.indexOf(name);
  return idx >= 0 && idx + 1 < process.argv.length ? process.argv[idx + 1] : null;
}

function getProcessed() {
  if (!fs.existsSync(LOG_FILE)) return [];
  try { return JSON.parse(fs.readFileSync(LOG_FILE, 'utf-8')); } catch { return []; }
}

function markProcessed(name, driveId) {
  const list = getProcessed();
  list.push({ file: name, driveId, date: new Date().toISOString() });
  fs.writeFileSync(LOG_FILE, JSON.stringify(list, null, 2));
}

function getAudioFiles() {
  if (!fs.existsSync(AUDIO_FOLDER)) return [];
  return fs.readdirSync(AUDIO_FOLDER).filter(f => f.endsWith('.mp3'));
}

async function listDriveFiles(folderId, authKey) {
  const { google } = await import('googleapis');

  let creds;
  if (fs.existsSync(authKey)) {
    creds = JSON.parse(fs.readFileSync(authKey, 'utf-8'));
  } else {
    creds = JSON.parse(authKey);
  }

  const auth = new google.auth.GoogleAuth({
    credentials: creds,
    scopes: ['https://www.googleapis.com/auth/drive.readonly'],
  });

  const drive = google.drive({ version: 'v3', auth });
  const res = await drive.files.list({
    q: `'${folderId}' in parents and mimeType='text/html' and trashed=false`,
    fields: 'files(id,name,size,createdTime)',
    orderBy: 'createdTime desc',
  });

  return res.data.files || [];
}

async function downloadDriveFile(fileId, destPath, authKey) {
  const { google } = await import('googleapis');

  let creds;
  if (fs.existsSync(authKey)) {
    creds = JSON.parse(fs.readFileSync(authKey, 'utf-8'));
  } else {
    creds = JSON.parse(authKey);
  }

  const auth = new google.auth.GoogleAuth({
    credentials: creds,
    scopes: ['https://www.googleapis.com/auth/drive.readonly'],
  });

  const drive = google.drive({ version: 'v3', auth });
  const dest = fs.createWriteStream(destPath);

  const res = await drive.files.get(
    { fileId, alt: 'media' },
    { responseType: 'stream' }
  );

  return new Promise((resolve, reject) => {
    res.data
      .on('end', resolve)
      .on('error', reject)
      .pipe(dest);
  });
}

async function main() {
  console.log(`\n=== Google Drive → HTML → Video Pipeline ===\n`);

  if (!SERVICE_ACCOUNT_KEY) {
    console.error('ERROR: GOOGLE_SERVICE_ACCOUNT_KEY not set.');
    console.error('Provide via --key <path> or GOOGLE_SERVICE_ACCOUNT_KEY env var.');
    process.exit(1);
  }
  if (!DRIVE_FOLDER_ID) {
    console.error('ERROR: GOOGLE_DRIVE_FOLDER_ID not set.');
    console.error('Provide via --folder <id> or GOOGLE_DRIVE_FOLDER_ID env var.');
    process.exit(1);
  }

  if (!fs.existsSync(OUTPUT_FOLDER)) fs.mkdirSync(OUTPUT_FOLDER, { recursive: true });
  if (!fs.existsSync(DOWNLOAD_FOLDER)) fs.mkdirSync(DOWNLOAD_FOLDER, { recursive: true });

  const audioFiles = getAudioFiles();
  if (audioFiles.length === 0) {
    console.error('No MP3 audio files in', AUDIO_FOLDER);
    process.exit(1);
  }

  console.log('Fetching HTML files from Google Drive...');
  let driveFiles;
  try {
    driveFiles = await listDriveFiles(DRIVE_FOLDER_ID, SERVICE_ACCOUNT_KEY);
  } catch (err) {
    console.error('Failed to list Drive files:', err.message);
    console.error('Make sure the service account has access to the folder.');
    process.exit(1);
  }

  console.log(`Found ${driveFiles.length} HTML file(s) in Drive.\n`);

  if (driveFiles.length === 0) {
    console.log('No HTML files to process.');
    return;
  }

  const processed = getProcessed();
  const processedIds = new Set(processed.map(p => p.driveId));
  const pending = driveFiles.filter(f => !processedIds.has(f.id));

  if (pending.length === 0) {
    console.log('All HTML files already processed.');
    return;
  }

  console.log(`Pending: ${pending.length} file(s)\n`);

  for (let i = 0; i < pending.length; i++) {
    const file = pending[i];
    const safeName = file.name.replace(/[^a-zA-Z0-9._-]/g, '_');
    const htmlPath = path.join(DOWNLOAD_FOLDER, safeName);
    const audioFile = audioFiles[Math.floor(Math.random() * audioFiles.length)];
    const audioPath = path.join(AUDIO_FOLDER, audioFile);
    const outName = safeName.replace(/\.html$/i, '.mp4');
    const outPath = path.join(OUTPUT_FOLDER, outName);

    console.log(`[${i + 1}/${pending.length}] ${file.name} (${file.id})`);

    // Download
    try {
      console.log('   Downloading from Drive...');
      await downloadDriveFile(file.id, htmlPath, SERVICE_ACCOUNT_KEY);
    } catch (err) {
      console.error(`   Download failed: ${err.message}`);
      continue;
    }

    // Convert to video
    console.log(`   Converting with audio: ${audioFile}`);
    try {
      await html2video(htmlPath, audioPath, outPath);
    } catch (err) {
      console.error(`   Conversion failed: ${err.message}`);
      continue;
    }

    markProcessed(file.name, file.id);
    console.log('   Done.\n');
  }

  const totalSize = fs.readdirSync(OUTPUT_FOLDER)
    .filter(f => f.endsWith('.mp4'))
    .reduce((s, f) => s + (fs.statSync(path.join(OUTPUT_FOLDER, f)).size || 0), 0);

  console.log(`=== Pipeline complete ===`);
  console.log(`Videos in: ${OUTPUT_FOLDER}`);
  console.log(`Total size: ${(totalSize / 1024 / 1024).toFixed(1)} MB`);
  console.log(`Ready for publishing!`);
}

if (require.main === module) main().catch(console.error);
module.exports = { main, listDriveFiles, downloadDriveFile };
