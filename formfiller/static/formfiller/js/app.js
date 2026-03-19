// Global state
let formData = null;
let currentJobId = null;
let eventSource = null;

// ============ PARSE ============

async function parseForm() {
    const url = document.getElementById('formUrl').value.trim();
    if (!url) {
        showAlert('Please enter a Google Form URL.', 'warning');
        return;
    }
    if (!url.includes('docs.google.com/forms')) {
        showAlert('Please enter a valid Google Forms URL.', 'warning');
        return;
    }

    const btn = document.getElementById('btnParse');
    const spinner = document.getElementById('parseSpinner');
    btn.disabled = true;
    spinner.classList.remove('d-none');
    hideAlert();

    try {
        const resp = await fetch('/api/parse/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url })
        });
        const data = await resp.json();

        if (data.success) {
            formData = data.form;
            renderFormInfo(data.form);
            renderFields(data.form.fields);
            document.getElementById('formSection').classList.remove('d-none');
        } else {
            showAlert(data.error || 'Failed to parse form.', 'danger');
        }
    } catch (err) {
        showAlert('Network error: ' + err.message, 'danger');
    } finally {
        btn.disabled = false;
        spinner.classList.add('d-none');
    }
}

function renderFormInfo(form) {
    document.getElementById('formTitle').textContent = form.title || 'Untitled Form';
    document.getElementById('formDescription').textContent = form.description || '';

    const signinWarning = document.getElementById('signinWarning');
    const btnStart = document.getElementById('btnStart');
    if (form.requires_signin) {
        signinWarning.classList.remove('d-none');
        btnStart.disabled = true;
    } else {
        signinWarning.classList.add('d-none');
        btnStart.disabled = false;
    }
}

function renderFields(fields) {
    const container = document.getElementById('fieldsContainer');
    container.innerHTML = '';

    fields.forEach((field, idx) => {
        const isChoice = ['radio', 'checkbox', 'dropdown'].includes(field.field_type);
        const isScale = field.field_type === 'linear_scale';
        const isFileUpload = field.field_type === 'file_upload';
        const requiredClass = field.required ? 'required' : '';

        let optionsHtml = '';
        if (isChoice && field.options && field.options.length > 0) {
            optionsHtml = `<div class="options-preview mt-1">
                Options: ${field.options.map(o => `<span class="badge bg-secondary">${escapeHtml(o)}</span>`).join(' ')}
                ${field.other_option ? '<span class="badge bg-info">Other</span>' : ''}
            </div>`;
        }
        if (isScale) {
            const low = field.scale_min || 1;
            const high = field.scale_max || 5;
            optionsHtml = `<div class="options-preview mt-1">Scale: ${low} — ${high}</div>`;
        }

        const isEmail = field._is_email || false;

        let strategyHtml = '';
        if (isFileUpload) {
            strategyHtml = `<div class="alert alert-secondary py-1 px-2 mb-0 mt-2">
                <small><i class="bi bi-info-circle"></i> File upload is not supported.</small>
            </div>`;
        } else {
            const defaultStrat = isEmail ? 'template' : 'random';
            const strategies = isChoice || isScale
                ? `<option value="random" selected>Random from options</option>
                   <option value="fixed">Fixed value</option>`
                : `<option value="random" ${defaultStrat === 'random' ? 'selected' : ''}>Random (auto-detect)</option>
                   <option value="fixed">Fixed value</option>
                   <option value="from_list">From list</option>
                   <option value="template" ${defaultStrat === 'template' ? 'selected' : ''}>Template pattern</option>`;

            strategyHtml = `
            <div class="strategy-config">
                <div class="row align-items-center">
                    <div class="col-auto">
                        <label class="form-label mb-0 small fw-semibold">Fill strategy:</label>
                    </div>
                    <div class="col">
                        <select class="form-select form-select-sm" id="strategy_${field.entry_id}"
                                onchange="onStrategyChange('${field.entry_id}', this.value)">
                            ${strategies}
                        </select>
                    </div>
                </div>
                <div id="strategyExtra_${field.entry_id}" class="${isEmail ? 'mt-2' : 'mt-2 d-none'}">
                    ${isEmail ? `<input type="text" class="form-control form-control-sm mb-2"
                           id="templateValue_${field.entry_id}"
                           value="{chinese_surname}{initials}-{choice:wm23,wm24,wp22,wp21}@student.tarc.edu.my">
                    <div class="form-text small" style="line-height:1.6">
                        <strong>Placeholders:</strong>
                        <code>{chinese_surname}</code> <code>{initials}</code> <code>{choice:a,b,c}</code>
                        <code>{number:1-99}</code> <code>{digit}</code> <code>{digits:N}</code>
                        <code>{letter}</code> <code>{letters:N}</code>
                        <code>{first_name}</code> <code>{last_name}</code> <code>{name}</code> <code>{email}</code>
                    </div>` : ''}
                </div>
            </div>`;
        }

        const typeColors = {
            short_text: 'primary', paragraph: 'primary',
            radio: 'success', checkbox: 'warning', dropdown: 'info',
            linear_scale: 'secondary', date: 'dark', time: 'dark',
            grid_radio: 'success', grid_checkbox: 'warning', file_upload: 'danger'
        };
        const badgeColor = typeColors[field.field_type] || 'secondary';

        const card = document.createElement('div');
        card.className = `card shadow-sm mb-2 field-card ${requiredClass}`;
        card.innerHTML = `
            <div class="card-body py-3">
                <div class="d-flex align-items-start justify-content-between">
                    <div class="flex-grow-1">
                        <h6 class="mb-1">
                            ${escapeHtml(field.label)}
                            ${field.required ? '<span class="text-danger">*</span>' : ''}
                        </h6>
                        <span class="badge bg-${badgeColor} field-type-badge">${field.field_type.replace('_', ' ')}</span>
                        ${optionsHtml}
                    </div>
                </div>
                ${strategyHtml}
            </div>`;
        container.appendChild(card);
    });
}

function onStrategyChange(entryId, strategy) {
    const extra = document.getElementById(`strategyExtra_${entryId}`);
    if (strategy === 'fixed') {
        extra.classList.remove('d-none');
        extra.innerHTML = `<input type="text" class="form-control form-control-sm"
                           id="fixedValue_${entryId}" placeholder="Enter fixed value">`;
    } else if (strategy === 'from_list') {
        extra.classList.remove('d-none');
        extra.innerHTML = `<textarea class="form-control form-control-sm" rows="3"
                           id="listValue_${entryId}" placeholder="One value per line"></textarea>`;
    } else if (strategy === 'template') {
        extra.classList.remove('d-none');
        extra.innerHTML = `
            <input type="text" class="form-control form-control-sm mb-2"
                   id="templateValue_${entryId}"
                   placeholder="{chinese_surname}{initials}-{choice:wm23,wm24,wp22}@student.tarc.edu.my">
            <div class="form-text small" style="line-height:1.6">
                <strong>Placeholders:</strong><br>
                <code>{chinese_surname}</code> tan, lim, chen...<br>
                <code>{initials}</code> ch, ws, yk... (2-letter)<br>
                <code>{choice:a,b,c}</code> random pick<br>
                <code>{number:1-99}</code> random number in range<br>
                <code>{first_name}</code> / <code>{last_name}</code> English names<br>
                <code>{letter}</code> single letter &nbsp; <code>{letters:3}</code> N letters<br>
                <code>{digit}</code> single digit &nbsp; <code>{digits:4}</code> N digits<br>
                <code>{email}</code> random email &nbsp; <code>{name}</code> full name
            </div>`;
    } else {
        extra.classList.add('d-none');
        extra.innerHTML = '';
    }
}

// ============ SUBMIT ============

async function startSubmission() {
    if (!formData) return;

    const count = parseInt(document.getElementById('submitCount').value) || 1;
    const delay = parseInt(document.getElementById('submitDelay').value) || 1000;
    const useBrowser = document.getElementById('useBrowser').checked;
    const proxyText = document.getElementById('proxyInput').value.trim();
    const proxies = proxyText ? proxyText.split('\n').map(p => p.trim()).filter(Boolean) : [];

    // Collect strategies
    const strategies = {};
    formData.fields.forEach(field => {
        if (field.field_type === 'file_upload') return;
        const sel = document.getElementById(`strategy_${field.entry_id}`);
        if (!sel) return;
        const strat = { strategy: sel.value };
        if (sel.value === 'fixed') {
            const inp = document.getElementById(`fixedValue_${field.entry_id}`);
            strat.fixed_value = inp ? inp.value : '';
        } else if (sel.value === 'from_list') {
            const ta = document.getElementById(`listValue_${field.entry_id}`);
            strat.value_list = ta ? ta.value.split('\n').filter(Boolean) : [];
        } else if (sel.value === 'template') {
            const inp = document.getElementById(`templateValue_${field.entry_id}`);
            strat.template = inp ? inp.value : '';
        }
        strategies[field.entry_id] = strat;
    });

    const payload = {
        form_url: formData.form_url || document.getElementById('formUrl').value.trim(),
        form_id: formData.form_id,
        submit_url: formData.submit_url,
        fields: formData.fields,
        hidden_fields: formData.hidden_fields || {},
        strategies,
        count,
        delay_ms: delay,
        use_playwright: useBrowser,
        proxies
    };

    try {
        const resp = await fetch('/api/submit/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await resp.json();
        if (data.success) {
            currentJobId = data.job_id;
            showProgress(count);
            connectSSE(data.job_id);
        } else {
            showAlert(data.error || 'Failed to start submission.', 'danger');
        }
    } catch (err) {
        showAlert('Network error: ' + err.message, 'danger');
    }
}

function showProgress(total) {
    document.getElementById('progressSection').classList.remove('d-none');
    document.getElementById('btnStart').classList.add('d-none');
    document.getElementById('btnStop').classList.remove('d-none');
    document.getElementById('totalCount').textContent = total;
    document.getElementById('completedCount').textContent = '0';
    document.getElementById('failedCount').textContent = '0';
    document.getElementById('progressBar').style.width = '0%';
    document.getElementById('progressBar').textContent = '0%';
    document.getElementById('logArea').innerHTML = '';
    appendLog('Submission started...', 'info');
}

function connectSSE(jobId) {
    if (eventSource) eventSource.close();
    eventSource = new EventSource(`/api/stream/${jobId}/`);

    eventSource.onmessage = function (event) {
        const data = JSON.parse(event.data);

        if (data.type === 'progress') {
            updateProgress(data);
        } else if (data.type === 'error') {
            appendLog(`#${data.index || '?'} Error: ${data.message}`, 'error');
        } else if (data.type === 'success') {
            appendLog(`#${data.index} Submitted successfully`, 'success');
        } else if (data.type === 'complete' || data.type === 'stopped') {
            onJobDone(data);
        }
    };

    eventSource.onerror = function () {
        // Only show "Connection lost" if the job wasn't already finished
        if (currentJobId) {
            appendLog('Connection lost. The job may still be running on the server.', 'error');
            // Reset buttons so user can start a new job
            document.getElementById('btnStart').classList.remove('d-none');
            document.getElementById('btnStop').classList.add('d-none');
            currentJobId = null;
        }
        eventSource.close();
        eventSource = null;
    };
}

function updateProgress(data) {
    const completed = data.completed || 0;
    const failed = data.failed || 0;
    const total = data.total || 1;
    const pct = Math.round(((completed + failed) / total) * 100);

    document.getElementById('completedCount').textContent = completed;
    document.getElementById('failedCount').textContent = failed;
    document.getElementById('progressBar').style.width = pct + '%';
    document.getElementById('progressBar').textContent = pct + '%';
}

function onJobDone(data) {
    if (eventSource) { eventSource.close(); eventSource = null; }
    document.getElementById('btnStart').classList.remove('d-none');
    document.getElementById('btnStop').classList.add('d-none');

    const bar = document.getElementById('progressBar');
    bar.classList.remove('progress-bar-animated');
    bar.style.width = '100%';
    bar.textContent = '100%';

    const msg = data.type === 'stopped' ? 'Submission stopped by user.' : 'All submissions complete.';
    appendLog(msg, 'info');
    currentJobId = null;
}

async function stopSubmission() {
    if (!currentJobId) return;
    try {
        await fetch(`/api/stop/${currentJobId}/`, { method: 'POST' });
        appendLog('Stopping...', 'info');
    } catch (err) {
        appendLog('Failed to stop: ' + err.message, 'error');
    }
}

// ============ UTILS ============

function showAlert(msg, type) {
    const area = document.getElementById('alertArea');
    area.className = `alert alert-${type}`;
    area.innerHTML = `<i class="bi bi-exclamation-circle"></i> ${escapeHtml(msg)}`;
    area.classList.remove('d-none');
}

function hideAlert() {
    document.getElementById('alertArea').className = 'd-none';
}

function appendLog(msg, type) {
    const log = document.getElementById('logArea');
    const entry = document.createElement('div');
    entry.className = `log-entry log-${type || 'info'}`;
    const ts = new Date().toLocaleTimeString();
    entry.textContent = `[${ts}] ${msg}`;
    log.appendChild(entry);
    log.scrollTop = log.scrollHeight;
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}
