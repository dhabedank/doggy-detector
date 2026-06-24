document.addEventListener('DOMContentLoaded', function() {
    setupSettingsListeners();
    loadSettingsPage();
    loadHealthDetails();
    loadUpdateStatus();
});

function setupSettingsListeners() {
    document.getElementById('threshold').addEventListener('input', function() {
        document.getElementById('thresholdNumber').value = formatThreshold(this.value);
        updateTimingSummary();
    });
    document.getElementById('thresholdNumber').addEventListener('input', function() {
        if (this.value === '') {
            return;
        }
        const value = clampThreshold(this.value);
        document.getElementById('threshold').value = value;
        updateTimingSummary();
    });

    ['minBarks', 'gapSec', 'mergeWithinSec', 'preRollSec', 'minDurationSec'].forEach(id => {
        document.getElementById(id).addEventListener('input', updateTimingSummary);
        document.getElementById(id).addEventListener('change', updateTimingSummary);
    });

    document.getElementById('settingsForm').addEventListener('submit', function(event) {
        event.preventDefault();
        saveSettings();
    });

    document.getElementById('refreshHealthBtn').addEventListener('click', loadHealthDetails);
    document.getElementById('updateCheckBtn').addEventListener('click', checkForUpdates);
    document.getElementById('updateInstallBtn').addEventListener('click', requestUpdateInstall);
    document.getElementById('systemRestartBtn').addEventListener('click', requestSystemRestart);
    document.getElementById('deterrenceEnabled').addEventListener('change', updateDeterrenceVisibility);
}

function updateDeterrenceVisibility() {
    const enabled = document.getElementById('deterrenceEnabled').checked;
    document.getElementById('deterrenceFields').hidden = !enabled;
}

function loadSettingsPage() {
    Promise.all([
        fetch('/api/devices').then(response => response.json()),
        fetch('/api/settings').then(response => response.json())
    ])
    .then(([devicesData, settingsData]) => {
        populateDevices(devicesData, settingsData);
        populateSettings(settingsData);
        updateTimingSummary();
    })
    .catch(error => {
        console.error('Error loading settings:', error);
        document.getElementById('settingsSaveStatus').textContent = 'Error loading settings.';
    });
}

function populateDevices(devicesData, settingsData) {
    const deviceSelect = document.getElementById('audioDevice');
    deviceSelect.innerHTML = '<option value="auto">System default input</option>';

    const currentDevice = settingsData.audio ? settingsData.audio.device : null;
    if (devicesData.devices) {
        devicesData.devices.forEach(device => {
            const stereoLabel = device.is_stereo ? ' (stereo)' : ' (mono)';
            const option = document.createElement('option');
            option.value = device.key || device.name;
            const hostLabel = device.hostapi ? ` - ${device.hostapi}` : '';
            option.textContent = `[${device.id}] ${device.name}${stereoLabel}${hostLabel}`;
            if (
                currentDevice !== null &&
                (currentDevice == device.id || currentDevice === option.value || currentDevice === device.name)
            ) {
                option.selected = true;
            }
            deviceSelect.appendChild(option);
        });
    }
}

function populateSettings(settingsData) {
    const detection = settingsData.detection || {};
    const incidents = settingsData.incidents || {};
    const location = settingsData.location || {};
    const deterrence = settingsData.deterrence || {};

    const threshold = detection.threshold ?? 0.15;
    document.getElementById('threshold').value = threshold;
    document.getElementById('thresholdNumber').value = formatThreshold(threshold);
    document.getElementById('minBarks').value = incidents.min_barks ?? 2;
    document.getElementById('gapSec').value = incidents.gap_sec ?? 15;
    document.getElementById('mergeWithinSec').value = incidents.merge_within_sec ?? 10;
    document.getElementById('preRollSec').value = incidents.pre_roll_sec ?? 15;
    document.getElementById('minDurationSec').value = incidents.min_duration_sec ?? 1;
    document.getElementById('locationAddress').value = location.address || '';
    document.getElementById('locationLat').value = location.lat ?? '';
    document.getElementById('locationLon').value = location.lon ?? '';
    document.getElementById('deterrenceEnabled').checked = deterrence.enabled !== false;
    updateDeterrenceVisibility();
    document.getElementById('deterrenceAudibleEnabled').checked = Boolean(deterrence.audible_enabled);
    document.getElementById('deterrenceUltrasonicEnabled').checked = Boolean(deterrence.ultrasonic_enabled);
    document.getElementById('deterrenceManualEnabled').checked = deterrence.manual_enabled !== false;
    document.getElementById('deterrenceAutoEnabled').checked = Boolean(deterrence.auto_enabled);
    document.getElementById('deterrenceThreshold').value = deterrence.bark_score_threshold ?? 0.15;
    document.getElementById('deterrenceCooldownSec').value = deterrence.cooldown_sec ?? 10;
    document.getElementById('deterrenceBurstSec').value = deterrence.burst_sec ?? 2;
    document.getElementById('deterrenceMaxIncident').value = deterrence.max_fires_per_incident ?? 3;
    document.getElementById('deterrenceMaxDay').value = deterrence.max_fires_per_day ?? 50;
    document.getElementById('deterrenceProfile').value = deterrence.audible_profile || 'chirp';
    document.getElementById('deterrenceOutputDevice').value = deterrence.audible_output_device ?? '';
    document.getElementById('deterrenceGpioPin').value = deterrence.ultrasonic_gpio_pin ?? '';
    document.getElementById('deterrenceActiveHigh').checked = deterrence.ultrasonic_active_high !== false;
    document.getElementById('deterrenceQuietEnabled').checked = Boolean(deterrence.quiet_hours_enabled);
    document.getElementById('deterrenceQuietStart').value = deterrence.quiet_hours_start || '22:00';
    document.getElementById('deterrenceQuietEnd').value = deterrence.quiet_hours_end || '07:00';
}

function saveSettings() {
    const status = document.getElementById('settingsSaveStatus');
    status.textContent = 'Saving...';

    const lat = document.getElementById('locationLat').value;
    const lon = document.getElementById('locationLon').value;
    const settings = {
        audio_device: document.getElementById('audioDevice').value,
        detection_threshold: clampThreshold(document.getElementById('thresholdNumber').value),
        incidents_min_barks: parseInt(document.getElementById('minBarks').value, 10),
        incidents_gap_sec: parseFloat(document.getElementById('gapSec').value),
        incidents_merge_within_sec: parseFloat(document.getElementById('mergeWithinSec').value),
        incidents_min_duration_sec: parseFloat(document.getElementById('minDurationSec').value),
        incidents_pre_roll_sec: parseFloat(document.getElementById('preRollSec').value),
        location_address: document.getElementById('locationAddress').value,
        location_lat: lat ? parseFloat(lat) : null,
        location_lon: lon ? parseFloat(lon) : null
    };
    const gpioPin = document.getElementById('deterrenceGpioPin').value;
    const outputDevice = document.getElementById('deterrenceOutputDevice').value;
    const deterrenceSettings = {
        enabled: document.getElementById('deterrenceEnabled').checked,
        audible_enabled: document.getElementById('deterrenceAudibleEnabled').checked,
        ultrasonic_enabled: document.getElementById('deterrenceUltrasonicEnabled').checked,
        manual_enabled: document.getElementById('deterrenceManualEnabled').checked,
        auto_enabled: document.getElementById('deterrenceAutoEnabled').checked,
        assertiveness: 'assertive',
        bark_score_threshold: clampThreshold(document.getElementById('deterrenceThreshold').value),
        cooldown_sec: parseFloat(document.getElementById('deterrenceCooldownSec').value),
        burst_sec: parseFloat(document.getElementById('deterrenceBurstSec').value),
        max_fires_per_incident: parseInt(document.getElementById('deterrenceMaxIncident').value, 10),
        max_fires_per_day: parseInt(document.getElementById('deterrenceMaxDay').value, 10),
        audible_profile: document.getElementById('deterrenceProfile').value,
        audible_output_device: outputDevice ? outputDevice : null,
        ultrasonic_gpio_pin: gpioPin ? parseInt(gpioPin, 10) : null,
        ultrasonic_active_high: document.getElementById('deterrenceActiveHigh').checked,
        quiet_hours_enabled: document.getElementById('deterrenceQuietEnabled').checked,
        quiet_hours_start: document.getElementById('deterrenceQuietStart').value || '22:00',
        quiet_hours_end: document.getElementById('deterrenceQuietEnd').value || '07:00'
    };

    Promise.all([
        fetch('/api/settings', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(settings)
        }).then(response => response.json()),
        fetch('/api/deterrence/settings', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(deterrenceSettings)
        }).then(response => response.json())
    ])
    .then(([settingsResult, deterrenceResult]) => {
        if (settingsResult.success && deterrenceResult.success) {
            status.textContent = settingsResult.message;
            loadSettingsPage();
            loadHealthDetails();
        } else {
            status.textContent = 'Error saving settings.';
        }
    })
    .catch(error => {
        console.error('Error saving settings:', error);
        status.textContent = 'Error saving settings.';
    });
}

function clampThreshold(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) {
        return 0.15;
    }
    return Math.max(0.001, Math.min(1.0, numeric));
}

function formatThreshold(value) {
    return Number(clampThreshold(value)).toFixed(3);
}

function updateTimingSummary() {
    const minBarks = Number(document.getElementById('minBarks').value || 0);
    const gapSec = Number(document.getElementById('gapSec').value || 0);
    const mergeWithinSec = Number(document.getElementById('mergeWithinSec').value || 0);
    const preRollSec = Number(document.getElementById('preRollSec').value || 0);
    const finalizeAfter = gapSec + mergeWithinSec;

    document.getElementById('incidentTimingSummary').textContent =
        `Current rule: start after ${minBarks} positive detection window${minBarks === 1 ? '' : 's'}, ` +
        `enter cooldown after ${gapSec}s without a bark above threshold, ` +
        `save after ${finalizeAfter}s without a new bark, and include ${preRollSec}s of pre-roll audio.`;
}

function loadHealthDetails() {
    fetch('/health')
        .then(response => response.json())
        .then(renderHealthDetails)
        .catch(error => {
            console.error('Error loading health details:', error);
            document.getElementById('diagnosticsState').textContent = 'Error';
            document.getElementById('settingsHealthChecks').innerHTML =
                '<div class="health-empty">Could not load health checks.</div>';
        });
}

function loadUpdateStatus() {
    fetch('/api/update/status')
        .then(response => response.json())
        .then(renderUpdateStatus)
        .catch(error => {
            console.error('Error loading update status:', error);
            document.getElementById('updateMessage').textContent = 'Could not load update status.';
        });
}

function checkForUpdates() {
    const button = document.getElementById('updateCheckBtn');
    button.disabled = true;
    document.getElementById('updateMessage').textContent = 'Checking for releases...';
    fetch('/api/update/check', {method: 'POST'})
        .then(response => response.json())
        .then(data => {
            if (data.detail) {
                document.getElementById('updateMessage').textContent = data.detail;
                return;
            }
            renderUpdateStatus(data);
        })
        .catch(error => {
            console.error('Error checking updates:', error);
            document.getElementById('updateMessage').textContent = 'Update check failed.';
        })
        .finally(() => {
            button.disabled = false;
        });
}

function requestUpdateInstall() {
    const button = document.getElementById('updateInstallBtn');
    const target = document.getElementById('updateTarget').value || 'latest';
    button.disabled = true;
    document.getElementById('updateMessage').textContent = 'Queueing update...';
    fetch('/api/update/request', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({target})
    })
        .then(response => response.json())
        .then(data => {
            renderUpdateStatus(data);
            const trigger = data.service_trigger || {};
            if (trigger.triggered) {
                document.getElementById('updateMessage').textContent =
                    'Update queued. The dashboard may briefly disconnect during restart.';
            } else if (trigger.error) {
                document.getElementById('updateMessage').textContent =
                    `Update queued, but the service did not start: ${trigger.error}`;
            }
        })
        .catch(error => {
            console.error('Error requesting update:', error);
            document.getElementById('updateMessage').textContent = 'Could not queue update.';
        })
        .finally(() => {
            setTimeout(loadUpdateStatus, 1500);
            button.disabled = false;
        });
}

function requestSystemRestart() {
    const button = document.getElementById('systemRestartBtn');
    const status = document.getElementById('systemRestartStatus');
    const confirmed = window.confirm(
        'Restart Doggy Detector now? The dashboard may disconnect for a few seconds.'
    );

    if (!confirmed) {
        return;
    }

    button.disabled = true;
    status.textContent = 'Queueing restart...';

    fetch('/api/system/restart', {method: 'POST'})
        .then(async response => {
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.detail || 'Could not queue restart.');
            }
            return data;
        })
        .then(data => {
            status.textContent = data.message || 'Restart queued.';
            setTimeout(loadHealthDetails, 8000);
        })
        .catch(error => {
            console.error('Error restarting detector:', error);
            status.textContent = error.message || 'Could not queue restart.';
        })
        .finally(() => {
            setTimeout(() => {
                button.disabled = false;
            }, 3000);
        });
}

function renderUpdateStatus(update) {
    const current = update.current_version || 'unknown';
    const latest = update.latest_version || 'unknown';
    const state = update.state || 'idle';
    const lastChecked = update.last_checked_at ? formatDateTime(update.last_checked_at) : 'Never';
    const pending = update.pending_request || null;
    const message = updateMessageForState(update, pending);

    document.getElementById('updateCurrentVersion').textContent = current;
    document.getElementById('updateLatestVersion').textContent = latest;
    document.getElementById('updateState').textContent = state;
    document.getElementById('updateLastCheck').textContent = lastChecked;
    document.getElementById('updateMessage').textContent = message;
    document.getElementById('updateInstallBtn').disabled = state === 'updating';

    renderUpdateLog(update.logs || []);
}

function updateMessageForState(update, pending) {
    if (update.last_error) {
        return update.last_error;
    }
    if (pending) {
        return `Queued for ${pending.target || 'latest'}.`;
    }
    if (update.update_available) {
        return `Release ${update.latest_version} is available.`;
    }
    if (update.latest_version) {
        return 'Installed release is current.';
    }
    return 'No release check has completed yet.';
}

function renderUpdateLog(logs) {
    const container = document.getElementById('updateLog');
    if (!logs.length) {
        container.innerHTML = '<div class="health-empty">No update logs yet.</div>';
        return;
    }
    container.innerHTML = logs.slice(-8).reverse().map(entry => `
        <div class="update-log-entry">
            <span>${escapeHtml(formatDateTime(entry.at))}</span>
            <strong>${escapeHtml(entry.message)}</strong>
        </div>
    `).join('');
}

function formatDateTime(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return value || '-';
    }
    return date.toLocaleString();
}

function renderHealthDetails(health) {
    const checks = health.checks || [];
    const state = health.state || 'unknown';
    const generatedAt = health.generated_at ? new Date(health.generated_at) : null;
    const generatedText = generatedAt && !Number.isNaN(generatedAt.getTime())
        ? `Generated ${generatedAt.toLocaleString()}`
        : 'Generated time unavailable';

    const diagnosticsState = document.getElementById('diagnosticsState');
    diagnosticsState.textContent = state.toUpperCase();
    diagnosticsState.className = `diagnostics-state diagnostics-${state}`;
    document.getElementById('diagnosticsGenerated').textContent = generatedText;

    const container = document.getElementById('settingsHealthChecks');
    if (!checks.length) {
        container.innerHTML = '<div class="health-empty">No health checks available.</div>';
        return;
    }

    container.innerHTML = checks.map(check => `
        <div class="health-check health-${check.state}">
            <span class="health-state">${check.state}</span>
            <strong>${escapeHtml(check.name.replaceAll('_', ' '))}</strong>
            <span>${escapeHtml(check.message)}</span>
        </div>
    `).join('');
}

function escapeHtml(value) {
    return String(value)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');
}
