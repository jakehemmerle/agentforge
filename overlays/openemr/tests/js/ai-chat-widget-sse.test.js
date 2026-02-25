/**
 * @jest-environment jsdom
 */

/**
 * Tests for SSE line parsing in the AI Chat Widget.
 *
 * Uses the parseSSELine function exported from the widget module.
 */

var parseSSELine = require('../../interface/main/tabs/js/ai-chat-widget').parseSSELine;

describe('SSE line parsing', function () {
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
        var result = parseSSELine('data: [calling:find_appointments]');
        expect(result).toBe('[calling:find_appointments]');
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
