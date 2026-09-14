import {defineConfig} from '@playwright/test';
import path from 'node:path';

const suite = process.env.E2E_SUITE;
if (!suite || !['E01', 'E02', 'E03', 'E04', 'E05', 'E06', 'DR', 'DR-contract'].includes(suite)) {
    throw new Error('E2E_SUITE must select one registered suite');
}
const output = process.env.E2E_OUTPUT || path.resolve('results', suite);
export default defineConfig({
    testDir: '.', testMatch: 'chains.spec.ts', grep: new RegExp(`^.*\\[${suite}\\]`),
    timeout: 600_000, expect: {timeout: 30_000}, workers: 1, retries: 0,
    forbidOnly: true, fullyParallel: false, outputDir: path.join(output, 'test-results'),
    reporter: [['list'], ['./reporter.ts'], ['html', {outputFolder: path.join(output, 'html'), open: 'never'}]],
    use: {browserName: 'chromium', baseURL: process.env.E2E_APP_URL || 'http://localhost:18066',
        storageState: process.env.E2E_AUTH_STATE || undefined,
        actionTimeout: 30_000, navigationTimeout: 60_000,
        trace: 'on', video: 'on', screenshot: 'on', viewport: {width: 1440, height: 1000}},
});
