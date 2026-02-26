const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const SKIP = !process.env.INTEGRATION_TEST;

const repoRoot = path.resolve(__dirname, '..', '..', '..');
const submodulePath = path.join(repoRoot, 'openemr');
const customize = path.join(repoRoot, 'injectables', 'openemr-customize.sh');

const run = (cmd, opts = {}) =>
  execSync(cmd, { cwd: repoRoot, stdio: 'pipe', timeout: 300_000, ...opts }).toString();

const describeIf = SKIP ? describe.skip : describe;

describeIf('inject-overlay integration', () => {
  beforeAll(() => {
    if (!fs.existsSync(path.join(submodulePath, '.git'))) {
      throw new Error(
        'OpenEMR submodule not found. Run: git submodule update --init openemr'
      );
    }

    run(`${customize} clean`);
    run(`${customize} apply`);
    // Full install required: postinstall runs napa (fetches bootstrap-rtl etc.)
    // and gulp -i (copies deps into public/assets/) which the Sass build needs.
    run('npm install', { cwd: submodulePath });
  });

  afterAll(() => {
    run(`${customize} clean`);
  });

  test('widget JS and CSS exist at expected paths after injection', () => {
    const jsPath = path.join(
      submodulePath,
      'interface', 'main', 'tabs', 'js', 'ai-chat-widget.js'
    );
    const cssPath = path.join(
      submodulePath,
      'interface', 'main', 'tabs', 'css', 'ai-chat-widget.css'
    );

    expect(fs.existsSync(jsPath)).toBe(true);
    expect(fs.existsSync(cssPath)).toBe(true);

    // Sanity check: files are non-empty
    expect(fs.statSync(jsPath).size).toBeGreaterThan(0);
    expect(fs.statSync(cssPath).size).toBeGreaterThan(0);
  });

  test('OpenEMR gulp build succeeds after injection', () => {
    // npm run build runs gulp; a non-zero exit code throws automatically
    const output = run('npm run build', { cwd: submodulePath });
    expect(output).toBeDefined();
  });
});
