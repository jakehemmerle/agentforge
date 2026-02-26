/**
 * Dev Hot-Reload Client
 *
 * Polls the dev server for version changes and hot-reloads CSS/JS
 * without a full page refresh. Only active when
 * window.__CHAT_WIDGET_DEV_RELOAD is truthy.
 */
(function () {
    'use strict';

    if (!window.__CHAT_WIDGET_DEV_RELOAD) {
        return;
    }

    var DEV_SERVER = 'http://localhost:8351';
    var POLL_INTERVAL = 1500;
    var knownJs = null;
    var knownCss = null;

    function log(msg) {
        console.log('[dev-reload] ' + msg);
    }

    function reloadCSS() {
        var link = document.querySelector('link[href*="ai-chat-widget.css"]');
        if (!link) {
            return;
        }
        var href = link.href.replace(/[?&]_dr=\d+/, '');
        var sep = href.indexOf('?') === -1 ? '?' : '&';
        link.href = href + sep + '_dr=' + Date.now();
        log('CSS reloaded');
    }

    function saveState() {
        var msgs = [];
        var els = document.querySelectorAll('.ai-chat-msg');
        for (var i = 0; i < els.length; i++) {
            var el = els[i];
            var role = el.classList.contains('ai-chat-msg-user') ? 'user' : 'assistant';
            msgs.push({ role: role, content: el.textContent });
        }
        var panel = document.querySelector('.ai-chat-panel');
        var isOpen = panel ? panel.classList.contains('open') : false;
        sessionStorage.setItem('__dev_reload_state', JSON.stringify({
            messages: msgs,
            isOpen: isOpen
        }));
    }

    function reloadJS() {
        saveState();

        // Remove old widget DOM
        var btn = document.querySelector('.ai-chat-btn');
        if (btn) { btn.remove(); }
        var panel = document.querySelector('.ai-chat-panel');
        if (panel) { panel.remove(); }

        // Remove old script tag
        var oldScript = document.querySelector('script[src*="ai-chat-widget.js"]');
        if (oldScript) { oldScript.remove(); }

        // Insert new script tag to re-fetch and re-execute
        var script = document.createElement('script');
        script.src = 'js/ai-chat-widget.js?_dr=' + Date.now();
        document.body.appendChild(script);
        log('JS reloaded');
    }

    function poll() {
        fetch(DEV_SERVER + '/version').then(function (res) {
            return res.json();
        }).then(function (data) {
            if (knownJs === null || knownCss === null) {
                // First poll — record baseline, don't trigger reload
                knownJs = data.js;
                knownCss = data.css;
                log('connected (js=' + data.js + ', css=' + data.css + ')');
                return;
            }

            if (data.css !== knownCss) {
                knownCss = data.css;
                reloadCSS();
            }
            if (data.js !== knownJs) {
                knownJs = data.js;
                reloadJS();
            }
        }).catch(function () {
            // Dev server not running — silently ignore
        });
    }

    setInterval(poll, POLL_INTERVAL);
    poll();
})();
