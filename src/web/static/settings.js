document.addEventListener('DOMContentLoaded', function() {
    setupSettingsListeners();
    loadSettingsPage();
    loadHealthDetails();
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
            status.textContent = data.message;
            loadSettingsPage();
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
        `Current rule: start after ${minBarks} bark detection${minBarks === 1 ? '' : 's'}, ` +
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
