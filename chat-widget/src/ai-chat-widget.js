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
        clear: '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>'
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

    AiChatWidget.prototype._showToolCall = function (toolName) {
        this._removeToolCall();
        var el = document.createElement('div');
        el.className = 'ai-chat-tool-call';
        el.id = 'ai-chat-tool-indicator';

        var label = toolName.replace(/_/g, ' ');
        label = label.charAt(0).toUpperCase() + label.slice(1);
        el.innerHTML =
            '<span class="spinner-border text-secondary" role="status"></span>' +
            '<span>Searching: ' + escapeHtml(label) + '...</span>';
        this.messagesEl.appendChild(el);
        this._scrollToBottom();
        return el;
    };

    AiChatWidget.prototype._removeToolCall = function () {
        var el = document.getElementById('ai-chat-tool-indicator');
        if (el) {
            el.remove();
        }
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
                    self._removeToolCall();
                    if (!responseEl) {
                        self._addMessage('assistant', 'Sorry, something went wrong while processing your request. Please try again.');
                    }
                    return false;
                }

                // Tool call notification
                var toolMatch = data.match(/^\[calling:(.+)\]$/);
                if (toolMatch) {
                    self._removeTyping();
                    self._showToolCall(toolMatch[1]);
                    return false;
                }

                // Token
                self._removeTyping();
                self._removeToolCall();

                if (!responseEl) {
                    responseEl = document.createElement('div');
                    responseEl.className = 'ai-chat-msg ai-chat-msg-assistant';
                    self.messagesEl.appendChild(responseEl);
                }

                responseText += data;
                responseEl.innerHTML = marked.parse(responseText);
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
            self._removeToolCall();

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
        this._removeToolCall();

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
            var w = parseInt(self.panel.style.width, 10);
            var h = parseInt(self.panel.style.height, 10);
            if (w && h) {
                sessionStorage.setItem('__ai_chat_panel_size', JSON.stringify({ width: w, height: h }));
            }
        }

        handle.addEventListener('mousedown', function (e) {
            e.preventDefault();
            startX = e.clientX;
            startY = e.clientY;
            startW = self.panel.offsetWidth;
            startH = self.panel.offsetHeight;
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
            var w = parseInt(self.panel.style.width, 10);
            var h = parseInt(self.panel.style.height, 10);
            if (w && h) {
                sessionStorage.setItem('__ai_chat_panel_size', JSON.stringify({ width: w, height: h }));
            }
        }

        handle.addEventListener('touchstart', function (e) {
            e.preventDefault();
            var touch = e.touches[0];
            startX = touch.clientX;
            startY = touch.clientY;
            startW = self.panel.offsetWidth;
            startH = self.panel.offsetHeight;
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
