document.addEventListener('DOMContentLoaded', function() {
    const page = document.querySelector('.detail-page');
    const eventId = page ? page.dataset.eventId : null;
    if (!eventId) {
        showDetailError('Incident id missing.');
        return;
    }
    fetchEventDetail(eventId);
});

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
        ? (event.false_pos_reason || 'False positive')
        : 'Valid incident';
    document.getElementById('detailHash').textContent = event.clip_hash || 'No clip fingerprint';
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
