// Global state
let formData = null;
let currentJobId = null;
let eventSource = null;

// ============ PARSE ============

async function parseGenericForm() {
    const url = document.getElementById('formUrl').value.trim();
    if (!url) {
        showAlert('Please enter a URL.', 'warning');
        return;
    }

    const btn = document.getElementById('btnParse');
    const spinner = document.getElementById('parseSpinner');
    btn.disabled = true;
    spinner.classList.remove('d-none');
    hideAlert();

    try {
        const resp = await fetch('/api/generic/parse/', {
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
            showAlert(data.error || 'Failed to parse page.', 'danger');
        }
    } catch (err) {
        showAlert('Network error: ' + err.message, 'danger');
    } finally {
        btn.disabled = false;
        spinner.classList.add('d-none');
    }
}

function renderFormInfo(form) {
    document.getElementById('formTitle').textContent = form.page_title || 'Untitled Page';
    document.getElementById('formDescription').textContent =
        form.form_selector ? `Form detected: ${form.form_selector}` : 'No <form> element found — scanning entire page.';

    const loginWarning = document.getElementById('loginWarning');
    const noFieldsWarning = document.getElementById('noFieldsWarning');
    const btnStart = document.getElementById('btnStart');

    if (form.has_login) {
        loginWarning.classList.remove('d-none');
    } else {
        loginWarning.classList.add('d-none');
    }

    if (!form.fields || form.fields.length === 0) {
        noFieldsWarning.classList.remove('d-none');
        btnStart.disabled = true;
    } else {
        noFieldsWarning.classList.add('d-none');
        btnStart.disabled = false;
    }
}

function renderFields(fields) {
    const container = document.getElementById('fieldsContainer');
    container.innerHTML = '';

    fields.forEach((field, idx) => {
        const isChoice = ['radio', 'checkbox', 'dropdown'].includes(field.field_type);
        const requiredClass = field.required ? 'required' : '';

        let optionsHtml = '';
        if (isChoice && field.options && field.options.length > 0) {
            optionsHtml = `<div class="options-preview mt-1">
                Options: ${field.options.map(o => `<span class="badge bg-secondary">${escapeHtml(o)}</span>`).join(' ')}
            </div>`;
        }

        // Show field metadata
        let metaHtml = '<div class="mt-1 small text-muted">';
        if (field.name) metaHtml += `name="${escapeHtml(field.name)}" `;
        if (field.input_type) metaHtml += `type="${escapeHtml(field.input_type)}" `;
        if (field.selector) metaHtml += `<code>${escapeHtml(field.selector)}</code>`;
        metaHtml += '</div>';

        // Detect email fields
        const isEmail = field.input_type === 'email' ||
            (field.label && /email|e-mail|emel/i.test(field.label)) ||
            (field.name && /email/i.test(field.name));

        let strategyHtml = '';
        const defaultStrat = isEmail ? 'template' : 'random';
        const strategies = isChoice
            ? `<option value="random" selected>Random from options</option>
               <option value="pick_options">Pick specific options</option>
               <option value="fixed">Fixed value (type exactly)</option>`
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
                    <select class="form-select form-select-sm" id="strategy_${field.field_id}"
                            onchange="onStrategyChange('${field.field_id}', this.value)">
                        ${strategies}
                    </select>
                </div>
            </div>
            <div id="strategyExtra_${field.field_id}" class="${isEmail ? 'mt-2' : 'mt-2 d-none'}">
                ${isEmail ? `<input type="text" class="form-control form-control-sm mb-2"
                       id="templateValue_${field.field_id}"
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

        const typeColors = {
            short_text: 'primary', paragraph: 'primary',
            radio: 'success', checkbox: 'warning', dropdown: 'info',
            date: 'dark', time: 'dark'
        };
        const badgeColor = typeColors[field.field_type] || 'secondary';

        const card = document.createElement('div');
        card.className = `card shadow-sm mb-2 field-card ${requiredClass}`;
        card.innerHTML = `
            <div class="card-body py-3">
                <div class="d-flex align-items-start justify-content-between">
                    <div class="flex-grow-1">
                        <h6 class="mb-1">
                            ${escapeHtml(field.label || '(unlabeled)')}
                            ${field.required ? '<span class="text-danger">*</span>' : ''}
                        </h6>
                        <span class="badge bg-${badgeColor} field-type-badge">${field.field_type.replace('_', ' ')}</span>
                        ${optionsHtml}
                        ${metaHtml}
                    </div>
                </div>
                ${strategyHtml}
            </div>`;
        container.appendChild(card);
    });
}

function onStrategyChange(fieldId, strategy) {
    const extra = document.getElementById(`strategyExtra_${fieldId}`);
    if (strategy === 'fixed') {
        extra.classList.remove('d-none');
        extra.innerHTML = `<input type="text" class="form-control form-control-sm"
                           id="fixedValue_${fieldId}" placeholder="Enter fixed value">`;
    } else if (strategy === 'from_list') {
        extra.classList.remove('d-none');
        extra.innerHTML = `<textarea class="form-control form-control-sm" rows="3"
                           id="listValue_${fieldId}" placeholder="One value per line"></textarea>`;
    } else if (strategy === 'pick_options') {
        const field = formData ? formData.fields.find(f => f.field_id === fieldId) : null;
        if (field && field.options && field.options.length > 0) {
            const isCheckbox = field.field_type === 'checkbox';
            const inputType = isCheckbox ? 'checkbox' : 'radio';
            const optionsHtml = field.options
                .filter(o => o !== '')
                .map((opt, i) => `
                    <div class="form-check">
                        <input class="form-check-input" type="${inputType}"
                               name="pick_${fieldId}" id="pick_${fieldId}_${i}"
                               value="${escapeHtml(opt)}" checked>
                        <label class="form-check-label small" for="pick_${fieldId}_${i}">
                            ${escapeHtml(opt)}
                        </label>
                    </div>`).join('');

            const note = isCheckbox
                ? 'Random subset of checked options per submission'
                : field.options.filter(o => o !== '').length > 1
                    ? 'One checked option picked randomly per submission'
                    : '';

            extra.classList.remove('d-none');
            extra.innerHTML = `
                <div class="pick-options-list mt-1">${optionsHtml}</div>
                ${note ? `<div class="form-text small text-muted mt-1"><i class="bi bi-info-circle"></i> ${note}</div>` : ''}`;
        }
    } else if (strategy === 'template') {
        extra.classList.remove('d-none');
        extra.innerHTML = `
            <input type="text" class="form-control form-control-sm mb-2"
                   id="templateValue_${fieldId}"
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

async function startGenericSubmission() {
    if (!formData) return;

    const count = parseInt(document.getElementById('submitCount').value) || 1;
    const delay = parseInt(document.getElementById('submitDelay').value) || 2000;
    const proxyText = document.getElementById('proxyInput').value.trim();
    const proxies = proxyText ? proxyText.split('\n').map(p => p.trim()).filter(Boolean) : [];
    const submitSelector = document.getElementById('submitSelector').value.trim();

    // Collect strategies
    const strategies = {};
    formData.fields.forEach(field => {
        const sel = document.getElementById(`strategy_${field.field_id}`);
        if (!sel) return;
        const strat = { strategy: sel.value };
        if (sel.value === 'fixed') {
            const inp = document.getElementById(`fixedValue_${field.field_id}`);
            strat.fixed_value = inp ? inp.value : '';
        } else if (sel.value === 'pick_options') {
            const checked = [...document.querySelectorAll(`input[name="pick_${field.field_id}"]:checked`)];
            strat.picked_options = checked.map(el => el.value);
        } else if (sel.value === 'from_list') {
            const ta = document.getElementById(`listValue_${field.field_id}`);
            strat.value_list = ta ? ta.value.split('\n').filter(Boolean) : [];
        } else if (sel.value === 'template') {
            const inp = document.getElementById(`templateValue_${field.field_id}`);
            strat.template = inp ? inp.value : '';
        }
        strategies[field.field_id] = strat;
    });

    const payload = {
        form_url: formData.page_url || document.getElementById('formUrl').value.trim(),
        fields: formData.fields,
        strategies,
        count,
        delay_ms: delay,
        proxies,
        submit_selector: submitSelector,
    };

    try {
        const resp = await fetch('/api/generic/submit/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await resp.json();
        if (data.success) {
            currentJobId = data.job_id;
            generateSamplePreview(strategies);
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
    appendLog('Submission started (browser mode)...', 'info');
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
            let summary = `#${data.index} Submitted successfully`;
            if (data.answers) {
                const vals = Object.values(data.answers);
                if (vals.length > 0) {
                    const preview = vals.slice(0, 5).map(v =>
                        Array.isArray(v) ? v.join('+') : String(v)
                    ).map(v => v.length > 20 ? v.substring(0, 20) + '..' : v).join(' | ');
                    summary += ` — ${preview}${vals.length > 5 ? ' ...' : ''}`;
                }
            }
            appendLog(summary, 'success');
        } else if (data.type === 'complete' || data.type === 'stopped') {
            onJobDone(data);
        }
    };

    eventSource.onerror = function () {
        if (currentJobId) {
            appendLog('Connection lost. The job may still be running on the server.', 'error');
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

// ============ SAMPLE PREVIEW ============

function generateSamplePreview(strategies) {
    if (!formData || !formData.fields) return;

    const container = document.getElementById('samplePreview');
    const body = document.getElementById('samplePreviewBody');

    let questionNum = 0;
    let rows = '';

    formData.fields.forEach(field => {
        questionNum++;

        const strat = strategies[field.field_id] || { strategy: 'random' };
        const label = field.label ? (field.label.length > 80 ? field.label.substring(0, 80) + '...' : field.label) : '(unlabeled)';
        let answer = '';
        let answerClass = '';

        switch (strat.strategy) {
            case 'fixed':
                answer = strat.fixed_value || '(empty)';
                answerClass = 'text-primary';
                break;
            case 'pick_options':
                if (strat.picked_options && strat.picked_options.length > 0) {
                    answer = strat.picked_options.join(', ');
                    if (strat.picked_options.length > 1) {
                        answer += ' <span class="badge bg-secondary">random pick</span>';
                    }
                } else {
                    answer = '<span class="text-warning">(no options selected)</span>';
                }
                answerClass = 'text-success';
                break;
            case 'from_list':
                if (strat.value_list && strat.value_list.length > 0) {
                    const preview = strat.value_list.slice(0, 3).join(', ');
                    answer = `Cycling: ${preview}${strat.value_list.length > 3 ? '...' : ''}`;
                } else {
                    answer = '(empty list)';
                }
                answerClass = 'text-info';
                break;
            case 'template':
                answer = `<code>${escapeHtml(strat.template || '')}</code>`;
                answerClass = '';
                break;
            default:
                if (field.options && field.options.length > 0) {
                    const validOpts = field.options.filter(o => o !== '');
                    const sample = validOpts[Math.floor(Math.random() * validOpts.length)];
                    answer = `<span class="text-muted">(random)</span> e.g. ${escapeHtml(sample)}`;
                } else {
                    answer = '<span class="text-muted">(random auto-detect)</span>';
                }
                break;
        }

        rows += `<tr>
            <td class="text-center text-muted">${questionNum}</td>
            <td class="small">${escapeHtml(label)}</td>
            <td class="small ${answerClass}">${answer}</td>
        </tr>`;
    });

    body.innerHTML = `
        <table class="table table-sm table-striped mb-0">
            <thead class="table-light">
                <tr>
                    <th style="width:40px">#</th>
                    <th>Question</th>
                    <th style="width:40%">Sample Answer</th>
                </tr>
            </thead>
            <tbody>${rows}</tbody>
        </table>`;

    container.classList.remove('d-none');
}

function toggleSamplePreview() {
    const body = document.getElementById('samplePreviewBody');
    const icon = document.getElementById('sampleToggleIcon');
    if (body.classList.contains('d-none')) {
        body.classList.remove('d-none');
        icon.className = 'bi bi-chevron-up';
    } else {
        body.classList.add('d-none');
        icon.className = 'bi bi-chevron-down';
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
