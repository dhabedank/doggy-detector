let selectedRange = '30d';
let exactStartAt = '';
let exactEndAt = '';

document.addEventListener('DOMContentLoaded', function() {
    setupReportListeners();
    applyRangePreset('30d', { fetchAfter: true });
});

function setupReportListeners() {
    document.querySelectorAll('.range-preset').forEach(button => {
        button.addEventListener('click', function() {
            applyRangePreset(this.dataset.range, { fetchAfter: true });
        });
    });

    ['reportStartDate', 'reportEndDate'].forEach(id => {
        document.getElementById(id).addEventListener('change', function() {
            selectedRange = '';
            exactStartAt = '';
            exactEndAt = '';
            updateRangePresetState();
            fetchReports();
        });
    });

    ['quietStart', 'quietEnd', 'clusterGap', 'includeFalsePos'].forEach(id => {
        document.getElementById(id).addEventListener('change', fetchReports);
    });

    document.getElementById('refreshReportsBtn').addEventListener('click', fetchReports);
}

function applyRangePreset(range, options = {}) {
    selectedRange = range;
    const now = new Date();
    let start = new Date(now);
    let end = new Date(now);

    if (range === '24h') {
        start = addHours(now, -24);
    } else if (range === '7d') {
        start = addDays(now, -7);
    } else if (range === '30d') {
        start = addDays(now, -30);
    } else if (range === '90d') {
        start = addDays(now, -90);
    } else if (range === '6mo') {
        start = addMonths(now, -6);
    } else if (range === '1y') {
        start = addYears(now, -1);
    } else if (range === 'last-year') {
        const lastYear = now.getFullYear() - 1;
        start = new Date(lastYear, 0, 1, 0, 0, 0);
        end = new Date(lastYear, 11, 31, 23, 59, 59);
    }

    exactStartAt = formatLocalDateTime(start);
    exactEndAt = formatLocalDateTime(end);
    document.getElementById('reportStartDate').value = formatDateInput(start);
    document.getElementById('reportEndDate').value = formatDateInput(end);
    updateRangePresetState();

    if (options.fetchAfter) {
        fetchReports();
    }
}

function updateRangePresetState() {
    document.querySelectorAll('.range-preset').forEach(button => {
        button.classList.toggle('active', button.dataset.range === selectedRange);
    });
}

function fetchReports() {
    const params = new URLSearchParams();
    if (exactStartAt && exactEndAt) {
        params.set('start_at', exactStartAt);
        params.set('end_at', exactEndAt);
    } else {
        const startDate = document.getElementById('reportStartDate').value;
        const endDate = document.getElementById('reportEndDate').value;
        if (!startDate || !endDate) {
            setReportState('Select a range');
            return;
        }
        params.set('start_date', startDate);
        params.set('end_date', endDate);
    }

    params.set('include_false_pos', String(document.getElementById('includeFalsePos').checked));
    params.set('quiet_start', document.getElementById('quietStart').value || '22:00');
    params.set('quiet_end', document.getElementById('quietEnd').value || '07:00');
    params.set('cluster_gap_minutes', document.getElementById('clusterGap').value || '10');

    setReportState('Loading');
    fetch(`/api/reports/analytics?${params.toString()}`)
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            renderReports(data);
            setReportState(data.range && data.range.truncated ? 'Limited' : 'Ready');
        })
        .catch(error => {
            console.error('Error loading reports:', error);
            setReportState('Error');
            renderReportError();
        });
}

function renderReports(data) {
    renderReportMeta(data);
    renderKpis(data.kpis || {});
    renderDailyTrend(data.daily || []);
    renderHeatmap(data.heatmap || []);
    renderHourlyBars(data.hourly || []);
    renderDurationBuckets(data.duration_buckets || []);
    renderQuietHours(data.quiet_hours || {});
    renderQuality(data.kpis || {}, data.range || {});
    renderCategoryBars('directionBars', 'directionMeta', data.direction_summary || [], 'No direction data');
    renderCategoryBars('weatherBars', 'weatherMeta', data.weather_summary || [], 'No weather data');
    renderClusters(data.clusters || [], data.range || {});
    renderLongestIncidents(data.longest_incidents || []);
}

function renderReportMeta(data) {
    const range = data.range || {};
    const start = range.start ? formatDateTime(range.start) : '-';
    const end = range.end ? formatDateTime(range.end) : '-';
    const elapsed = range.elapsed_sec ? formatDuration(range.elapsed_sec) : '0s';
    const included = range.selected_event_count ?? (data.kpis ? data.kpis.incident_count : 0);
    document.getElementById('reportRangeLabel').textContent = `${start} - ${end} (${elapsed})`;
    document.getElementById('reportState').textContent = range.truncated
        ? `${included.toLocaleString()} included, limited to ${range.max_events.toLocaleString()}`
        : `${Number(included || 0).toLocaleString()} included`;
}

function renderKpis(kpis) {
    document.getElementById('kpiIncidents').textContent = Number(kpis.incident_count || 0).toLocaleString();
    document.getElementById('kpiDuration').textContent = formatDuration(kpis.total_duration_sec || 0);
    document.getElementById('kpiShare').textContent = formatPercentValue(kpis.duration_percent_elapsed || 0);
    document.getElementById('kpiRate').textContent = `${formatNumber(kpis.incident_rate_per_hour || 0)}/hr`;
    document.getElementById('kpiAverage').textContent = formatDuration(kpis.avg_duration_sec || 0);
    document.getElementById('kpiMedian').textContent = formatDuration(kpis.median_duration_sec || 0);
    document.getElementById('kpiP90').textContent = formatDuration(kpis.p90_duration_sec || 0);
    document.getElementById('kpiLongest').textContent = formatDuration(kpis.longest_duration_sec || 0);
}

function renderDailyTrend(days) {
    const container = document.getElementById('dailyTrendChart');
    const totalIncidents = days.reduce((sum, day) => sum + Number(day.incident_count || 0), 0);
    document.getElementById('dailyTrendMeta').textContent = `${totalIncidents.toLocaleString()} incidents`;
    if (!days.length) {
        container.innerHTML = '<div class="report-empty">No days in range.</div>';
        return;
    }

    const maxValue = Math.max(...days.map(day => Math.max(Number(day.duration_sec || 0), Number(day.incident_count || 0))), 1);
    container.innerHTML = days.map(day => {
        const duration = Number(day.duration_sec || 0);
        const count = Number(day.incident_count || 0);
        const width = Math.max(2, (Math.max(duration, count) / maxValue) * 100);
        const label = `${count} ${count === 1 ? 'incident' : 'incidents'} / ${formatDuration(duration)}`;
        return `
            <div class="trend-row" title="${escapeHtml(label)}">
                <span class="trend-date">${escapeHtml(formatDateOnly(day.date))}</span>
                <span class="trend-track"><span class="trend-fill" style="width: ${width}%"></span></span>
                <strong>${count.toLocaleString()}</strong>
                <span>${escapeHtml(formatDuration(duration))}</span>
            </div>
        `;
    }).join('');
}

function renderHeatmap(cells) {
    const hoursContainer = document.getElementById('heatmapHours');
    const grid = document.getElementById('hourHeatmap');
    hoursContainer.innerHTML = '<span></span>' + Array.from({ length: 24 }, (_, hour) => {
        const label = hour % 6 === 0 ? String(hour).padStart(2, '0') : '';
        return `<span>${label}</span>`;
    }).join('');

    if (!cells.length) {
        grid.innerHTML = '<div class="report-empty">No heatmap data.</div>';
        return;
    }

    const byDate = new Map();
    cells.forEach(cell => {
        if (!byDate.has(cell.date)) {
            byDate.set(cell.date, []);
        }
        byDate.get(cell.date).push(cell);
    });
    const maxCount = Math.max(...cells.map(cell => Number(cell.incident_count || 0)), 1);

    grid.innerHTML = Array.from(byDate.entries()).map(([date, rowCells]) => {
        const byHour = new Map(rowCells.map(cell => [Number(cell.hour), cell]));
        const hourCells = Array.from({ length: 24 }, (_, hour) => {
            const cell = byHour.get(hour) || { incident_count: 0, duration_sec: 0 };
            const count = Number(cell.incident_count || 0);
            const intensity = count === 0 ? 0 : Math.max(0.16, count / maxCount);
            const title = `${formatDateOnly(date)} ${String(hour).padStart(2, '0')}:00 - ${count} incidents, ${formatDuration(cell.duration_sec || 0)}`;
            return `<span class="heatmap-cell" style="--heat: ${intensity}" title="${escapeHtml(title)}"></span>`;
        }).join('');
        return `<div class="heatmap-row"><span class="heatmap-date">${escapeHtml(formatDateOnly(date))}</span>${hourCells}</div>`;
    }).join('');
}

function renderHourlyBars(hours) {
    const container = document.getElementById('hourlyBars');
    if (!hours.length) {
        container.innerHTML = '<div class="report-empty">No hourly data.</div>';
        return;
    }

    const peak = hours.reduce((best, row) => {
        if (Number(row.incident_count || 0) > Number(best.incident_count || 0)) {
            return row;
        }
        return best;
    }, hours[0] || {});
    document.getElementById('hourlyMeta').textContent =
        `${formatHour(peak.hour || 0)} peak`;

    const maxValue = Math.max(...hours.map(row => Number(row.incident_count || 0)), 1);
    container.innerHTML = hours.map(row => renderBarRow(
        formatHour(row.hour),
        Number(row.incident_count || 0),
        maxValue,
        formatDuration(row.duration_sec || 0)
    )).join('');
}

function renderDurationBuckets(buckets) {
    const container = document.getElementById('durationBuckets');
    const total = buckets.reduce((sum, row) => sum + Number(row.incident_count || 0), 0);
    document.getElementById('durationMeta').textContent = `${total.toLocaleString()} incidents`;
    if (!buckets.length) {
        container.innerHTML = '<div class="report-empty">No duration data.</div>';
        return;
    }
    const maxValue = Math.max(...buckets.map(row => Number(row.incident_count || 0)), 1);
    container.innerHTML = buckets.map(row => renderBarRow(
        row.label,
        Number(row.incident_count || 0),
        maxValue,
        formatDuration(row.duration_sec || 0)
    )).join('');
}

function renderQuietHours(quiet) {
    const container = document.getElementById('quietMetrics');
    const start = quiet.start || '22:00';
    const end = quiet.end || '07:00';
    document.getElementById('quietWindowLabel').textContent = `${start}-${end}`;
    container.innerHTML = renderMetricRows([
        ['Incidents', Number(quiet.incident_count || 0).toLocaleString()],
        ['Incident time', formatDuration(quiet.duration_sec || 0)],
        ['Longest', formatDuration(quiet.longest_duration_sec || 0)],
        ['Incident share', formatPercentValue(quiet.incident_percent || 0)],
        ['Time share', formatPercentValue(quiet.duration_percent || 0)],
    ]);
}

function renderQuality(kpis, range) {
    const container = document.getElementById('qualityMetrics');
    const reviewed = Number(kpis.total_event_count || 0);
    const included = Number(kpis.incident_count || 0);
    const falsePos = Number(kpis.false_positive_count || 0);
    const clips = Number(kpis.recorded_clip_count || 0);
    const missing = Number(kpis.missing_clip_count || 0);
    document.getElementById('qualityMeta').textContent = `${reviewed.toLocaleString()} reviewed`;
    container.innerHTML = renderMetricRows([
        ['Records reviewed', reviewed.toLocaleString()],
        ['Included', included.toLocaleString()],
        [range.include_false_pos ? 'False positives included' : 'False positives filtered', falsePos.toLocaleString()],
        ['Clips available', clips.toLocaleString()],
        ['Missing clips', missing.toLocaleString()],
        ['Near threshold', Number(kpis.near_threshold_count || 0).toLocaleString()],
    ]);
}

function renderCategoryBars(containerId, metaId, rows, emptyText) {
    const container = document.getElementById(containerId);
    const meta = document.getElementById(metaId);
    if (!rows.length) {
        meta.textContent = emptyText;
        container.innerHTML = `<div class="report-empty">${escapeHtml(emptyText)}.</div>`;
        return;
    }

    const maxValue = Math.max(...rows.map(row => Number(row.incident_count || 0)), 1);
    meta.textContent = `${rows[0].label || 'Unknown'} top`;
    container.innerHTML = rows.slice(0, 8).map(row => renderBarRow(
        row.label || 'Unknown',
        Number(row.incident_count || 0),
        maxValue,
        formatDuration(row.duration_sec || 0)
    )).join('');
}

function renderClusters(clusters, range) {
    const tbody = document.getElementById('clusterTableBody');
    const gap = document.getElementById('clusterGap').value || '10';
    document.getElementById('clusterMeta').textContent = `${gap} minute gap`;
    if (!clusters.length) {
        tbody.innerHTML = '<tr class="loading-row"><td colspan="5">No repeat clusters in this range.</td></tr>';
        return;
    }

    tbody.innerHTML = clusters.map(cluster => `
        <tr>
            <td data-label="Started">${escapeHtml(formatDateTime(cluster.started_at))}</td>
            <td data-label="Span">${escapeHtml(formatDuration(cluster.span_sec || 0))}</td>
            <td data-label="Incidents">${Number(cluster.incident_count || 0).toLocaleString()}</td>
            <td data-label="Incident Time">${escapeHtml(formatDuration(cluster.duration_sec || 0))}</td>
            <td data-label="Max Gap">${escapeHtml(formatDuration(cluster.max_gap_sec || 0))}</td>
        </tr>
    `).join('');
}

function renderLongestIncidents(incidents) {
    const tbody = document.getElementById('longestTableBody');
    document.getElementById('longestMeta').textContent = `${incidents.length} shown`;
    if (!incidents.length) {
        tbody.innerHTML = '<tr class="loading-row"><td colspan="6">No incidents in this range.</td></tr>';
        return;
    }

    tbody.innerHTML = incidents.map(incident => `
        <tr>
            <td data-label="Date / Time">${escapeHtml(formatDateTime(incident.started_at))}</td>
            <td data-label="Duration">${escapeHtml(formatDuration(incident.duration_sec || 0))}</td>
            <td data-label="Score">${escapeHtml(formatScore(incident.peak_score))}</td>
            <td data-label="Direction">${escapeHtml(incident.direction || '-')}</td>
            <td data-label="Weather">${escapeHtml(formatWeather(incident))}</td>
            <td data-label="Link">${incident.id ? `<a class="btn btn-action" href="/events/${incident.id}">Details</a>` : '-'}</td>
        </tr>
    `).join('');
}

function renderReportError() {
    document.getElementById('dailyTrendChart').innerHTML = '<div class="report-empty">Unable to load reports.</div>';
    document.getElementById('hourHeatmap').innerHTML = '<div class="report-empty">Unable to load reports.</div>';
    document.getElementById('hourlyBars').innerHTML = '';
    document.getElementById('durationBuckets').innerHTML = '';
    document.getElementById('quietMetrics').innerHTML = '';
    document.getElementById('qualityMetrics').innerHTML = '';
    document.getElementById('directionBars').innerHTML = '';
    document.getElementById('weatherBars').innerHTML = '';
    document.getElementById('clusterTableBody').innerHTML = '<tr class="loading-row"><td colspan="5">Unable to load reports.</td></tr>';
    document.getElementById('longestTableBody').innerHTML = '<tr class="loading-row"><td colspan="6">Unable to load reports.</td></tr>';
}

function renderBarRow(label, value, maxValue, subtext) {
    const width = Math.max(2, (Number(value || 0) / Math.max(1, Number(maxValue || 1))) * 100);
    return `
        <div class="bar-row">
            <span class="bar-label">${escapeHtml(label)}</span>
            <span class="bar-track"><span class="bar-fill" style="width: ${width}%"></span></span>
            <strong>${Number(value || 0).toLocaleString()}</strong>
            <span class="bar-subtext">${escapeHtml(subtext)}</span>
        </div>
    `;
}

function renderMetricRows(rows) {
    return rows.map(([label, value]) => `
        <div class="metric-row">
            <span>${escapeHtml(label)}</span>
            <strong>${escapeHtml(value)}</strong>
        </div>
    `).join('');
}

function setReportState(label) {
    document.getElementById('reportState').textContent = label;
}

function addHours(date, hours) {
    const result = new Date(date);
    result.setHours(result.getHours() + hours);
    return result;
}

function addDays(date, days) {
    const result = new Date(date);
    result.setDate(result.getDate() + days);
    return result;
}

function addMonths(date, months) {
    const result = new Date(date.getFullYear(), date.getMonth(), 1, date.getHours(), date.getMinutes(), date.getSeconds());
    result.setMonth(result.getMonth() + months);
    const lastDay = new Date(result.getFullYear(), result.getMonth() + 1, 0).getDate();
    result.setDate(Math.min(date.getDate(), lastDay));
    return result;
}

function addYears(date, years) {
    const result = new Date(date.getFullYear() + years, date.getMonth(), 1, date.getHours(), date.getMinutes(), date.getSeconds());
    const lastDay = new Date(result.getFullYear(), result.getMonth() + 1, 0).getDate();
    result.setDate(Math.min(date.getDate(), lastDay));
    return result;
}

function formatLocalDateTime(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const hour = String(date.getHours()).padStart(2, '0');
    const minute = String(date.getMinutes()).padStart(2, '0');
    const second = String(date.getSeconds()).padStart(2, '0');
    return `${year}-${month}-${day}T${hour}:${minute}:${second}`;
}

function formatDateInput(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

function formatDateTime(value) {
    if (!value) {
        return '-';
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return '-';
    }
    return date.toLocaleString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
    });
}

function formatDateOnly(value) {
    const date = new Date(`${value}T00:00:00`);
    if (Number.isNaN(date.getTime())) {
        return value || '-';
    }
    return date.toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
    });
}

function formatHour(hour) {
    const numeric = Number(hour || 0);
    return `${String(numeric).padStart(2, '0')}:00`;
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

function formatPercentValue(value) {
    return `${Number(value || 0).toFixed(1)}%`;
}

function formatScore(value) {
    if (value === null || value === undefined) {
        return '-';
    }
    return `${(Number(value) * 100).toFixed(1)}%`;
}

function formatNumber(value) {
    const number = Number(value || 0);
    if (Math.abs(number) >= 10) {
        return number.toFixed(1);
    }
    return number.toFixed(2);
}

function formatWeather(incident) {
    const parts = [];
    if (incident.weather_conditions) {
        parts.push(incident.weather_conditions);
    }
    if (incident.weather_temp_f !== null && incident.weather_temp_f !== undefined) {
        parts.push(`${Math.round(Number(incident.weather_temp_f))}F`);
    }
    if (incident.weather_wind_mph !== null && incident.weather_wind_mph !== undefined) {
        parts.push(`${Math.round(Number(incident.weather_wind_mph))} mph`);
    }
    return parts.length ? parts.join(' / ') : '-';
}

function escapeHtml(value) {
    return String(value)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');
}
