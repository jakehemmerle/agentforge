/**
 * Jest mock for `marked` (ESM-only package).
 *
 * Returns input wrapped in <p> tags to approximate real output
 * without needing ESM transform.
 */
function parse(text) {
    return '<p>' + text + '</p>';
}

function setOptions() {}

module.exports = { parse: parse, setOptions: setOptions };
