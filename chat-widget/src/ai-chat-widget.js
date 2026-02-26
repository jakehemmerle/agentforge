/**
 * AI Chat Widget
 *
 * Floating chat widget that connects to the AI agent FastAPI server
 * via Server-Sent Events (SSE) for streaming responses.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

(function () {
    'use strict';

    var marked = require('marked');

    var AI_AGENT_URL = (typeof window !== 'undefined' && typeof window.aiAgentUrl !== 'undefined')
        ? window.aiAgentUrl
        : 'http://localhost:8350';

    var AI_AGENT_API_KEY = (typeof window !== 'undefined' && typeof window.aiAgentApiKey !== 'undefined')
        ? window.aiAgentApiKey
        : '';

    var ICONS = {
        chat: '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H5.2L4 17.2V4h16v12z"/><path d="M7 9h10v2H7zm0-3h10v2H7z"/></svg>',
        send: '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>',
        close: '\u2212',
        spark: '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M12 2L9.19 8.63 2 9.24l5.46 4.73L5.82 21 12 17.27 18.18 21l-1.64-7.03L22 9.24l-7.19-.61z"/></svg>',
        clear: '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>',
        wrench: '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M22.7 19l-9.1-9.1c.9-2.3.4-5-1.5-6.9-2-2-5-2.4-7.4-1.3L9 6 6 9 1.6 4.7C.4 7.1.9 10.1 2.9 12.1c1.9 1.9 4.6 2.4 6.9 1.5l9.1 9.1c.4.4 1 .4 1.4 0l2.3-2.3c.5-.4.5-1.1.1-1.4z"/></svg>',
        chevron: '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z"/></svg>',
        check: '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>'
    };

    function getSessionId() {
        var key = 'ai_chat_session_id';
        var id = sessionStorage.getItem(key);
        if (!id) {
            id = 'sess_' + Date.now() + '_' + Math.random().toString(36).substring(2, 9);
            sessionStorage.setItem(key, id);
        }
        return id;
    }

    function escapeHtml(text) {
        var div = document.createElement('div');
        div.appendChild(document.createTextNode(text));
        return div.innerHTML;
    }

    /**
     * Parse a single SSE line and return the data payload, or null if not a data line.
     */
    function parseSSELine(line) {
        if (line.indexOf('data:') !== 0) {
            return null;
        }

        var payload = line.substring(5);
        if (payload.charAt(0) === ' ') {
            payload = payload.substring(1);
        }
        if (payload.charAt(payload.length - 1) === '\r') {
            payload = payload.substring(0, payload.length - 1);
        }

        return payload;
    }

    marked.setOptions({ breaks: true });

    function AiChatWidget() {
        this.isOpen = false;
        this.isStreaming = false;
        this.sessionId = getSessionId();
        this.messages = [];
        this.abortController = null;
        this._build();
        this._bindEvents();
        this._initResize();
        this._restoreDevState();
    }

    AiChatWidget.prototype._build = function () {
        // Floating button
        this.btn = document.createElement('button');
        this.btn.className = 'ai-chat-btn';
        this.btn.setAttribute('aria-label', 'Open AI Assistant');
        this.btn.setAttribute('title', 'AI Assistant');
        this.btn.innerHTML = ICONS.chat;

        // Panel
        this.panel = document.createElement('div');
        this.panel.className = 'ai-chat-panel';
        this.panel.innerHTML =
            '<div class="ai-chat-resize-handle"></div>' +
            '<div class="ai-chat-header">' +
                '<div class="ai-chat-header-title">' + ICONS.spark + ' AI Assistant</div>' +
                '<div class="ai-chat-header-actions">' +
                    '<button class="ai-chat-clear" aria-label="Clear chat">' + ICONS.clear + '</button>' +
                    '<button class="ai-chat-minimize" aria-label="Minimize">' + ICONS.close + '</button>' +
                '</div>' +
            '</div>' +
            '<div class="ai-chat-messages"></div>' +
            '<div class="ai-chat-input-area">' +
                '<textarea class="ai-chat-input" placeholder="Ask about appointments, patients..." rows="1"></textarea>' +
                '<button class="ai-chat-send" aria-label="Send" disabled>' + ICONS.send + '</button>' +
            '</div>';

        this.messagesEl = this.panel.querySelector('.ai-chat-messages');
        this.inputEl = this.panel.querySelector('.ai-chat-input');
        this.sendBtn = this.panel.querySelector('.ai-chat-send');
        this.minimizeBtn = this.panel.querySelector('.ai-chat-minimize');
        this.clearBtn = this.panel.querySelector('.ai-chat-clear');
        this.resizeHandle = this.panel.querySelector('.ai-chat-resize-handle');

        // Restore saved panel size
        var savedSize = sessionStorage.getItem('__ai_chat_panel_size');
        if (savedSize) {
            try {
                var size = JSON.parse(savedSize);
                this.panel.style.width = size.width + 'px';
                this.panel.style.height = size.height + 'px';
            } catch (e) { /* ignore */ }
        }

        document.body.appendChild(this.panel);
        document.body.appendChild(this.btn);

        // Show welcome message
        this._addMessage('assistant', 'Hello! I can help you find appointments, look up patient information, and more. How can I assist you today?');
    };

    AiChatWidget.prototype._bindEvents = function () {
        var self = this;

        this.btn.addEventListener('click', function () {
            self.toggle();
        });

        this.minimizeBtn.addEventListener('click', function () {
            self.toggle();
        });

        this.clearBtn.addEventListener('click', function () {
            self._clearChat();
        });

        this.sendBtn.addEventListener('click', function () {
            self._sendMessage();
        });

        this.inputEl.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                self._sendMessage();
            }
        });

        this.inputEl.addEventListener('input', function () {
            self.sendBtn.disabled = !self.inputEl.value.trim() || self.isStreaming;
            // Auto-resize textarea
            self.inputEl.style.height = 'auto';
            self.inputEl.style.height = Math.min(self.inputEl.scrollHeight, 80) + 'px';
        });
    };

    AiChatWidget.prototype.toggle = function () {
        this.isOpen = !this.isOpen;
        if (this.isOpen) {
            this.panel.classList.add('open');
            this.btn.style.display = 'none';
            this.inputEl.focus();
            this._scrollToBottom();
        } else {
            this.panel.classList.remove('open');
            this.btn.style.display = 'flex';
        }
    };

    AiChatWidget.prototype._addMessage = function (role, text) {
        var msgEl = document.createElement('div');
        msgEl.className = 'ai-chat-msg ai-chat-msg-' + role;
        if (role === 'assistant') {
            msgEl.innerHTML = marked.parse(text);
        } else {
            msgEl.textContent = text;
        }
        this.messagesEl.appendChild(msgEl);
        this.messages.push({ role: role, content: text });
        this._scrollToBottom();
        return msgEl;
    };

    AiChatWidget.prototype._showTyping = function () {
        var el = document.createElement('div');
        el.className = 'ai-chat-typing';
        el.id = 'ai-chat-typing-indicator';
        el.innerHTML =
            '<div class="ai-chat-typing-dot"></div>' +
            '<div class="ai-chat-typing-dot"></div>' +
            '<div class="ai-chat-typing-dot"></div>';
        this.messagesEl.appendChild(el);
        this._scrollToBottom();
        return el;
    };

    AiChatWidget.prototype._removeTyping = function () {
        var el = document.getElementById('ai-chat-typing-indicator');
        if (el) {
            el.remove();
        }
    };

    AiChatWidget.prototype._addToolCall = function (toolName) {
        var label = toolName.replace(/_/g, ' ');
        label = label.charAt(0).toUpperCase() + label.slice(1);

        var el = document.createElement('div');
        el.className = 'ai-chat-tool';
        el.setAttribute('data-tool', toolName);
        el.innerHTML =
            '<div class="ai-chat-tool-header">' +
                '<span class="ai-chat-tool-icon">' + ICONS.wrench + '</span>' +
                '<span class="ai-chat-tool-name">' + escapeHtml(label) + '</span>' +
                '<span class="ai-chat-tool-status"><span class="spinner-border" role="status"></span></span>' +
                '<span class="ai-chat-tool-chevron">' + ICONS.chevron + '</span>' +
            '</div>' +
            '<div class="ai-chat-tool-body"></div>';

        var header = el.querySelector('.ai-chat-tool-header');
        header.addEventListener('click', function () {
            el.classList.toggle('expanded');
        });

        this.messagesEl.appendChild(el);
        this._scrollToBottom();
        return el;
    };

    AiChatWidget.prototype._updateToolResult = function (toolName, content) {
        // Find the last tool call element matching this name
        var tools = this.messagesEl.querySelectorAll('.ai-chat-tool[data-tool="' + toolName + '"]');
        if (!tools.length) { return; }
        var el = tools[tools.length - 1];

        // Replace spinner with checkmark
        var status = el.querySelector('.ai-chat-tool-status');
        if (status) {
            status.innerHTML = '<span class="ai-chat-tool-check">' + ICONS.check + '</span>';
        }

        // Populate the body with a pretty-rendered result
        var body = el.querySelector('.ai-chat-tool-body');
        if (body) {
            body.innerHTML = this._renderToolBody(toolName, content);
        }
    };

    AiChatWidget.prototype._renderToolBody = function (toolName, content) {
        var data;
        try {
            data = JSON.parse(content);
        } catch (e) {
            return '<pre class="ai-chat-tool-raw">' + escapeHtml(content) + '</pre>';
        }

        switch (toolName) {
            case 'find_appointments': return this._renderAppointments(data);
            case 'get_encounter_context': return this._renderEncounter(data);
            case 'draft_encounter_note': return this._renderDraftNote(data);
            case 'validate_claim_ready_completeness': return this._renderValidation(data);
            default:
                return '<pre class="ai-chat-tool-raw">' + escapeHtml(JSON.stringify(data, null, 2)) + '</pre>';
        }
    };

    AiChatWidget.prototype._renderAppointments = function (data) {
        var appts = data.appointments || [];
        if (!appts.length) {
            var msg = data.message || 'No appointments found';
            return '<div class="ai-chat-tr-empty">' + escapeHtml(msg) + '</div>';
        }
        var html = '<div class="ai-chat-tr-count">' + appts.length + ' appointment' + (appts.length !== 1 ? 's' : '') + '</div>';
        html += '<table class="ai-chat-tr-table"><thead><tr><th>Time</th><th>Patient</th><th>Status</th><th>Category</th></tr></thead><tbody>';
        for (var i = 0; i < appts.length; i++) {
            var a = appts[i];
            var time = (a.start_time || '').substring(0, 5);
            var statusCls = (a.status_label || '').toLowerCase().indexOf('open') >= 0 ? ' ai-chat-tr-open' :
                            (a.status_label || '').toLowerCase().indexOf('arrived') >= 0 ? ' ai-chat-tr-arrived' :
                            (a.status_label || '').toLowerCase().indexOf('checked') >= 0 ? ' ai-chat-tr-done' :
                            (a.status_label || '').toLowerCase().indexOf('no show') >= 0 ? ' ai-chat-tr-noshow' : '';
            html += '<tr><td>' + escapeHtml(time) + '</td>'
                + '<td>' + escapeHtml(a.patient_name || '') + '</td>'
                + '<td class="' + statusCls + '">' + escapeHtml(a.status_label || a.status || '') + '</td>'
                + '<td>' + escapeHtml(a.category || '') + '</td></tr>';
        }
        html += '</tbody></table>';
        if (data.data_warnings && data.data_warnings.length) {
            html += '<div class="ai-chat-tr-warn">' + escapeHtml(data.data_warnings.join('; ')) + '</div>';
        }
        return html;
    };

    AiChatWidget.prototype._renderEncounter = function (data) {
        var html = '';
        var p = data.patient || {};
        var e = data.encounter || {};
        html += '<div class="ai-chat-tr-row"><strong>' + escapeHtml(p.name || 'Patient') + '</strong>';
        if (p.dob) { html += ' &middot; DOB ' + escapeHtml(p.dob); }
        if (p.sex) { html += ' &middot; ' + escapeHtml(p.sex); }
        html += '</div>';
        html += '<div class="ai-chat-tr-row">' + escapeHtml(e.date || '') + ' &mdash; ' + escapeHtml(e.reason || 'Encounter') + '</div>';
        var cc = data.clinical_context || {};
        if (cc.active_problems && cc.active_problems.length) {
            html += '<div class="ai-chat-tr-label">Problems</div><ul class="ai-chat-tr-list">';
            for (var i = 0; i < cc.active_problems.length; i++) {
                var prob = cc.active_problems[i];
                html += '<li>' + escapeHtml(prob.description || '') + (prob.code ? ' <span class="ai-chat-tr-code">' + escapeHtml(prob.code) + '</span>' : '') + '</li>';
            }
            html += '</ul>';
        }
        if (cc.medications && cc.medications.length) {
            html += '<div class="ai-chat-tr-label">Medications</div><ul class="ai-chat-tr-list">';
            for (var i = 0; i < cc.medications.length; i++) {
                var med = cc.medications[i];
                html += '<li>' + escapeHtml(med.drug_name || '') + (med.dose ? ' ' + escapeHtml(med.dose) : '') + (med.frequency ? ', ' + escapeHtml(med.frequency) : '') + '</li>';
            }
            html += '</ul>';
        }
        if (cc.allergies && cc.allergies.length) {
            html += '<div class="ai-chat-tr-label">Allergies</div><ul class="ai-chat-tr-list">';
            for (var i = 0; i < cc.allergies.length; i++) {
                var al = cc.allergies[i];
                html += '<li>' + escapeHtml(al.substance || '') + (al.reaction ? ' &rarr; ' + escapeHtml(al.reaction) : '') + '</li>';
            }
            html += '</ul>';
        }
        if (cc.vitals) {
            var v = cc.vitals;
            var parts = [];
            if (v.bp) parts.push('BP ' + v.bp);
            if (v.hr) parts.push('HR ' + v.hr);
            if (v.temp) parts.push('Temp ' + v.temp);
            if (v.spo2) parts.push('SpO2 ' + v.spo2 + '%');
            if (parts.length) {
                html += '<div class="ai-chat-tr-label">Vitals</div><div class="ai-chat-tr-row">' + escapeHtml(parts.join(' &middot; ')) + '</div>';
            }
        }
        if (data.data_warnings && data.data_warnings.length) {
            html += '<div class="ai-chat-tr-warn">' + escapeHtml(data.data_warnings.join('; ')) + '</div>';
        }
        return html;
    };

    AiChatWidget.prototype._renderDraftNote = function (data) {
        var html = '';
        var note = data.draft_note || {};
        html += '<div class="ai-chat-tr-row"><strong>' + escapeHtml((note.type || 'Note').toUpperCase()) + '</strong>';
        if (note.patient_name) { html += ' &mdash; ' + escapeHtml(note.patient_name); }
        html += '</div>';
        if (note.content) {
            var c = note.content;
            if (c.subjective) { html += '<div class="ai-chat-tr-label">Subjective</div><div class="ai-chat-tr-text">' + escapeHtml(c.subjective) + '</div>'; }
            if (c.objective) { html += '<div class="ai-chat-tr-label">Objective</div><div class="ai-chat-tr-text">' + escapeHtml(c.objective) + '</div>'; }
            if (c.assessment) { html += '<div class="ai-chat-tr-label">Assessment</div><div class="ai-chat-tr-text">' + escapeHtml(c.assessment) + '</div>'; }
            if (c.plan) { html += '<div class="ai-chat-tr-label">Plan</div><div class="ai-chat-tr-text">' + escapeHtml(c.plan) + '</div>'; }
            if (c.narrative) { html += '<div class="ai-chat-tr-text">' + escapeHtml(c.narrative) + '</div>'; }
            if (c.summary) { html += '<div class="ai-chat-tr-text">' + escapeHtml(c.summary) + '</div>'; }
        } else if (note.full_text) {
            html += '<div class="ai-chat-tr-text">' + escapeHtml(note.full_text) + '</div>';
        }
        if (data.warnings && data.warnings.length) {
            for (var i = 0; i < data.warnings.length; i++) {
                html += '<div class="ai-chat-tr-warn">' + escapeHtml(data.warnings[i]) + '</div>';
            }
        }
        if (data.disclaimer) {
            html += '<div class="ai-chat-tr-disclaimer">' + escapeHtml(data.disclaimer) + '</div>';
        }
        return html;
    };

    AiChatWidget.prototype._renderValidation = function (data) {
        var html = '';
        var ready = data.ready;
        html += '<div class="ai-chat-tr-status ' + (ready ? 'ai-chat-tr-pass' : 'ai-chat-tr-fail') + '">'
            + (ready ? 'Ready for submission' : 'Not ready') + '</div>';
        var checks = (data.errors || []).concat(data.warnings || []);
        if (checks.length) {
            html += '<div class="ai-chat-tr-checks">';
            for (var i = 0; i < checks.length; i++) {
                var c = checks[i];
                var icon = c.severity === 'error' ? '<span class="ai-chat-tr-x">&times;</span>' : '<span class="ai-chat-tr-bang">!</span>';
                html += '<div class="ai-chat-tr-check-item">' + icon + ' ' + escapeHtml(c.message || c.check) + '</div>';
            }
            html += '</div>';
        }
        var s = data.summary || {};
        if (s.dx_codes && s.dx_codes.length) {
            html += '<div class="ai-chat-tr-row">Dx: ' + s.dx_codes.map(function(c) { return '<span class="ai-chat-tr-code">' + escapeHtml(c) + '</span>'; }).join(' ') + '</div>';
        }
        if (s.cpt_codes && s.cpt_codes.length) {
            html += '<div class="ai-chat-tr-row">CPT: ' + s.cpt_codes.map(function(c) { return '<span class="ai-chat-tr-code">' + escapeHtml(c) + '</span>'; }).join(' ') + '</div>';
        }
        if (s.total_charges) {
            html += '<div class="ai-chat-tr-row">Charges: $' + escapeHtml(String(s.total_charges)) + '</div>';
        }
        return html;
    };

    AiChatWidget.prototype._scrollToBottom = function () {
        var el = this.messagesEl;
        requestAnimationFrame(function () {
            el.scrollTop = el.scrollHeight;
        });
    };

    AiChatWidget.prototype._sendMessage = function () {
        var text = this.inputEl.value.trim();
        if (!text || this.isStreaming) {
            return;
        }

        this._addMessage('user', text);
        this.inputEl.value = '';
        this.inputEl.style.height = 'auto';
        this.sendBtn.disabled = true;
        this.isStreaming = true;

        this._streamResponse(text);
    };

    AiChatWidget.prototype._streamResponse = function (message) {
        var self = this;
        var typingEl = this._showTyping();
        var responseEl = null;
        var responseText = '';
        var segmentText = '';

        this.abortController = new AbortController();

        var fetchHeaders = { 'Content-Type': 'application/json' };
        if (AI_AGENT_API_KEY) {
            fetchHeaders['X-API-Key'] = AI_AGENT_API_KEY;
        }

        fetch(AI_AGENT_URL + '/api/stream', {
            method: 'POST',
            headers: fetchHeaders,
            body: JSON.stringify({
                message: message,
                session_id: this.sessionId
            }),
            signal: this.abortController.signal
        }).then(function (response) {
            if (!response.ok) {
                throw new Error('Server responded with status ' + response.status);
            }

            var reader = response.body.getReader();
            var decoder = new TextDecoder();
            var buffer = '';

            var finished = false;

            function processParsedLine(data) {
                if (data === null) {
                    return false;
                }

                if (data === '[DONE]') {
                    if (!finished) {
                        finished = true;
                        self._finishStream(responseEl, responseText);
                    }
                    return true;
                }

                if (data === '[ERROR]') {
                    self._removeTyping();
                    if (!responseEl) {
                        self._addMessage('assistant', 'Sorry, something went wrong while processing your request. Please try again.');
                    }
                    return false;
                }

                // Tool call start — reset responseEl so post-tool text
                // gets its own element positioned after the tool call
                var toolMatch = data.match(/^\[calling:(.+)\]$/);
                if (toolMatch) {
                    self._removeTyping();
                    responseEl = null;
                    segmentText = '';
                    self._addToolCall(toolMatch[1]);
                    return false;
                }

                // Tool call result
                if (data.indexOf('[tool_done]') === 0) {
                    try {
                        var info = JSON.parse(data.substring(11));
                        self._updateToolResult(info.name, info.content);
                    } catch (e) { /* ignore malformed result */ }
                    return false;
                }

                // Text token (JSON-encoded by server to preserve newlines)
                var text = data;
                if (data.charAt(0) === '"') {
                    try { text = JSON.parse(data); } catch (e) { /* use raw */ }
                }

                if (!text) { return false; }

                self._removeTyping();

                if (!responseEl) {
                    responseEl = document.createElement('div');
                    responseEl.className = 'ai-chat-msg ai-chat-msg-assistant';
                    self.messagesEl.appendChild(responseEl);
                    segmentText = '';
                }

                responseText += text;
                segmentText += text;
                responseEl.innerHTML = marked.parse(segmentText);
                self._scrollToBottom();
                return false;
            }

            function processChunk() {
                return reader.read().then(function (result) {
                    if (result.done) {
                        // Flush any remaining data in the buffer
                        if (buffer.trim()) {
                            var finalData = parseSSELine(buffer);
                            processParsedLine(finalData);
                            buffer = '';
                        }
                        if (!finished) {
                            finished = true;
                            self._finishStream(responseEl, responseText);
                        }
                        return;
                    }

                    buffer += decoder.decode(result.value, { stream: true });
                    var lines = buffer.split('\n');
                    buffer = lines.pop() || '';

                    for (var i = 0; i < lines.length; i++) {
                        var data = parseSSELine(lines[i]);
                        var done = processParsedLine(data);
                        if (done) {
                            return;
                        }
                    }

                    return processChunk();
                });
            }

            return processChunk();
        }).catch(function (err) {
            self._removeTyping();

            if (err.name === 'AbortError') {
                self.isStreaming = false;
                self.abortController = null;
                self.sendBtn.disabled = !self.inputEl.value.trim();
                return;
            }

            var errorMsg = 'Sorry, I couldn\'t connect to the AI service. Please make sure the AI agent is running.';
            self._addMessage('assistant', errorMsg);
            self.isStreaming = false;
            self.sendBtn.disabled = !self.inputEl.value.trim();
        });
    };

    AiChatWidget.prototype._restoreDevState = function () {
        var raw = sessionStorage.getItem('__dev_reload_state');
        if (!raw) {
            return;
        }
        sessionStorage.removeItem('__dev_reload_state');

        var state;
        try {
            state = JSON.parse(raw);
        } catch (e) {
            return;
        }

        // Clear the default welcome message
        this.messagesEl.innerHTML = '';
        this.messages = [];

        // Replay saved messages
        if (state.messages) {
            for (var i = 0; i < state.messages.length; i++) {
                this._addMessage(state.messages[i].role, state.messages[i].content);
            }
        }

        // Restore panel size
        if (state.panelSize && state.panelSize.width && state.panelSize.height) {
            this.panel.style.width = state.panelSize.width + 'px';
            this.panel.style.height = state.panelSize.height + 'px';
            sessionStorage.setItem('__ai_chat_panel_size', JSON.stringify(state.panelSize));
        }

        // Restore open/closed state
        if (state.isOpen && !this.isOpen) {
            this.toggle();
        }
    };

    AiChatWidget.prototype._finishStream = function (responseEl, responseText) {
        this._removeTyping();

        if (responseText) {
            this.messages.push({ role: 'assistant', content: responseText });
        }

        this.isStreaming = false;
        this.abortController = null;
        this.sendBtn.disabled = !this.inputEl.value.trim();
    };

    AiChatWidget.prototype._clearChat = function () {
        // Abort any in-flight stream
        if (this.abortController) {
            this.abortController.abort();
            this.abortController = null;
        }
        this.isStreaming = false;

        // Clear DOM and state
        this.messagesEl.innerHTML = '';
        this.messages = [];

        // Re-add welcome message
        this._addMessage('assistant', 'Hello! I can help you find appointments, look up patient information, and more. How can I assist you today?');

        this.sendBtn.disabled = !this.inputEl.value.trim();
    };

    AiChatWidget.prototype._initResize = function () {
        var self = this;
        var handle = this.resizeHandle;
        if (!handle) { return; }

        var startX, startY, startW, startH;
        var overlay = null;

        function createOverlay() {
            overlay = document.createElement('div');
            overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;z-index:9999;cursor:nwse-resize;';
            document.body.appendChild(overlay);
        }

        function removeOverlay() {
            if (overlay) {
                overlay.remove();
                overlay = null;
            }
        }

        function saveSize() {
            var w = parseInt(self.panel.style.width, 10);
            var h = parseInt(self.panel.style.height, 10);
            if (w && h) {
                sessionStorage.setItem('__ai_chat_panel_size', JSON.stringify({ width: w, height: h }));
            }
        }

        function onMouseMove(e) {
            var dx = startX - e.clientX;
            var dy = startY - e.clientY;
            var newW = Math.min(Math.max(startW + dx, 300), window.innerWidth * 0.9);
            var newH = Math.min(Math.max(startH + dy, 350), window.innerHeight * 0.9);
            self.panel.style.width = newW + 'px';
            self.panel.style.height = newH + 'px';
        }

        function onMouseUp() {
            document.removeEventListener('mousemove', onMouseMove);
            document.removeEventListener('mouseup', onMouseUp);
            removeOverlay();
            saveSize();
        }

        handle.addEventListener('mousedown', function (e) {
            e.preventDefault();
            startX = e.clientX;
            startY = e.clientY;
            startW = self.panel.offsetWidth;
            startH = self.panel.offsetHeight;
            createOverlay();
            document.addEventListener('mousemove', onMouseMove);
            document.addEventListener('mouseup', onMouseUp);
        });

        // Touch support
        function onTouchMove(e) {
            var touch = e.touches[0];
            var dx = startX - touch.clientX;
            var dy = startY - touch.clientY;
            var newW = Math.min(Math.max(startW + dx, 300), window.innerWidth * 0.9);
            var newH = Math.min(Math.max(startH + dy, 350), window.innerHeight * 0.9);
            self.panel.style.width = newW + 'px';
            self.panel.style.height = newH + 'px';
        }

        function onTouchEnd() {
            document.removeEventListener('touchmove', onTouchMove);
            document.removeEventListener('touchend', onTouchEnd);
            removeOverlay();
            saveSize();
        }

        handle.addEventListener('touchstart', function (e) {
            e.preventDefault();
            var touch = e.touches[0];
            startX = touch.clientX;
            startY = touch.clientY;
            startW = self.panel.offsetWidth;
            startH = self.panel.offsetHeight;
            createOverlay();
            document.addEventListener('touchmove', onTouchMove);
            document.addEventListener('touchend', onTouchEnd);
        });
    };

    // Initialize when DOM is ready (skip in Node/test environments)
    if (typeof document !== 'undefined' && typeof window !== 'undefined' && !window.__AI_CHAT_TEST) {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', function () {
                new AiChatWidget();
            });
        } else {
            new AiChatWidget();
        }
    }

    // Export for testing (Node/CommonJS)
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = { AiChatWidget: AiChatWidget, parseSSELine: parseSSELine };
    }
})();
