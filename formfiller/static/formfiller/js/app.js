// Global state
let formData = null;
let currentJobId = null;
let eventSource = null;
let formRequiresSignin = false;

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
        formRequiresSignin = true;
    }
    if (formRequiresSignin && !isGoogleAuthenticated) {
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
                   <option value="weighted">Weighted random (%)</option>
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
    } else if (strategy === 'pick_options') {
        const field = formData ? formData.fields.find(f => f.entry_id === entryId) : null;
        if (field && field.options && field.options.length > 0) {
            const isCheckbox = field.field_type === 'checkbox';
            const inputType = isCheckbox ? 'checkbox' : 'radio';
            const optionsHtml = field.options
                .filter(o => o !== '')
                .map((opt, i) => `
                    <div class="form-check">
                        <input class="form-check-input" type="${inputType}"
                               name="pick_${entryId}" id="pick_${entryId}_${i}"
                               value="${escapeHtml(opt)}" checked>
                        <label class="form-check-label small" for="pick_${entryId}_${i}">
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
    } else if (strategy === 'weighted') {
        const field = formData ? formData.fields.find(f => f.entry_id === entryId) : null;
        let options = [];
        if (field) {
            if (field.field_type === 'linear_scale') {
                const lo = field.scale_min || 1;
                const hi = field.scale_max || 5;
                for (let i = lo; i <= hi; i++) options.push(String(i));
            } else if (field.options) {
                options = field.options.filter(o => o !== '');
            }
        }
        if (options.length > 0) {
            const defaultWeight = Math.round(100 / options.length);
            const rows = options.map((opt, i) => `
                <div class="d-flex align-items-center gap-2 mb-1">
                    <span class="small flex-grow-1">${escapeHtml(opt)}</span>
                    <input type="number" class="form-control form-control-sm weight-input"
                           style="width: 80px" data-entry="${entryId}" data-idx="${i}"
                           value="${defaultWeight}" min="0" max="100">
                    <span class="small text-muted">%</span>
                </div>`).join('');
            extra.classList.remove('d-none');
            extra.innerHTML = `
                <div class="mt-1">${rows}</div>
                <div class="form-text small text-muted mt-1">
                    <i class="bi bi-info-circle"></i> Higher % = more likely. Does not need to sum to 100.
                </div>`;
        }
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
        } else if (sel.value === 'pick_options') {
            const checked = [...document.querySelectorAll(`input[name="pick_${field.entry_id}"]:checked`)];
            strat.picked_options = checked.map(el => el.value);
        } else if (sel.value === 'from_list') {
            const ta = document.getElementById(`listValue_${field.entry_id}`);
            strat.value_list = ta ? ta.value.split('\n').filter(Boolean) : [];
        } else if (sel.value === 'template') {
            const inp = document.getElementById(`templateValue_${field.entry_id}`);
            strat.template = inp ? inp.value : '';
        } else if (sel.value === 'weighted') {
            const weightInputs = document.querySelectorAll(`.weight-input[data-entry="${field.entry_id}"]`);
            const weights = {};
            let opts;
            if (field.field_type === 'linear_scale') {
                opts = [];
                for (let i = (field.scale_min || 1); i <= (field.scale_max || 5); i++) opts.push(String(i));
            } else {
                opts = (field.options || []).filter(o => o !== '');
            }
            weightInputs.forEach(inp => {
                const idx = parseInt(inp.dataset.idx);
                if (idx < opts.length) weights[opts[idx]] = parseFloat(inp.value) || 0;
            });
            strat.weights = weights;
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
            let errorMsg = data.message || '';
            if (errorMsg.includes('401')) {
                errorMsg += ' — Login to Google first (see Submission Settings > Google Account).';
            }
            appendLog(`#${data.index || '?'} Error: ${errorMsg}`, 'error');
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

// ============ SAMPLE PREVIEW ============

function generateSamplePreview(strategies) {
    if (!formData || !formData.fields) return;

    const container = document.getElementById('samplePreview');
    const body = document.getElementById('samplePreviewBody');

    let questionNum = 0;
    let rows = '';

    formData.fields.forEach(field => {
        if (field.field_type === 'file_upload') return;
        questionNum++;

        const strat = strategies[field.entry_id] || { strategy: 'random' };
        const label = field.label.length > 80 ? field.label.substring(0, 80) + '...' : field.label;
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
            case 'weighted':
                if (strat.weights) {
                    const entries = Object.entries(strat.weights)
                        .filter(([_, w]) => w > 0)
                        .sort((a, b) => b[1] - a[1]);
                    const top = entries.slice(0, 4).map(([opt, w]) => `${escapeHtml(opt)}: ${w}%`).join(', ');
                    answer = `<span class="text-muted">(weighted)</span> ${top}${entries.length > 4 ? ' ...' : ''}`;
                } else {
                    answer = '<span class="text-muted">(weighted random)</span>';
                }
                answerClass = 'text-info';
                break;
            default: // random
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

// ============ GOOGLE AUTH ============

function updateGoogleAuthUI() {
    const loggedOut = document.getElementById('settingsAuthLoggedOut');
    const loggedIn = document.getElementById('settingsAuthLoggedIn');
    if (loggedOut && loggedIn) {
        loggedOut.classList.toggle('d-none', isGoogleAuthenticated);
        loggedIn.classList.toggle('d-none', !isGoogleAuthenticated);
    }
}

async function googleLogin() {
    // Disable all login buttons
    document.querySelectorAll('#btnGoogleLogin, #btnSettingsLogin').forEach(btn => {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Opening...';
    });
    // Show all status areas
    document.querySelectorAll('#loginStatus, #settingsLoginStatus').forEach(el => {
        el.classList.remove('d-none');
        el.textContent = 'A browser window will open. Sign in to your Google account.';
    });

    try {
        const resp = await fetch('/api/google/login/', { method: 'POST' });
        const data = await resp.json();
        const msg = data.success
            ? 'Waiting for sign-in... (check the browser window)'
            : 'Login in progress. Check the browser window.';
        document.querySelectorAll('#loginStatus, #settingsLoginStatus').forEach(el => {
            el.textContent = msg;
        });
        pollLoginStatus();
    } catch (err) {
        document.querySelectorAll('#loginStatus, #settingsLoginStatus').forEach(el => {
            el.innerHTML = '<span class="text-danger">Error: ' + escapeHtml(err.message) + '</span>';
        });
        document.querySelectorAll('#btnGoogleLogin, #btnSettingsLogin').forEach(btn => {
            btn.disabled = false;
            btn.innerHTML = '<i class="bi bi-google"></i> Login to Google';
        });
    }
}

function pollLoginStatus() {
    const interval = setInterval(async () => {
        try {
            const resp = await fetch('/api/google/auth-status/');
            const data = await resp.json();

            if (data.status === 'authenticated') {
                clearInterval(interval);
                isGoogleAuthenticated = true;
                updateAuthBadge();
                updateGoogleAuthUI();

                const successMsg = formRequiresSignin
                    ? '<span class="text-success"><i class="bi bi-check-circle"></i> Logged in! Re-analyzing form...</span>'
                    : '<span class="text-success"><i class="bi bi-check-circle"></i> Logged in!</span>';
                document.querySelectorAll('#loginStatus, #settingsLoginStatus').forEach(el => {
                    el.innerHTML = successMsg;
                });

                const warnBtn = document.getElementById('btnGoogleLogin');
                if (warnBtn) warnBtn.classList.add('d-none');
                document.getElementById('btnStart').disabled = false;

                if (formRequiresSignin) {
                    setTimeout(() => parseForm(), 1000);
                }
            } else if (data.status === 'error') {
                clearInterval(interval);
                const errMsg = '<span class="text-danger"><i class="bi bi-x-circle"></i> ' + escapeHtml(data.error || 'Login failed') + '</span>';
                document.querySelectorAll('#loginStatus, #settingsLoginStatus').forEach(el => {
                    el.innerHTML = errMsg;
                });
                document.querySelectorAll('#btnGoogleLogin, #btnSettingsLogin').forEach(btn => {
                    btn.disabled = false;
                    btn.innerHTML = '<i class="bi bi-google"></i> Retry Login';
                });
            }
        } catch (err) {
            // Network error, keep polling
        }
    }, 2000);
}

function onGoogleLogout() {
    updateGoogleAuthUI();
    document.querySelectorAll('#loginStatus, #settingsLoginStatus').forEach(el => {
        el.classList.add('d-none');
    });
    if (formRequiresSignin) {
        document.getElementById('signinWarning').classList.remove('d-none');
        document.getElementById('btnStart').disabled = true;
        const btn = document.getElementById('btnGoogleLogin');
        if (btn) {
            btn.classList.remove('d-none');
            btn.disabled = false;
            btn.innerHTML = '<i class="bi bi-google"></i> Login to Google';
        }
    }
}
