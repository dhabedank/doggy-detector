// State
let currentPage = 1;
let totalPages = 1;
let eventsPerPage = 20;

// Filter state
let dateFilter = '';
let falsePositiveFilter = '';

// Modal state
let reportModal = null;
let eventDetailModal = null;
let falsePositiveModal = null;
let pendingFalsePositiveEventId = null;
let selectedFalsePositiveReason = 'speech';
let eventCache = {};

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    initializeElements();
    setupEventListeners();
    fetchEvents();
    fetchSummary();
    fetchStatus();

    // Set today's date as default for report modal
    const today = new Date().toISOString().split('T')[0];
    document.getElementById('endDate').value = today;
    document.getElementById('startDate').value = today;
});

// Initialize DOM elements
function initializeElements() {
    reportModal = document.getElementById('reportModal');
    eventDetailModal = document.getElementById('eventDetailModal');
    falsePositiveModal = document.getElementById('falsePositiveModal');
}

// Setup event listeners
function setupEventListeners() {
    // Filter listeners
    document.getElementById('dateFilter').addEventListener('change', function() {
        dateFilter = this.value;
        currentPage = 1;
        fetchEvents();
    });

    document.getElementById('falsePositiveFilter').addEventListener('change', function() {
        falsePositiveFilter = this.value;
        currentPage = 1;
        fetchEvents();
    });

    // Button listeners
    document.getElementById('refreshBtn').addEventListener('click', function() {
        currentPage = 1;
        fetchEvents();
    });

    document.getElementById('generateReportBtn').addEventListener('click', showReportModal);
    document.getElementById('closeReportBtn').addEventListener('click', hideReportModal);
    document.getElementById('cancelReportBtn').addEventListener('click', hideReportModal);
    document.getElementById('downloadReportBtn').addEventListener('click', downloadReport);

    // Event detail modal listeners
    document.getElementById('closeEventDetailBtn').addEventListener('click', hideEventDetailModal);
    document.getElementById('closeEventDetailFooterBtn').addEventListener('click', hideEventDetailModal);

    // False-positive reason modal listeners
    document.getElementById('closeFalsePositiveBtn').addEventListener('click', hideFalsePositiveModal);
    document.getElementById('cancelFalsePositiveBtn').addEventListener('click', hideFalsePositiveModal);
    document.getElementById('saveFalsePositiveBtn').addEventListener('click', saveFalsePositiveReason);
    document.querySelectorAll('.reason-option').forEach(button => {
        button.addEventListener('click', function() {
            selectedFalsePositiveReason = this.dataset.reason;
            document.querySelectorAll('.reason-option').forEach(option => option.classList.remove('selected'));
            this.classList.add('selected');
            document.getElementById('falsePositiveCustomReason').value = this.dataset.reason;
        });
    });

    // Pagination listeners
    document.getElementById('prevBtn').addEventListener('click', function() {
        if (currentPage > 1) {
            currentPage--;
            fetchEvents();
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }
    });

    document.getElementById('nextBtn').addEventListener('click', function() {
        if (currentPage < totalPages) {
            currentPage++;
            fetchEvents();
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }
    });

    // Close modal on outside click
    window.addEventListener('click', function(event) {
        if (event.target === reportModal) {
            hideReportModal();
        }
        if (event.target === eventDetailModal) {
            hideEventDetailModal();
        }
        if (event.target === falsePositiveModal) {
            hideFalsePositiveModal();
        }
    });
}

// Fetch events from API
function fetchEvents() {
    const params = new URLSearchParams();
    params.append('page', currentPage);
    params.append('per_page', eventsPerPage);

    if (dateFilter === 'today') {
        const today = new Date().toISOString().split('T')[0];
        params.append('date', today);
    }

    if (falsePositiveFilter === 'valid') {
        params.append('include_false_pos', 'false');
    } else if (falsePositiveFilter === 'false_pos') {
        params.append('include_false_pos', 'true');
        params.append('only_false_pos', 'true');
    } else {
        params.append('include_false_pos', 'true');
    }

    const url = `/api/events?${params.toString()}`;

    fetch(url)
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            renderEvents(data.events || []);
            totalPages = data.total_pages || 1;
            updatePagination();
            fetchSummary();
        })
        .catch(error => {
            console.error('Error fetching events:', error);
            const tbody = document.getElementById('eventsTableBody');
            tbody.innerHTML = '<tr class="loading-row"><td colspan="6">Error loading events. Please try again.</td></tr>';
        });
}

// Render events in table
function renderEvents(events) {
    const tbody = document.getElementById('eventsTableBody');

    if (events.length === 0) {
        tbody.innerHTML = '<tr class="loading-row"><td colspan="6">No events found.</td></tr>';
        return;
    }

    eventCache = {};

    tbody.innerHTML = events.map(event => {
        eventCache[event.id] = event;
        const timestamp = new Date(event.started_at);
        const timeString = timestamp.toLocaleTimeString('en-US', {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: true
        });
        const dateString = timestamp.toLocaleDateString('en-US', {
            month: 'short',
            day: 'numeric'
        });

        const duration = event.duration_sec !== null && event.duration_sec !== undefined
            ? Number(event.duration_sec).toFixed(2)
            : 'N/A';
        const score = event.peak_score !== null && event.peak_score !== undefined
            ? (Number(event.peak_score) * 100).toFixed(1)
            : 'N/A';

        const direction = renderDirection(event.direction);

        const clipButton = `<button class="btn btn-action btn-play" onclick="showEventDetail('${event.id}')">${event.clip_url ? 'Details' : 'Details'}</button>`;

        const isFlaggedFalsePositive = event.is_false_pos || false;
        const flagButtonClass = isFlaggedFalsePositive ? 'btn-flag flagged' : 'btn-flag';
        const flagButtonText = isFlaggedFalsePositive ? 'Unflag' : 'Flag';

        const flagButton = `<button class="btn btn-action ${flagButtonClass}" onclick="toggleFlag(this, '${event.id}', ${isFlaggedFalsePositive})">${flagButtonText}</button>`;
        const deleteButton = `<button class="btn btn-action btn-delete" onclick="deleteEvent('${event.id}', '${timeString.replace(/'/g, "\\'")}')">Delete</button>`;

        const rowClass = isFlaggedFalsePositive ? 'false-positive' : '';

        return `
            <tr class="${rowClass}">
                <td class="event-time" title="${dateString} ${timeString}">${timeString}</td>
                <td class="event-duration">${duration}s</td>
                <td class="event-score">${score}%</td>
                <td>${direction}</td>
                <td>${clipButton}</td>
                <td class="actions">${flagButton}${deleteButton}</td>
            </tr>
        `;
    }).join('');
}

function renderDirection(direction) {
    if (direction === 'left') {
        return '<span class="direction-left">←</span>';
    }
    if (direction === 'right') {
        return '<span class="direction-right">→</span>';
    }
    if (direction === 'center') {
        return '<span class="direction-center">↔</span>';
    }
    return '<span class="direction-unknown">?</span>';
}

// Update pagination controls
function updatePagination() {
    const pageInfo = document.getElementById('pageInfo');
    pageInfo.textContent = `Page ${currentPage} of ${totalPages}`;

    const prevBtn = document.getElementById('prevBtn');
    const nextBtn = document.getElementById('nextBtn');

    prevBtn.disabled = currentPage <= 1;
    nextBtn.disabled = currentPage >= totalPages;
}

// Toggle flag status
function toggleFlag(button, eventId, isFlagged) {
    if (!isFlagged) {
        showFalsePositiveModal(eventId);
        return;
    }

    fetch(`/api/events/${eventId}/unflag`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        }
    })
    .then(response => {
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        // Refresh events to reflect the flag change
        fetchEvents();
        fetchSummary();
    })
    .catch(error => {
        console.error('Error toggling flag:', error);
        alert('Error updating event status');
    });
}

function showFalsePositiveModal(eventId) {
    pendingFalsePositiveEventId = eventId;
    selectedFalsePositiveReason = 'speech';
    document.getElementById('falsePositiveCustomReason').value = 'speech';
    document.querySelectorAll('.reason-option').forEach(option => {
        option.classList.toggle('selected', option.dataset.reason === selectedFalsePositiveReason);
    });
    falsePositiveModal.classList.add('show');
}

function hideFalsePositiveModal() {
    falsePositiveModal.classList.remove('show');
    pendingFalsePositiveEventId = null;
}

function saveFalsePositiveReason() {
    if (!pendingFalsePositiveEventId) {
        return;
    }

    const customReason = document.getElementById('falsePositiveCustomReason').value.trim();
    const reason = customReason || selectedFalsePositiveReason;

    fetch(`/api/events/${pendingFalsePositiveEventId}/flag`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ reason: reason })
    })
    .then(response => {
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        hideFalsePositiveModal();
        fetchEvents();
        fetchSummary();
    })
    .catch(error => {
        console.error('Error saving false positive reason:', error);
        alert('Error updating event status');
    });
}

// Delete an event and its referenced clip
function deleteEvent(eventId, eventTime) {
    const confirmed = confirm(`Delete this incident from ${eventTime}? This also removes its saved clip.`);
    if (!confirmed) {
        return;
    }

    fetch(`/api/events/${eventId}`, {
        method: 'DELETE'
    })
    .then(response => {
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        fetchEvents();
        fetchSummary();
    })
    .catch(error => {
        console.error('Error deleting event:', error);
        alert('Error deleting event');
    });
}

function showEventDetail(eventId) {
    const cachedEvent = eventCache[eventId];
    if (cachedEvent) {
        renderEventDetail(cachedEvent);
        eventDetailModal.classList.add('show');
    }

    fetch(`/api/events/${eventId}`)
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(event => {
            eventCache[event.id] = event;
            renderEventDetail(event);
            eventDetailModal.classList.add('show');
        })
        .catch(error => {
            console.error('Error loading event detail:', error);
            alert('Error loading incident details');
        });
}

function renderEventDetail(event) {
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
        ? (event.false_pos_reason || 'yes')
        : 'no';
    document.getElementById('detailHash').textContent = event.clip_hash || 'No clip fingerprint';
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

function hideEventDetailModal() {
    const audio = document.getElementById('detailAudioPlayer');
    audio.pause();
    eventDetailModal.classList.remove('show');
}

// Show report modal
function showReportModal() {
    reportModal.classList.add('show');
}

// Hide report modal
function hideReportModal() {
    reportModal.classList.remove('show');
}

// Download report package
function downloadReport() {
    const startDate = document.getElementById('startDate').value;
    const endDate = document.getElementById('endDate').value;

    if (!startDate || !endDate) {
        alert('Please select both start and end dates');
        return;
    }

    if (new Date(startDate) > new Date(endDate)) {
        alert('Start date must be before end date');
        return;
    }

    const reportUrl = `/api/reports/generate?start_date=${startDate}&end_date=${endDate}`;
    window.location.href = reportUrl;

    // Close modal after initiating download
    setTimeout(hideReportModal, 500);
}

function fetchSummary() {
    fetch('/api/summary')
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => renderSummary(data))
        .catch(error => console.error('Error fetching summary:', error));
}

function renderSummary(data) {
    const today = data.today || {};
    const allTime = data.all_time || {};

    document.getElementById('todayIncidents').textContent = today.incident_count || 0;
    document.getElementById('todayDuration').textContent = formatDuration(today.total_duration_sec || 0);
    document.getElementById('todayLongest').textContent = formatDuration(today.longest_duration_sec || 0);
    document.getElementById('todayPeak').textContent = formatPercent(today.peak_score || 0);
    document.getElementById('allIncidents').textContent = allTime.incident_count || 0;
    document.getElementById('allDuration').textContent = formatDuration(allTime.total_duration_sec || 0);
    document.getElementById('allLongest').textContent = formatDuration(allTime.longest_duration_sec || 0);
    document.getElementById('allPeak').textContent = formatPercent(allTime.peak_score || 0);
}

// Update status display from data
function updateStatusDisplay(data) {
    // Update device name in header
    document.getElementById('deviceName').textContent = data.audio_device || 'Unknown';

    // Update live status bar
    const audioLevel = data.audio_level || 0;
    const score = data.last_score || 0;
    const audioLevelFill = document.getElementById('audioLevelFill');
    const audioLevelValue = document.getElementById('audioLevelValue');
    const scoreFill = document.getElementById('scoreFill');
    const scoreValue = document.getElementById('scoreValue');
    const detectionStatus = document.getElementById('detectionStatus');
    const chunksProcessed = document.getElementById('chunksProcessed');
    const statusDot = document.getElementById('statusDot');
    const statusText = document.getElementById('statusText');

    // Update audio level meter (RMS 0-1 mapped to 0-100%)
    audioLevelFill.style.width = (audioLevel * 100) + '%';
    audioLevelValue.textContent = audioLevel.toFixed(2);

    // Update bark score meter (0-1 mapped to 0-100%)
    scoreFill.style.width = (score * 100) + '%';
    scoreValue.textContent = score.toFixed(3);

    // Update chunks count
    if (data.chunks_processed !== undefined) {
        chunksProcessed.textContent = data.chunks_processed.toLocaleString();
    }

    const health = data.health || { state: data.audio_error ? 'critical' : 'unknown', checks: [] };
    const healthState = health.state || 'unknown';
    const healthProblems = (health.checks || [])
        .filter(check => check.state !== 'ok')
        .map(check => check.message);

    statusDot.classList.remove('stopped', 'warn', 'critical', 'unknown');
    if (healthState !== 'ok') {
        statusDot.classList.add(healthState === 'warn' ? 'warn' : 'critical');
    }
    statusText.textContent = healthState.toUpperCase();
    statusText.title = healthProblems.length > 0 ? healthProblems.join(' | ') : 'All health checks are OK';
    statusDot.title = statusText.title;
    renderOperationsSummary(data, health);

    // Update detection status
    detectionStatus.classList.remove('listening', 'barking', 'incident', 'error');
    if (data.audio_error) {
        detectionStatus.textContent = 'AUDIO ERROR: ' + data.audio_error;
        detectionStatus.classList.add('error');
    } else if (data.active_incident) {
        detectionStatus.textContent = 'INCIDENT IN PROGRESS';
        detectionStatus.classList.add('incident');
    } else if (data.is_barking) {
        detectionStatus.textContent = 'BARK DETECTED!';
        detectionStatus.classList.add('barking');
    } else if (data.chunks_processed > 0) {
        const modeText = data.mono_mode ? ' (mono - no direction)' : '';
        detectionStatus.textContent = 'Listening...' + modeText;
        detectionStatus.classList.add('listening');
    } else {
        detectionStatus.textContent = 'Starting...';
        detectionStatus.classList.add('listening');
    }
}

function renderOperationsSummary(data, health) {
    const checks = health.checks || [];
    const detectorCheck = findHealthCheck(checks, 'detector');
    const diskCheck = findHealthCheck(checks, 'disk_free');
    const urgent = checks.filter(check => ['critical', 'unknown'].includes(check.state));
    const warnings = checks.filter(check => check.state === 'warn');

    document.getElementById('opsDetector').textContent = detectorCheck
        ? shortHealthMessage(detectorCheck)
        : (data.audio_error ? 'Audio error' : 'Running');
    document.getElementById('opsUptime').textContent = formatUptime(data.startup_at);
    document.getElementById('opsDisk').textContent = diskCheck ? diskCheck.message : '-';

    const alerts = urgent.length > 0 ? urgent : warnings;
    const alertText = alerts.length > 0
        ? `${alerts.length} ${urgent.length > 0 ? 'urgent' : 'warning'}`
        : 'None';
    const alertMessages = alerts.map(check => `${check.name.replaceAll('_', ' ')}: ${check.message}`).join(' | ');
    const opsAlerts = document.getElementById('opsAlerts');
    opsAlerts.textContent = alertText;
    opsAlerts.title = alertMessages || 'No urgent health alerts';
    document.getElementById('opsStrip').classList.toggle('has-alerts', alerts.length > 0);
}

function findHealthCheck(checks, name) {
    return checks.find(check => check.name === name);
}

function shortHealthMessage(check) {
    if (check.state === 'ok') {
        return 'Running';
    }
    if (check.state === 'warn') {
        return 'Warning';
    }
    if (check.state === 'critical') {
        return 'Critical';
    }
    return 'Unknown';
}

function formatUptime(startupAt) {
    if (!startupAt) {
        return '-';
    }
    const started = new Date(startupAt);
    if (Number.isNaN(started.getTime())) {
        return '-';
    }
    return formatDuration((Date.now() - started.getTime()) / 1000);
}

// Connect to Server-Sent Events for live status (no polling, no log spam)
function connectStatusStream() {
    const eventSource = new EventSource('/api/status/stream');

    eventSource.addEventListener('status', function(event) {
        const data = JSON.parse(event.data);
        updateStatusDisplay(data);
    });

    eventSource.onerror = function(error) {
        console.error('Status stream error, reconnecting...', error);
        eventSource.close();
        // Reconnect after 2 seconds
        setTimeout(connectStatusStream, 2000);
    };
}

// Fetch status once on load (fallback), then use SSE
function fetchStatus() {
    fetch('/api/status')
        .then(response => response.json())
        .then(data => updateStatusDisplay(data))
        .catch(error => {
            console.error('Error fetching status:', error);
            document.getElementById('deviceName').textContent = 'Error';
        });
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

function formatWeather(event) {
    if (event.weather_temp_f === null || event.weather_temp_f === undefined) {
        return 'not recorded';
    }
    const wind = event.weather_wind_mph !== null && event.weather_wind_mph !== undefined
        ? `, ${Number(event.weather_wind_mph).toFixed(1)} mph`
        : '';
    return `${Number(event.weather_temp_f).toFixed(1)} F${wind}, ${event.weather_conditions || 'unknown'}`;
}

function escapeHtml(value) {
    return String(value)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');
}

// Start SSE connection for live updates
connectStatusStream();
