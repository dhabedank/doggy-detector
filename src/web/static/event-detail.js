let currentEvent = null;
let waveformEnabled = false;
let waveformAudioBuffer = null;
let waveformLoadPromise = null;
let waveformZoom = 1;
let waveformDrawQueued = false;

const WAVEFORM_MIN_ZOOM = 1;
const WAVEFORM_MAX_ZOOM = 16;
const WAVEFORM_HEIGHT = 168;

document.addEventListener('DOMContentLoaded', function() {
    const page = document.querySelector('.detail-page');
    const eventId = page ? page.dataset.eventId : null;
    setupWaveformControls();
    if (!eventId) {
        showDetailError('Incident id missing.');
        return;
    }
    fetchEventDetail(eventId);
});

function setupWaveformControls() {
    document.getElementById('waveformToggleBtn').addEventListener('click', toggleWaveform);
    document.getElementById('waveformZoomOutBtn').addEventListener('click', function() {
        setWaveformZoom(waveformZoom / 2);
    });
    document.getElementById('waveformZoomInBtn').addEventListener('click', function() {
        setWaveformZoom(waveformZoom * 2);
    });
    document.getElementById('waveformFitBtn').addEventListener('click', function() {
        setWaveformZoom(1);
    });
    document.getElementById('waveformCanvas').addEventListener('click', seekFromWaveformClick);

    const audio = document.getElementById('detailAudioPlayer');
    ['timeupdate', 'seeked', 'loadedmetadata', 'play', 'pause'].forEach(eventName => {
        audio.addEventListener(eventName, requestWaveformDraw);
    });
    window.addEventListener('resize', requestWaveformDraw);
}

function fetchEventDetail(eventId) {
    fetch(`/api/events/${eventId}`)
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(renderEventDetail)
        .catch(error => {
            console.error('Error loading event detail:', error);
            showDetailError('Could not load incident details.');
        });
}

function renderEventDetail(event) {
    currentEvent = event;
    waveformAudioBuffer = null;
    waveformLoadPromise = null;
    waveformEnabled = false;
    waveformZoom = 1;

    const startedAt = new Date(event.started_at);
    const audio = document.getElementById('detailAudioPlayer');
    const noClip = document.getElementById('detailNoClip');

    if (event.clip_url) {
        audio.src = event.clip_url;
        audio.hidden = false;
        noClip.hidden = true;
    } else {
        audio.removeAttribute('src');
        audio.hidden = true;
        noClip.hidden = false;
    }
    resetWaveformUi(Boolean(event.clip_url));

    document.getElementById('detailStarted').textContent = startedAt.toLocaleString();
    document.getElementById('detailDuration').textContent = formatDuration(event.duration_sec);
    document.getElementById('detailPeak').textContent = formatPercent(event.peak_score);
    document.getElementById('detailAverage').textContent = formatPercent(event.avg_score);
    document.getElementById('detailThreshold').textContent = formatThreshold(event.detection_threshold);
    document.getElementById('detailAudioLevel').textContent = formatAudioLevel(event);
    document.getElementById('detailBarks').textContent = event.bark_count ?? '-';
    document.getElementById('detailDirection').textContent = event.direction || 'unknown';
    document.getElementById('detailWeather').textContent = formatWeather(event);
    document.getElementById('detailFalsePositive').textContent = event.is_false_pos
        ? (event.false_pos_reason || 'False positive')
        : 'Valid incident';
    document.getElementById('detailHash').textContent = event.clip_hash || 'No clip fingerprint';
}

function resetWaveformUi(hasClip) {
    const section = document.getElementById('waveformSection');
    const frame = document.getElementById('waveformFrame');
    const controls = document.getElementById('waveformControls');
    const toggle = document.getElementById('waveformToggleBtn');

    section.hidden = !hasClip;
    frame.hidden = true;
    controls.hidden = true;
    toggle.textContent = 'Show Waveform';
    toggle.classList.remove('active');
    toggle.setAttribute('aria-pressed', 'false');
    setWaveformState('');
    updateWaveformZoomControls();
}

async function toggleWaveform() {
    if (!currentEvent || !currentEvent.clip_url) {
        return;
    }

    waveformEnabled = !waveformEnabled;
    updateWaveformVisibility();

    if (!waveformEnabled) {
        return;
    }

    setWaveformState('Loading');
    try {
        await ensureWaveformLoaded();
        setWaveformState(formatMarkerState());
        requestWaveformDraw();
    } catch (error) {
        console.error('Error loading waveform:', error);
        document.getElementById('waveformFrame').hidden = true;
        setWaveformState('Waveform unavailable');
    }
}

function updateWaveformVisibility() {
    const toggle = document.getElementById('waveformToggleBtn');
    document.getElementById('waveformFrame').hidden = !waveformEnabled;
    document.getElementById('waveformControls').hidden = !waveformEnabled;
    toggle.textContent = waveformEnabled ? 'Hide Waveform' : 'Show Waveform';
    toggle.classList.toggle('active', waveformEnabled);
    toggle.setAttribute('aria-pressed', String(waveformEnabled));
    setWaveformState(waveformEnabled ? formatMarkerState() : '');
}

function ensureWaveformLoaded() {
    if (waveformAudioBuffer) {
        return Promise.resolve(waveformAudioBuffer);
    }
    if (waveformLoadPromise) {
        return waveformLoadPromise;
    }

    waveformLoadPromise = fetch(currentEvent.clip_url, { cache: 'no-store' })
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.arrayBuffer();
        })
        .then(decodeAudioBuffer)
        .then(audioBuffer => {
            waveformAudioBuffer = audioBuffer;
            return audioBuffer;
        })
        .finally(() => {
            waveformLoadPromise = null;
        });

    return waveformLoadPromise;
}

async function decodeAudioBuffer(arrayBuffer) {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) {
        throw new Error('Web Audio is not available');
    }

    const audioContext = new AudioContextClass();
    try {
        return await audioContext.decodeAudioData(arrayBuffer.slice(0));
    } finally {
        if (audioContext.close) {
            audioContext.close();
        }
    }
}

function setWaveformZoom(nextZoom) {
    const frame = document.getElementById('waveformFrame');
    const oldScrollWidth = Math.max(frame.scrollWidth, frame.clientWidth, 1);
    const visibleCenter = (frame.scrollLeft + frame.clientWidth / 2) / oldScrollWidth;

    waveformZoom = Math.min(WAVEFORM_MAX_ZOOM, Math.max(WAVEFORM_MIN_ZOOM, nextZoom));
    updateWaveformZoomControls();
    requestWaveformDraw();

    requestAnimationFrame(() => {
        const newScrollWidth = Math.max(frame.scrollWidth, frame.clientWidth, 1);
        frame.scrollLeft = Math.max(0, visibleCenter * newScrollWidth - frame.clientWidth / 2);
    });
}

function updateWaveformZoomControls() {
    document.getElementById('waveformZoomValue').textContent = `${waveformZoom}x`;
    document.getElementById('waveformZoomOutBtn').disabled = waveformZoom <= WAVEFORM_MIN_ZOOM;
    document.getElementById('waveformZoomInBtn').disabled = waveformZoom >= WAVEFORM_MAX_ZOOM;
}

function requestWaveformDraw() {
    if (!waveformEnabled || !waveformAudioBuffer || waveformDrawQueued) {
        return;
    }
    waveformDrawQueued = true;
    requestAnimationFrame(() => {
        waveformDrawQueued = false;
        drawWaveform();
    });
}

function drawWaveform() {
    const frame = document.getElementById('waveformFrame');
    const canvas = document.getElementById('waveformCanvas');
    const context = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const viewportWidth = Math.max(320, Math.floor(frame.clientWidth || 640));
    const cssWidth = Math.max(viewportWidth, Math.floor(viewportWidth * waveformZoom));
    const cssHeight = WAVEFORM_HEIGHT;

    if (canvas.width !== Math.floor(cssWidth * dpr) || canvas.height !== Math.floor(cssHeight * dpr)) {
        canvas.width = Math.floor(cssWidth * dpr);
        canvas.height = Math.floor(cssHeight * dpr);
        canvas.style.width = `${cssWidth}px`;
        canvas.style.height = `${cssHeight}px`;
    }

    context.setTransform(dpr, 0, 0, dpr, 0, 0);
    context.clearRect(0, 0, cssWidth, cssHeight);

    const colors = getWaveformColors();
    context.fillStyle = colors.background;
    context.fillRect(0, 0, cssWidth, cssHeight);

    drawTimeGrid(context, cssWidth, cssHeight, colors);
    drawWaveformPeaks(context, cssWidth, cssHeight, colors);
    drawBarkMarkers(context, cssWidth, cssHeight, colors);
    drawPlaybackHead(context, cssWidth, cssHeight, colors);
}

function drawTimeGrid(context, width, height, colors) {
    const duration = getWaveformDuration();
    const step = getGridStep(duration, waveformZoom);

    context.strokeStyle = colors.grid;
    context.fillStyle = colors.textMuted;
    context.font = '11px "IBM Plex Mono", monospace';
    context.lineWidth = 1;

    for (let seconds = 0; seconds <= duration; seconds += step) {
        const x = Math.round((seconds / duration) * width) + 0.5;
        context.beginPath();
        context.moveTo(x, 0);
        context.lineTo(x, height - 18);
        context.stroke();
        if (seconds > 0 && seconds < duration) {
            context.fillText(formatMarkerTime(seconds), x + 4, height - 6);
        }
    }
}

function drawWaveformPeaks(context, width, height, colors) {
    const samples = waveformAudioBuffer.getChannelData(0);
    const centerY = Math.floor((height - 18) * 0.52);
    const amplitude = Math.max(24, Math.floor((height - 32) * 0.42));

    context.strokeStyle = colors.waveform;
    context.lineWidth = 1;
    context.beginPath();
    context.moveTo(0, centerY + 0.5);
    context.lineTo(width, centerY + 0.5);
    context.stroke();

    context.strokeStyle = colors.waveform;
    for (let x = 0; x < width; x += 1) {
        const start = Math.floor((x / width) * samples.length);
        const end = Math.max(start + 1, Math.floor(((x + 1) / width) * samples.length));
        const stride = Math.max(1, Math.floor((end - start) / 400));
        let min = 1;
        let max = -1;

        for (let i = start; i < end; i += stride) {
            const sample = samples[i] || 0;
            if (sample < min) {
                min = sample;
            }
            if (sample > max) {
                max = sample;
            }
        }

        const y1 = centerY - max * amplitude;
        const y2 = centerY - min * amplitude;
        context.beginPath();
        context.moveTo(x + 0.5, y1);
        context.lineTo(x + 0.5, y2);
        context.stroke();
    }
}

function drawBarkMarkers(context, width, height, colors) {
    const markers = getBarkMarkers();
    if (markers.length === 0) {
        return;
    }

    const duration = getWaveformDuration();
    const labelMarkers = width / markers.length > 24;

    markers.forEach((marker, index) => {
        const offset = getMarkerClipOffset(marker);
        if (offset === null) {
            return;
        }
        const x = Math.max(0, Math.min(width, (offset / duration) * width));
        const markerColor = getMarkerColor(marker, colors);

        context.strokeStyle = markerColor;
        context.fillStyle = markerColor;
        context.lineWidth = 2;
        context.beginPath();
        context.moveTo(x + 0.5, 8);
        context.lineTo(x + 0.5, height - 19);
        context.stroke();

        context.beginPath();
        context.arc(x, 13, 6, 0, Math.PI * 2);
        context.fill();

        if (labelMarkers) {
            context.fillStyle = colors.pinText;
            context.font = '9px "IBM Plex Mono", monospace';
            context.textAlign = 'center';
            context.textBaseline = 'middle';
            context.fillText(String(marker.index || index + 1), x, 13);
            context.textAlign = 'start';
            context.textBaseline = 'alphabetic';
        }
    });
}

function drawPlaybackHead(context, width, height, colors) {
    const audio = document.getElementById('detailAudioPlayer');
    const duration = getWaveformDuration();
    if (!Number.isFinite(audio.currentTime) || audio.currentTime <= 0 || duration <= 0) {
        return;
    }

    const x = Math.max(0, Math.min(width, (audio.currentTime / duration) * width));
    context.strokeStyle = colors.playhead;
    context.lineWidth = 2;
    context.beginPath();
    context.moveTo(x + 0.5, 0);
    context.lineTo(x + 0.5, height);
    context.stroke();
}

function seekFromWaveformClick(event) {
    if (!waveformAudioBuffer) {
        return;
    }
    const audio = document.getElementById('detailAudioPlayer');
    const canvas = document.getElementById('waveformCanvas');
    const bounds = canvas.getBoundingClientRect();
    const x = Math.max(0, Math.min(bounds.width, event.clientX - bounds.left));
    const duration = getWaveformDuration();
    audio.currentTime = (x / bounds.width) * duration;
    requestWaveformDraw();
}

function getBarkMarkers() {
    return Array.isArray(currentEvent?.bark_markers) ? currentEvent.bark_markers : [];
}

function getMarkerClipOffset(marker) {
    const clipOffset = Number(marker.clip_offset_sec);
    if (Number.isFinite(clipOffset)) {
        return clipOffset;
    }
    const offset = Number(marker.offset_sec);
    return Number.isFinite(offset) ? offset : null;
}

function getMarkerColor(marker, colors) {
    if (marker.direction === 'left') {
        return colors.left;
    }
    if (marker.direction === 'right') {
        return colors.right;
    }
    if (marker.direction === 'center') {
        return colors.center;
    }
    return colors.marker;
}

function getWaveformDuration() {
    if (waveformAudioBuffer?.duration) {
        return waveformAudioBuffer.duration;
    }
    return Math.max(1, Number(currentEvent?.duration_sec) || 1);
}

function getGridStep(duration, zoom) {
    const visibleDuration = duration / Math.max(1, zoom);
    if (visibleDuration <= 20) {
        return 2;
    }
    if (visibleDuration <= 60) {
        return 5;
    }
    if (visibleDuration <= 180) {
        return 10;
    }
    if (visibleDuration <= 600) {
        return 30;
    }
    return 60;
}

function getWaveformColors() {
    return {
        background: getCssColor('--surface-2', '#f5f7f2'),
        grid: getCssColor('--border', '#d8ddd4'),
        textMuted: getCssColor('--text-2', '#57625b'),
        waveform: getCssColor('--accent', '#1e7a3c'),
        marker: getCssColor('--warn-text', '#8a5300'),
        left: getCssColor('--info', '#20578f'),
        right: getCssColor('--danger', '#b3261e'),
        center: getCssColor('--accent-strong', '#15592b'),
        playhead: getCssColor('--danger', '#b3261e'),
        pinText: '#ffffff',
    };
}

function getCssColor(name, fallback) {
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback;
}

function formatMarkerState() {
    const count = getBarkMarkers().length;
    if (count === 0) {
        return 'No bark markers saved';
    }
    return `${count} bark marker${count === 1 ? '' : 's'}`;
}

function setWaveformState(message) {
    const state = document.getElementById('waveformState');
    state.textContent = message;
    state.hidden = !waveformEnabled || !message;
}

function showDetailError(message) {
    const error = document.getElementById('detailError');
    error.textContent = message;
    error.hidden = false;
}

function formatDuration(seconds) {
    const totalSeconds = Math.max(0, Math.round(Number(seconds) || 0));
    if (totalSeconds < 60) {
        return `${totalSeconds}s`;
    }
    const minutes = Math.floor(totalSeconds / 60);
    const remainder = totalSeconds % 60;
    if (minutes < 60) {
        return remainder > 0 ? `${minutes}m ${remainder}s` : `${minutes}m`;
    }
    const hours = Math.floor(minutes / 60);
    const minuteRemainder = minutes % 60;
    return minuteRemainder > 0 ? `${hours}h ${minuteRemainder}m` : `${hours}h`;
}

function formatPercent(value) {
    if (value === null || value === undefined) {
        return '-';
    }
    return `${(Number(value) * 100).toFixed(1)}%`;
}

function formatThreshold(value) {
    if (value === null || value === undefined) {
        return 'Not recorded';
    }
    return Number(value).toFixed(3);
}

function formatAudioLevel(event) {
    const peak = event.peak_audio_level;
    const avg = event.avg_audio_level;
    if (peak === null || peak === undefined) {
        return 'Not recorded';
    }
    const peakText = `${(Number(peak) * 100).toFixed(0)}% peak`;
    if (avg === null || avg === undefined) {
        return peakText;
    }
    return `${peakText}, ${(Number(avg) * 100).toFixed(0)}% avg`;
}

function formatWeather(event) {
    if (event.weather_temp_f === null || event.weather_temp_f === undefined) {
        return 'not recorded';
    }
    const wind = event.weather_wind_mph !== null && event.weather_wind_mph !== undefined
        ? `, ${Number(event.weather_wind_mph).toFixed(1)} mph`
        : '';
    return `${Number(event.weather_temp_f).toFixed(1)} F${wind}, ${event.weather_conditions || 'unknown'}`;
}

function formatMarkerTime(seconds) {
    const totalSeconds = Math.max(0, Math.round(seconds));
    const minutes = Math.floor(totalSeconds / 60);
    const remainder = totalSeconds % 60;
    return `${minutes}:${String(remainder).padStart(2, '0')}`;
}
