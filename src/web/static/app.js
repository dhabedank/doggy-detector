// State
let currentPage = 1;
let totalPages = 1;
let eventsPerPage = 20;

// Filter state
let dateFilter = '';
let falsePositiveFilter = '';

// Modal state
let reportModal = null;

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    initializeElements();
    setupEventListeners();
    fetchEvents();

    // Set today's date as default for report modal
    const today = new Date().toISOString().split('T')[0];
    document.getElementById('endDate').value = today;
    document.getElementById('startDate').value = today;
});

// Initialize DOM elements
function initializeElements() {
    reportModal = document.getElementById('reportModal');
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

    const reportUrl = `/api/report?start_date=${startDate}&end_date=${endDate}`;
    window.location.href = reportUrl;

    // Close modal after initiating download
    setTimeout(hideReportModal, 500);
}
