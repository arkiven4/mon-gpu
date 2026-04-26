/* ──────────────────────────────────────────────
   Cough Detector  –  frontend logic
   ────────────────────────────────────────────── */

'use strict';

// ── State ──────────────────────────────────────
let audioCtx  = null;
let stream    = null;
let processor = null;
let isRunning = false;
let pendingInfer = false;

let lastCoughTime  = 0;   // ms timestamp of last positive detection
let coughCount     = 0;
let coughEntries   = [];  // { id, time, prob, audioUrl }
let currentAudio   = null;

// Per-segment dedup: track absolute clock positions of already-logged segments.
// absStart = (captureTimeSec - chunkDurSec) + seg.start_sec  — stable across
// overlapping windows for the same cough, shifts by 0.2 s for a distinct cough.
let loggedSegments  = [];   // [{ absStart, absEnd }]
const SEG_MARGIN_SEC = 0.15; // segments within 150 ms = same cough event

// ── Audio buffers ───────────────────────────────
const INFER_BUF_MS  = 2000;  // rolling buffer sent to server (2 s)
const INFER_STEP_MS = 250;   // send every 0.25 s (matches model step_sec)
let   lastInferAt   = 0;
let   inferBuffer   = [];    // raw Float32 samples (native SR)

// ── Waveform display ────────────────────────────
const DISP_SIZE = 3000;           // rolling history points
const dispBuf   = new Float32Array(DISP_SIZE);
let   dispPos   = 0;              // circular write head

// ── Theme ───────────────────────────────────────
function applyTheme(theme) {
    document.body.dataset.theme = theme;
    localStorage.setItem('cd-theme', theme);
}

function toggleTheme() {
    applyTheme(document.body.dataset.theme === 'dark' ? 'light' : 'dark');
}

// Restore saved theme (default = light)
applyTheme(localStorage.getItem('cd-theme') || 'light');

// ── Canvas setup ───────────────────────────────
const waveCanvas = document.getElementById('waveCanvas');
const waveCtx    = waveCanvas.getContext('2d');

function resizeCanvas() {
    waveCanvas.width  = waveCanvas.offsetWidth  || 800;
    waveCanvas.height = waveCanvas.offsetHeight || 130;
}
resizeCanvas();
window.addEventListener('resize', resizeCanvas);

// ── Threshold marker position (CSS var) ─────────
// Scale: bar fills when prob = threshold*3 → threshold ≈ 33% bar width
// Actually we use ratio so threshold sits at 80% of bar
// The CSS ::after pseudo uses --thresh-pct set here:
document.getElementById('probTrack').style.setProperty('--thresh-pct', '80%');

// ── Animation loop (always running) ─────────────
(function animLoop() {
    drawWaveform();
    requestAnimationFrame(animLoop);
})();

function drawWaveform() {
    const W      = waveCanvas.width;
    const H      = waveCanvas.height;
    const isDark = document.body.dataset.theme === 'dark';

    // Theme-aware canvas colors
    const bgColor     = isDark ? '#070e1c'              : '#dce8f5';
    const gridColor   = isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.05)';
    const centerColor = isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.09)';

    waveCtx.fillStyle = bgColor;
    waveCtx.fillRect(0, 0, W, H);

    // Subtle grid lines
    waveCtx.strokeStyle = gridColor;
    waveCtx.lineWidth = 1;
    for (const frac of [0.25, 0.5, 0.75]) {
        waveCtx.beginPath();
        waveCtx.moveTo(0, H * frac);
        waveCtx.lineTo(W, H * frac);
        waveCtx.stroke();
    }

    // Center line
    waveCtx.strokeStyle = centerColor;
    waveCtx.beginPath();
    waveCtx.moveTo(0, H * 0.5);
    waveCtx.lineTo(W, H * 0.5);
    waveCtx.stroke();

    const now      = Date.now();
    const coughing = isRunning && (now - lastCoughTime < 1500);
    const color    = !isRunning ? (isDark ? 'rgba(100,116,139,0.35)' : 'rgba(148,163,184,0.5)')
                   : coughing  ? (isDark ? '#ef4444' : '#dc2626')
                   :             (isDark ? '#22c55e' : '#16a34a');

    const mid   = H * 0.5;
    const scale = mid * 0.78;

    waveCtx.strokeStyle = color;
    waveCtx.lineWidth   = 1.5;
    waveCtx.shadowBlur  = coughing ? 8 : 0;
    waveCtx.shadowColor = '#ef4444';

    waveCtx.beginPath();
    // oldest data starts at dispPos (ring buffer)
    for (let x = 0; x < W; x++) {
        const si = (dispPos + Math.floor(x * DISP_SIZE / W)) % DISP_SIZE;
        const y  = mid - dispBuf[si] * scale;
        x === 0 ? waveCtx.moveTo(x, y) : waveCtx.lineTo(x, y);
    }
    waveCtx.stroke();
    waveCtx.shadowBlur = 0;
}

// ── Permission overlay ──────────────────────────
document.getElementById('btnAllow').addEventListener('click', async () => {
    const errEl = document.getElementById('permError');
    errEl.style.display = 'none';

    try {
        // Trigger permission dialog; immediately release track
        const tmp = await navigator.mediaDevices.getUserMedia({ audio: true });
        tmp.getTracks().forEach(t => t.stop());

        await populateDevices();

        document.getElementById('permOverlay').style.display = 'none';
        document.getElementById('mainApp').classList.remove('d-none');
        resizeCanvas();
    } catch (e) {
        errEl.style.display = 'block';
        errEl.textContent   = 'Microphone access denied: ' + e.message;
    }
});

async function populateDevices() {
    const devices = await navigator.mediaDevices.enumerateDevices();
    const inputs  = devices.filter(d => d.kind === 'audioinput');
    const sel     = document.getElementById('deviceSelect');
    sel.innerHTML = '';
    inputs.forEach((d, i) => {
        const opt      = document.createElement('option');
        opt.value      = d.deviceId;
        opt.textContent = d.label || `Microphone ${i + 1}`;
        sel.appendChild(opt);
    });
}

// ── Start / Stop button ─────────────────────────
document.getElementById('btnStartStop').addEventListener('click', () => {
    isRunning ? stopCapture() : startCapture();
});

document.getElementById('deviceSelect').addEventListener('change', () => {
    if (isRunning) { stopCapture(); startCapture(); }
});

async function startCapture() {
    const deviceId = document.getElementById('deviceSelect').value;
    const btn      = document.getElementById('btnStartStop');

    try {
        stream = await navigator.mediaDevices.getUserMedia({
            audio: {
                deviceId:          deviceId ? { exact: deviceId } : undefined,
                echoCancellation:  false,
                noiseSuppression:  false,
                autoGainControl:   false,
            }
        });
    } catch (e) {
        alert('Microphone error: ' + e.message);
        return;
    }

    audioCtx  = new AudioContext();
    const src = audioCtx.createMediaStreamSource(stream);
    processor = audioCtx.createScriptProcessor(4096, 1, 1);

    const nativeSR      = audioCtx.sampleRate;
    const maxBufSamples = Math.round(nativeSR * INFER_BUF_MS / 1000);  // 2 s
    const minSendSamples = Math.round(nativeSR * 0.5);                  // need ≥ 0.5 s
    const decimFactor    = Math.max(1, Math.round(nativeSR * 3 / DISP_SIZE));

    processor.onaudioprocess = (e) => {
        const input = e.inputBuffer.getChannelData(0);

        // ── Fill display buffer (decimated) ──
        for (let i = 0; i < input.length; i += decimFactor) {
            dispBuf[dispPos % DISP_SIZE] = input[i];
            dispPos++;
        }

        // ── Accumulate for inference ──
        for (let i = 0; i < input.length; i++) inferBuffer.push(input[i]);
        if (inferBuffer.length > maxBufSamples) {
            inferBuffer = inferBuffer.slice(-maxBufSamples);
        }

        // ── Trigger inference every INFER_STEP_MS ──
        const now = performance.now();
        if (!pendingInfer
            && (now - lastInferAt) >= INFER_STEP_MS
            && inferBuffer.length >= minSendSamples) {
            lastInferAt = now;
            // Send full rolling buffer — server runs run_sliding on it
            const chunk = new Float32Array(inferBuffer);
            sendForInference(chunk, nativeSR);
        }
    };

    src.connect(processor);
    processor.connect(audioCtx.destination);

    isRunning      = true;
    inferBuffer    = [];
    loggedSegments = [];
    dispBuf.fill(0);
    dispPos      = 0;
    lastInferAt  = 0;
    pendingInfer = false;

    btn.textContent = 'Stop';
    btn.classList.add('stop');
    setIndicator('ok');
}

function stopCapture() {
    if (processor)  { processor.disconnect(); processor = null; }
    if (stream)     { stream.getTracks().forEach(t => t.stop()); stream = null; }
    if (audioCtx)   { audioCtx.close(); audioCtx = null; }

    isRunning   = false;
    inferBuffer = [];

    const btn = document.getElementById('btnStartStop');
    btn.textContent = 'Start';
    btn.classList.remove('stop');
    setIndicator('idle');
    updateProb(0, false);
}

// ── Inference request ───────────────────────────
async function sendForInference(chunk, srcSR) {
    pendingInfer = true;
    // Compute before await so timing is relative to when audio was captured.
    const captureTimeSec = performance.now() / 1000;
    const chunkDurSec    = chunk.length / srcSR;
    const absBase        = captureTimeSec - chunkDurSec;

    try {
        const fd = new FormData();
        fd.append('audio', new Blob([chunk.buffer], { type: 'application/octet-stream' }), 'chunk.raw');
        fd.append('src_sr', String(srcSR));

        const resp = await fetch('/cough/infer', { method: 'POST', body: fd });
        if (!resp.ok) return;
        const { prob, flag, segments } = await resp.json();

        updateProb(prob, flag === 1);

        const now = Date.now();
        if (flag === 1) {
            lastCoughTime = now;
            setIndicator('cough');

            // Evict stale entries (> 4 s old)
            loggedSegments = loggedSegments.filter(
                s => captureTimeSec - s.absEnd < 4.0
            );

            for (const seg of segments) {
                const absStart = absBase + seg.start_sec;
                const absEnd   = absBase + seg.end_sec;

                // Same cough reappears across overlapping windows at the same
                // absStart (math cancels); a distinct cough differs by ≥ 0.2 s.
                const duplicate = loggedSegments.some(
                    s => Math.abs(absStart - s.absStart) < SEG_MARGIN_SEC
                );
                if (duplicate) continue;

                loggedSegments.push({ absStart, absEnd });

                const clip = chunk.slice(
                    Math.round(seg.start_sec * srcSR),
                    Math.min(chunk.length, Math.round(seg.end_sec * srcSR)),
                );
                addCoughEntry(clip, srcSR, prob);
            }

            setTimeout(() => {
                if (Date.now() - lastCoughTime >= 1400 && isRunning) setIndicator('ok');
            }, 1500);
        } else if (now - lastCoughTime >= 1500) {
            if (isRunning) setIndicator('ok');
        }
    } catch (e) {
        console.warn('[cough] inference error:', e);
    } finally {
        pendingInfer = false;
    }
}

// ── UI updates ──────────────────────────────────
function updateProb(prob, isCough) {
    document.getElementById('probValue').textContent = prob.toFixed(4);

    const bar  = document.getElementById('probBar');
    // Scale: threshold maps to 80% of bar width
    const pct  = Math.min(100, (prob / THRESHOLD) * 80);
    bar.style.width           = pct + '%';
    bar.style.backgroundColor = isCough ? 'var(--cd-red)'
                              : prob > THRESHOLD * 0.5 ? 'var(--cd-amber)'
                              : 'var(--cd-green)';
}

function setIndicator(state) {
    // state: 'idle' | 'ok' | 'cough'
    const el  = document.getElementById('indicator');
    const txt = document.getElementById('indText');
    el.className = 'cd-indicator cd-ind-' + state;
    txt.textContent = state === 'cough' ? 'COUGH DETECTED'
                    : state === 'ok'    ? 'LISTENING'
                    :                     'IDLE';
}

// ── Cough log ────────────────────────────────────
function addCoughEntry(samples, srcSR, prob) {
    coughCount++;
    const timeStr  = new Date().toLocaleTimeString();
    const wavBlob  = encodeWAV(samples, srcSR);
    const audioUrl = URL.createObjectURL(wavBlob);

    coughEntries.unshift({ id: coughCount, time: timeStr, prob, audioUrl });

    document.getElementById('countBadge').textContent = coughCount;
    document.getElementById('lastDet').textContent    = `Last: ${timeStr}  (prob ${prob.toFixed(4)})`;
    renderLog();
}

function renderLog() {
    const el = document.getElementById('coughLog');
    if (coughEntries.length === 0) {
        el.innerHTML = '<div class="cd-empty">No coughs detected yet. Press <strong>Start</strong> to begin.</div>';
        return;
    }
    el.innerHTML = coughEntries.map(e => `
        <div class="cd-entry">
            <div class="cd-entry-num">${e.id}</div>
            <div class="cd-entry-info">
                <div class="cd-entry-time">${e.time}</div>
                <div class="cd-entry-prob">prob: ${e.prob.toFixed(4)}</div>
            </div>
            <button class="cd-btn-play" data-url="${e.audioUrl}" onclick="playCough(this)">&#9654; Play</button>
        </div>
    `).join('');
}

function clearLog() {
    coughEntries.forEach(e => URL.revokeObjectURL(e.audioUrl));
    coughEntries = [];
    coughCount   = 0;
    document.getElementById('countBadge').textContent = '0';
    document.getElementById('lastDet').textContent    = '—';
    if (currentAudio) { currentAudio.pause(); currentAudio = null; }
    renderLog();
}

// ── Playback ─────────────────────────────────────
function playCough(btn) {
    const url = btn.dataset.url;

    // Stop if already playing the same clip
    if (currentAudio && btn.classList.contains('playing')) {
        currentAudio.pause();
        currentAudio = null;
        resetPlayButtons();
        return;
    }

    if (currentAudio) {
        currentAudio.pause();
        currentAudio = null;
        resetPlayButtons();
    }

    currentAudio = new Audio(url);
    currentAudio.play().catch(console.warn);

    btn.innerHTML = '&#9646;&#9646; Stop';
    btn.classList.add('playing');

    currentAudio.onended = () => {
        resetPlayButtons();
        currentAudio = null;
    };
}

function resetPlayButtons() {
    document.querySelectorAll('.cd-btn-play').forEach(b => {
        b.innerHTML = '&#9654; Play';
        b.classList.remove('playing');
    });
}

// ── WAV encoder ───────────────────────────────────
function encodeWAV(samples, sampleRate) {
    const n   = samples.length;
    const buf = new ArrayBuffer(44 + n * 2);
    const v   = new DataView(buf);

    const s = (off, str) => { for (let i = 0; i < str.length; i++) v.setUint8(off + i, str.charCodeAt(i)); };

    s(0,  'RIFF');
    v.setUint32(4,  36 + n * 2, true);
    s(8,  'WAVE');
    s(12, 'fmt ');
    v.setUint32(16, 16,          true);  // chunk size
    v.setUint16(20, 1,           true);  // PCM
    v.setUint16(22, 1,           true);  // mono
    v.setUint32(24, sampleRate,  true);
    v.setUint32(28, sampleRate * 2, true);
    v.setUint16(32, 2,           true);  // block align
    v.setUint16(34, 16,          true);  // bits/sample
    s(36, 'data');
    v.setUint32(40, n * 2,       true);

    let off = 44;
    for (let i = 0; i < n; i++, off += 2) {
        const x = Math.max(-1, Math.min(1, samples[i]));
        v.setInt16(off, x < 0 ? x * 0x8000 : x * 0x7FFF, true);
    }

    return new Blob([buf], { type: 'audio/wav' });
}
