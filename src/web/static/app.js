// State
let currentPage = 1;
let totalPages = 1;
let eventsPerPage = 20;

// Filter state
let dateFilter = '';
let falsePositiveFilter = '';

// Modal state
let reportModal = null;
let settingsModal = null;

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    initializeElements();
    setupEventListeners();
    fetchEvents();
    fetchStatus();

    // Set today's date as default for report modal
    const today = new Date().toISOString().split('T')[0];
    document.getElementById('endDate').value = today;
    document.getElementById('startDate').value = today;
});

// Initialize DOM elements
function initializeElements() {
    reportModal = document.getElementById('reportModal');
    settingsModal = document.getElementById('settingsModal');
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
    document.getElementById('downloadCsvBtn').addEventListener('click', downloadCsv);

    // Test audio button
    document.getElementById('testAudioBtn').addEventListener('click', testAudioDetection);

    // Settings modal listeners
    document.getElementById('settingsBtn').addEventListener('click', showSettingsModal);
    document.getElementById('closeSettingsBtn').addEventListener('click', hideSettingsModal);
    document.getElementById('cancelSettingsBtn').addEventListener('click', hideSettingsModal);
    document.getElementById('saveSettingsBtn').addEventListener('click', saveSettings);

    // Threshold slider
    document.getElementById('threshold').addEventListener('input', function() {
        document.getElementById('thresholdValue').textContent = this.value;
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
        if (event.target === settingsModal) {
            hideSettingsModal();
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

    tbody.innerHTML = events.map(event => {
        const timestamp = new Date(event.timestamp);
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

        const duration = event.duration ? event.duration.toFixed(2) : 'N/A';
        const score = event.confidence ? (event.confidence * 100).toFixed(1) : 'N/A';

        const direction = event.direction === 'left'
            ? '<span class="direction-left">←</span>'
            : '<span class="direction-right">→</span>';

        const clipButton = event.clip_path
            ? `<button class="btn btn-action btn-play" onclick="playClip('${event.clip_path}')">Play</button>`
            : '<button class="btn btn-action btn-play" disabled>No Clip</button>';

        const isFlaggedFalsePositive = event.flagged_as_false_positive || false;
        const flagButtonClass = isFlaggedFalsePositive ? 'btn-flag flagged' : 'btn-flag';
        const flagButtonText = isFlaggedFalsePositive ? 'Unflag' : 'Flag';

        const flagButton = `<button class="btn btn-action ${flagButtonClass}" onclick="toggleFlag(this, '${event.id}', ${isFlaggedFalsePositive})">${flagButtonText}</button>`;

        const rowClass = isFlaggedFalsePositive ? 'false-positive' : '';

        return `
            <tr class="${rowClass}">
                <td class="event-time" title="${dateString} ${timeString}">${timeString}</td>
                <td class="event-duration">${duration}s</td>
                <td class="event-score">${score}%</td>
                <td>${direction}</td>
                <td>${clipButton}</td>
                <td class="actions">${flagButton}</td>
            </tr>
        `;
    }).join('');
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

// Play audio clip
function playClip(clipPath) {
    const audioPlayer = document.getElementById('audioPlayer');
    audioPlayer.src = `/api/clips/${clipPath}`;
    audioPlayer.play().catch(error => {
        console.error('Error playing audio:', error);
        alert('Error playing audio clip');
    });
}

// Toggle flag status
function toggleFlag(button, eventId, isFlagged) {
    const endpoint = isFlagged ? `/api/events/${eventId}/unflag` : `/api/events/${eventId}/flag`;
    const method = 'POST';
    const body = !isFlagged ? JSON.stringify({ reason: 'Flagged as false positive' }) : null;

    fetch(endpoint, {
        method: method,
        headers: {
            'Content-Type': 'application/json',
        },
        body: body
    })
    .then(response => {
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        // Refresh events to reflect the flag change
        fetchEvents();
    })
    .catch(error => {
        console.error('Error toggling flag:', error);
        alert('Error updating event status');
    });
}

// Show report modal
function showReportModal() {
    reportModal.classList.add('show');
}

// Hide report modal
function hideReportModal() {
    reportModal.classList.remove('show');
}

// Download report
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

// Download CSV export
function downloadCsv() {
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

    const csvUrl = `/api/reports/csv?start_date=${startDate}&end_date=${endDate}`;
    window.location.href = csvUrl;

    // Close modal after initiating download
    setTimeout(hideReportModal, 500);
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

// Start SSE connection for live updates
connectStatusStream();

// Show settings modal
function showSettingsModal() {
    // Load devices and current settings
    Promise.all([
        fetch('/api/devices').then(r => r.json()),
        fetch('/api/settings').then(r => r.json())
    ])
    .then(([devicesData, settingsData]) => {
        // Populate device dropdown
        const deviceSelect = document.getElementById('audioDevice');
        deviceSelect.innerHTML = '<option value="auto">Auto-detect stereo mic</option>';

        if (devicesData.devices) {
            const currentDevice = settingsData.audio ? settingsData.audio.device : null;
            devicesData.devices.forEach(device => {
                const stereoLabel = device.is_stereo ? ' (stereo)' : ' (mono)';
                const option = document.createElement('option');
                option.value = device.id;
                option.textContent = device.name + stereoLabel;
                // Use == for type coercion (device.id might be string, currentDevice might be number)
                if (currentDevice !== null && currentDevice == device.id) {
                    option.selected = true;
                }
                deviceSelect.appendChild(option);
            });
        }

        // Set current values
        if (settingsData.detection) {
            const threshold = settingsData.detection.threshold || 0.5;
            document.getElementById('threshold').value = threshold;
            document.getElementById('thresholdValue').textContent = threshold;
        }

        if (settingsData.location) {
            document.getElementById('locationAddress').value = settingsData.location.address || '';
            document.getElementById('locationLat').value = settingsData.location.lat || '';
            document.getElementById('locationLon').value = settingsData.location.lon || '';
        }

        settingsModal.classList.add('show');
    })
    .catch(error => {
        console.error('Error loading settings:', error);
        alert('Error loading settings');
    });
}

// Hide settings modal
function hideSettingsModal() {
    settingsModal.classList.remove('show');
}

// Save settings
function saveSettings() {
    const deviceSelect = document.getElementById('audioDevice');
    const threshold = document.getElementById('threshold').value;
    const address = document.getElementById('locationAddress').value;
    const lat = document.getElementById('locationLat').value;
    const lon = document.getElementById('locationLon').value;

    const settings = {
        audio_device: deviceSelect.value,
        detection_threshold: parseFloat(threshold),
        location_address: address,
        location_lat: lat ? parseFloat(lat) : null,
        location_lon: lon ? parseFloat(lon) : null
    };

    fetch('/api/settings', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(settings)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            alert(data.message);
            hideSettingsModal();
            fetchStatus(); // Refresh status display
        } else {
            alert('Error saving settings: ' + (data.error || 'Unknown error'));
        }
    })
    .catch(error => {
        console.error('Error saving settings:', error);
        alert('Error saving settings');
    });
}

// Test audio detection with sample file
function testAudioDetection() {
    const btn = document.getElementById('testAudioBtn');
    const originalText = btn.textContent;
    btn.textContent = 'Testing...';
    btn.disabled = true;

    fetch('/api/test-audio', { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            btn.textContent = originalText;
            btn.disabled = false;

            if (data.success) {
                // Build result message
                let msg = `Test Results:\n\n`;
                msg += `File: ${data.file}\n`;
                msg += `Duration: ${data.duration_sec}s\n`;
                msg += `Chunks analyzed: ${data.chunks_analyzed}\n`;
                msg += `Threshold: ${data.threshold}\n\n`;
                msg += `Max bark score: ${data.max_score}\n`;
                msg += `Bark detections: ${data.bark_detections}\n\n`;

                if (data.bark_detections > 0) {
                    msg += `SUCCESS: Model detected barking!\n\n`;
                } else if (data.max_score > 0.1) {
                    msg += `PARTIAL: Model heard dog sounds but below threshold.\n`;
                    msg += `Try lowering threshold in Settings.\n\n`;
                } else {
                    msg += `ISSUE: Model did not detect dog sounds.\n\n`;
                }

                // Show some details
                msg += `Sample detections:\n`;
                const samples = data.details.slice(0, 5);
                samples.forEach(d => {
                    msg += `  ${d.time_sec}s: score=${d.score} [${d.top_classes.join(', ')}]\n`;
                });

                alert(msg);
            } else {
                alert('Test failed: ' + (data.detail || 'Unknown error'));
            }
        })
        .catch(error => {
            btn.textContent = originalText;
            btn.disabled = false;
            console.error('Error testing audio:', error);
            alert('Error running test: ' + error.message);
        });
}
