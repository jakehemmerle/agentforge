/**
 * @jest-environment jsdom
 */

/**
 * Tests for AI Chat Widget core functionality.
 *
 * Covers constructor, toggle, addMessage, sendMessage, and parseSSELine.
 */

var widget = require('../src/ai-chat-widget');
var AiChatWidget = widget.AiChatWidget;
var parseSSELine = widget.parseSSELine;

describe('AiChatWidget', function () {
    var w;

    beforeEach(function () {
        document.body.innerHTML = '';
        // Provide sessionStorage stub
        var store = {};
        jest.spyOn(Storage.prototype, 'getItem').mockImplementation(function (key) {
            return store[key] || null;
        });
        jest.spyOn(Storage.prototype, 'setItem').mockImplementation(function (key, val) {
            store[key] = val;
        });

        w = new AiChatWidget();
    });

    afterEach(function () {
        jest.restoreAllMocks();
    });

    describe('constructor', function () {
        test('initializes with isOpen = false', function () {
            expect(w.isOpen).toBe(false);
        });

        test('initializes with isStreaming = false', function () {
            expect(w.isStreaming).toBe(false);
        });

        test('generates a session ID', function () {
            expect(w.sessionId).toMatch(/^sess_/);
        });

        test('creates messages array with welcome message', function () {
            expect(w.messages.length).toBe(1);
            expect(w.messages[0].role).toBe('assistant');
        });

        test('appends button and panel to document body', function () {
            expect(document.querySelector('.ai-chat-btn')).not.toBeNull();
            expect(document.querySelector('.ai-chat-panel')).not.toBeNull();
        });

        test('sets abortController to null', function () {
            expect(w.abortController).toBeNull();
        });
    });

    describe('toggle', function () {
        test('opens panel on first toggle', function () {
            w.toggle();
            expect(w.isOpen).toBe(true);
            expect(w.panel.classList.contains('open')).toBe(true);
            expect(w.btn.style.display).toBe('none');
        });

        test('closes panel on second toggle', function () {
            w.toggle();
            w.toggle();
            expect(w.isOpen).toBe(false);
            expect(w.panel.classList.contains('open')).toBe(false);
            expect(w.btn.style.display).toBe('flex');
        });
    });

    describe('_addMessage', function () {
        test('adds a user message to the DOM', function () {
            w._addMessage('user', 'Hello');
            var msgs = w.messagesEl.querySelectorAll('.ai-chat-msg-user');
            expect(msgs.length).toBe(1);
            expect(msgs[0].textContent).toBe('Hello');
        });

        test('adds an assistant message to the DOM', function () {
            w._addMessage('assistant', 'Hi there');
            // welcome message + our new one
            var msgs = w.messagesEl.querySelectorAll('.ai-chat-msg-assistant');
            expect(msgs.length).toBe(2);
        });

        test('pushes message to messages array', function () {
            var before = w.messages.length;
            w._addMessage('user', 'Test');
            expect(w.messages.length).toBe(before + 1);
            expect(w.messages[w.messages.length - 1]).toEqual({ role: 'user', content: 'Test' });
        });

        test('returns the created element', function () {
            var el = w._addMessage('user', 'Check');
            expect(el).toBeInstanceOf(HTMLElement);
            expect(el.textContent).toBe('Check');
        });
    });

    describe('_sendMessage', function () {
        beforeEach(function () {
            // Mock _streamResponse to avoid actual fetch
            w._streamResponse = jest.fn();
        });

        test('does nothing when input is empty', function () {
            w.inputEl.value = '';
            w._sendMessage();
            expect(w._streamResponse).not.toHaveBeenCalled();
        });

        test('does nothing when input is whitespace only', function () {
            w.inputEl.value = '   ';
            w._sendMessage();
            expect(w._streamResponse).not.toHaveBeenCalled();
        });

        test('does nothing when already streaming', function () {
            w.isStreaming = true;
            w.inputEl.value = 'test';
            w._sendMessage();
            expect(w._streamResponse).not.toHaveBeenCalled();
        });

        test('sends a message and calls _streamResponse', function () {
            w.inputEl.value = 'Hello AI';
            w._sendMessage();

            expect(w._streamResponse).toHaveBeenCalledWith('Hello AI');
            expect(w.isStreaming).toBe(true);
            expect(w.inputEl.value).toBe('');
            expect(w.sendBtn.disabled).toBe(true);
        });

        test('adds user message to the messages list', function () {
            w.inputEl.value = 'Test msg';
            var before = w.messages.length;
            w._sendMessage();
            expect(w.messages.length).toBe(before + 1);
            expect(w.messages[w.messages.length - 1]).toEqual({ role: 'user', content: 'Test msg' });
        });
    });
});

describe('parseSSELine', function () {
    test('parses "data: token" (with space)', function () {
        expect(parseSSELine('data: hello')).toBe('hello');
    });

    test('parses "data:token" (without space)', function () {
        expect(parseSSELine('data:hello')).toBe('hello');
    });

    test('parses "data: [DONE]"', function () {
        expect(parseSSELine('data: [DONE]')).toBe('[DONE]');
    });

    test('parses "data:[DONE]" without space', function () {
        expect(parseSSELine('data:[DONE]')).toBe('[DONE]');
    });

    test('parses tool call notification', function () {
        expect(parseSSELine('data: [calling:find_appointments]')).toBe('[calling:find_appointments]');
    });

    test('ignores empty lines', function () {
        expect(parseSSELine('')).toBeNull();
    });

    test('ignores comment lines', function () {
        expect(parseSSELine(': keep-alive')).toBeNull();
    });

    test('ignores non-data event lines', function () {
        expect(parseSSELine('event: message')).toBeNull();
    });

    test('preserves spaces within the payload', function () {
        expect(parseSSELine('data: hello world')).toBe('hello world');
    });

    test('handles data: with only a space (empty payload)', function () {
        expect(parseSSELine('data: ')).toBe('');
    });
});
