let followTimer = null;
let followEnabled = false;

document.addEventListener('DOMContentLoaded', function() {
    document.getElementById('logRefreshBtn').addEventListener('click', loadLogs);
    document.getElementById('logFollowBtn').addEventListener('click', toggleFollow);
    document.getElementById('logCopyBtn').addEventListener('click', copyLogs);
    document.getElementById('logService').addEventListener('change', loadLogs);
    document.getElementById('logLines').addEventListener('change', loadLogs);
    loadLogs();
});

function loadLogs() {
    const service = document.getElementById('logService').value;
    const lines = document.getElementById('logLines').value;
    const state = document.getElementById('logState');

    state.textContent = 'Loading';
    fetch(`/api/logs?service=${encodeURIComponent(service)}&lines=${encodeURIComponent(lines)}`)
        .then(response => response.json())
        .then(renderLogs)
        .catch(error => {
            console.error('Error loading logs:', error);
            state.textContent = 'Error';
            document.getElementById('logOutput').textContent = 'Could not load logs.';
        });
}

function toggleFollow() {
    followEnabled = !followEnabled;
    const button = document.getElementById('logFollowBtn');
    button.textContent = followEnabled ? 'Following' : 'Follow';
    button.classList.toggle('active', followEnabled);
    button.setAttribute('aria-pressed', String(followEnabled));

    if (followTimer) {
        clearInterval(followTimer);
        followTimer = null;
    }
    if (followEnabled) {
        loadLogs();
        followTimer = setInterval(loadLogs, 3000);
    }
}

function copyLogs() {
    const output = document.getElementById('logOutput');
    const button = document.getElementById('logCopyBtn');
    const text = output.textContent || '';

    copyText(text)
        .then(() => setCopyButtonState(button, 'Copied'))
        .catch(error => {
            console.error('Error copying logs:', error);
            setCopyButtonState(button, 'Copy failed');
        });
}

function renderLogs(data) {
    const state = document.getElementById('logState');
    const generated = document.getElementById('logGenerated');
    const output = document.getElementById('logOutput');
    const generatedAt = data.generated_at ? new Date(data.generated_at) : null;
    const generatedText = generatedAt && !Number.isNaN(generatedAt.getTime())
        ? generatedAt.toLocaleString()
        : 'Unknown time';

    state.textContent = data.success ? `${data.label} logs` : 'Log error';
    generated.textContent = `${data.unit || 'unknown'} / ${generatedText}`;

    const lines = data.lines || [];
    const text = lines.length ? lines.join('\n') : (data.error || 'No log lines returned.');
    output.textContent = data.error ? `${data.error}\n\n${text}` : text;
    output.classList.toggle('logs-output-error', !data.success);

    if (followEnabled) {
        output.scrollTop = output.scrollHeight;
    }
}

function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
        return navigator.clipboard.writeText(text);
    }

    return new Promise((resolve, reject) => {
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.setAttribute('readonly', '');
        textarea.style.position = 'fixed';
        textarea.style.left = '-9999px';
        document.body.appendChild(textarea);
        textarea.select();
        try {
            document.execCommand('copy') ? resolve() : reject(new Error('copy command failed'));
        } catch (error) {
            reject(error);
        } finally {
            document.body.removeChild(textarea);
        }
    });
}

function setCopyButtonState(button, label) {
    const original = 'Copy';
    button.textContent = label;
    button.disabled = label === 'Copied';
    setTimeout(() => {
        button.textContent = original;
        button.disabled = false;
    }, 1200);
}
