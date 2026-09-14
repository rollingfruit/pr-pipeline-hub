import {test, expect, Page, TestInfo} from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import {randomBytes} from 'node:crypto';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';

const execFileAsync = promisify(execFile);

function settings() {
    if (!process.env.E2E_SETTINGS || !process.env.E2E_PRIVATE_DIR) throw new Error('Pipeline bootstrap required');
    const value = {...JSON.parse(fs.readFileSync(process.env.E2E_SETTINGS, 'utf8')),
        ...JSON.parse(fs.readFileSync(path.join(process.env.E2E_PRIVATE_DIR, 'bootstrap.json'), 'utf8'))};
    if (process.env.PIPELINE_FEATURE_RESILIENCE === 'true') value.E2E_RESILIENCE_ENABLED = true;
    return value;
}
async function json(page: Page, url: string, data?: unknown) {
    const headers = internalHeaders(url);
    if (url.startsWith('/api/v4/')) headers['X-Requested-With'] = 'XMLHttpRequest';
    const response = data === undefined ? await page.request.get(url, {headers}) : await page.request.post(url, {data, headers});
    expect(response.ok(), `${url}: HTTP ${response.status()}`).toBeTruthy();
    return response.json();
}
function internalHeaders(url: string): Record<string, string> {
    if (!url.startsWith('http://localhost:18684/') && !url.startsWith(multicaEndpoint('/'))) return {};
    const privateConfig = JSON.parse(fs.readFileSync(path.join(process.env.E2E_PRIVATE_DIR!, 'internal.json'), 'utf8'));
    return {'X-Auth-Token': privateConfig.token};
}
function multicaEndpoint(route: string) {
    return (process.env.E2E_MULTICA_URL || 'http://localhost:18080').replace(/\/$/, '') + route;
}
function edge(route: string) {
    const cfg = settings();
    return `/v1/agent/${route}?${new URLSearchParams({user_id: cfg.CONTROL_USER_ID || cfg.user_id, user_name: cfg.username})}`;
}
async function login(page: Page) {
    const current = await page.request.get('/api/v4/users/me');
    if (current.status() === 200) return;
    const cfg = settings();
    await page.goto('/login');
    const webChoice = page.getByRole('link', {name: /在浏览器查看|View in Browser/i});
    await page.locator('#input_loginId').or(webChoice).first().waitFor({state: 'visible'});
    if (await webChoice.isVisible()) await webChoice.click();
    await page.locator('#input_loginId').waitFor({state: 'visible'});
    const usernameTab = page.getByRole('tab', {name: /用户名登录|Username sign-in/i});
    if (await usernameTab.isVisible()) await usernameTab.click();
    await page.locator('#input_loginId').fill(cfg.TEST_ADMIN_USER);
    await page.locator('#input_password-input').fill(cfg.TEST_ADMIN_PASSWORD);
    await page.locator('button[type=submit]').click();
    await expect.poll(async () => (await page.request.get('/api/v4/users/me')).status()).toBe(200);
}
async function attach(info: TestInfo, value: unknown) {
    const file = info.outputPath('correlation.json');
    fs.writeFileSync(file, JSON.stringify(value, null, 2));
    await info.attach('correlation', {path: file, contentType: 'application/json'});
}
async function createBot(page: Page) {
    const cfg = settings();
    const name = 'e2e-' + randomBytes(5).toString('hex');
    await page.goto('/hw/agents-manage');
    await page.getByRole('button', {name: '添加Agent', exact: true}).click();
    await page.getByPlaceholder('请输入名称，示例：文档写作助手').fill(name);
    const provider = cfg.AGENT_PROVIDER || 'codex';
    if (!['codex', 'opencode'].includes(provider)) throw new Error('Unsupported E2E Agent provider');
    await page.getByPlaceholder('请输入简单描述，示例：一键生成、润色各类文稿，高效辅助办公与学习写作的智能工具').fill(`Isolated real ${provider} E2E`);
    await page.getByRole('tab', {name: '本地Agent', exact: true}).click();
    const scan = page.getByRole('button', {name: '已安装 Daemon，开始扫描', exact: true});
    if (await scan.isVisible()) await scan.click();
    const providerButton = page.locator('.agents-manage-create__provider-grid--local button').filter({hasText: new RegExp(provider, 'i')}).first();
    await providerButton.click();
    await expect(providerButton).toHaveClass(/\bactive\b/);
    const pending = page.waitForResponse(r => r.url().includes('/managed-platforms/agents') && r.request().method() === 'POST');
    await page.getByRole('button', {name: '确定', exact: true}).click();
    const response = await pending;
    expect(response.ok()).toBeTruthy();
    const bot = await response.json();
    expect(bot.bot_id).toBeTruthy();
    const user = await json(page, `/api/v4/users/${bot.bot_id}`);
    expect(user.is_bot).toBe(true);
    await json(page, `/api/v4/teams/${cfg.team_id}/members`, {team_id: cfg.team_id, user_id: bot.bot_id});
    await page.reload();
    await expect(page.getByText(name, {exact: true}).first()).toBeVisible();
    const managed = await json(page, edge('managed-platforms'));
    const created = (managed.agents || []).find((item: any) => item.bot_id === bot.bot_id);
    expect(created, 'Created bot must have its own durable control-plane binding').toBeTruthy();
    expect(created.managed_runtime_id).toBe(cfg.RUNTIME_ID);
    expect(created.managed_daemon_id).toBe(cfg.DAEMON_ID);
    expect(created.managed_workspace_id).toBe(cfg.WORKSPACE_ID);
    return {...bot, name, control: created};
}
async function conversation(page: Page, bot: any, group = false) {
    const cfg = settings();
    if (!group) {
        const channel = await json(page, '/api/v4/channels/direct', [cfg.user_id, bot.bot_id]);
        await page.goto(`/hw/channels/${channel.name}`);
        return channel;
    }
    const channel = await json(page, '/api/v4/channels', {team_id: cfg.team_id, name: 'e2e-' + randomBytes(5).toString('hex'), display_name: 'PR E2E', type: 'O'});
    await json(page, `/api/v4/channels/${channel.id}/members`, {user_id: bot.bot_id});
    await page.goto(`/hw/channels/${channel.name}`);
    return channel;
}
async function send(page: Page, text: string, mention?: string) {
    const input = page.getByTestId('post_textbox');
    if (mention) {
        await input.fill('');
        await input.pressSequentially('@' + mention);
        await page.getByRole('option').filter({hasText: mention}).first().click();
        await input.press('End');
        await input.pressSequentially(' ' + text);
    } else await input.fill(text);
    const pending = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v4/posts' && r.request().method() === 'POST');
    await page.getByTestId('SendMessageButton').click();
    const response = await pending;
    if (!response.ok()) {
        const body = await response.json().catch(() => ({}));
        await attach(test.info(), {kind:'message-http-failure', status:response.status(),
            error_id:body.id, message:body.message});
    }
    expect(response.ok(), `Browser message submission: HTTP ${response.status()}`).toBeTruthy();
    return response.json();
}
async function replies(page: Page, channel: any, source: any, bot: any) {
    const all = await json(page, `/api/v4/channels/${channel.id}/posts`);
    return Object.values(all.posts).filter((p: any) => p.user_id === bot.bot_id && p.props?.source_post_id === source.id) as any[];
}
async function execution(page: Page, channel: any, source: any, bot: any, expected: string, toolPhase: 'completed' | 'failed' = 'completed') {
    let run: any, anchor: any;
    await expect.poll(async () => {
        anchor = (await replies(page, channel, source, bot)).find(p => p.props.agent_run_id &&
            ['anchor', 'final'].includes(p.props.agent_run_companion_kind));
        if (!anchor) return '';
        run = await json(page, edge(`agent-runs/${anchor.props.agent_run_id}`));
        return ['completed', 'failed', 'blocked', 'cancelled'].includes(run.status);
    }, {timeout: 300_000, intervals: [2000]}).toBe(true);
    await attach(test.info(), {run: run.id || anchor.props.agent_run_id, status: run.status,
        source_message: source.id, failure: run.failure, error: run.error});
    expect(run.status, 'Real Agent execution must complete, not merely acknowledge the message').toBe('completed');
    expect(run.task_id).toBeTruthy();
    expect(run.source_post_id).toBe(source.id);
    expect(run.channel_id).toBe(channel.id);
    expect(run.bot_id).toBe(bot.bot_id);
    // The production activity classifier projects read/cat tools as file events.
    expect((run.events || []).some((e: any) => (toolPhase === 'failed' ? ['command', 'tool'] : ['command', 'tool', 'file']).includes(e.kind) &&
        e.task_id === run.task_id && e.run_id === run.run_id && e.phase === toolPhase),
    `Expected a correlated ${toolPhase} tool execution`).toBeTruthy();
    const [expectedLabel, expectedValue] = expected.split('：', 2);
    const runText = JSON.stringify(run);
    expect(runText).toContain(expectedLabel);
    expect(runText).toContain(expectedValue);
    await expect(page.getByText(expectedValue, {exact: false}).first()).toBeVisible();
    await expect.poll(async () => (await replies(page, channel, source, bot)).filter(
        p => p.props.agent_run_companion_kind === 'final').length).toBe(1);
    await page.waitForTimeout(5000);
    const finals = (await replies(page, channel, source, bot)).filter(p => p.props.agent_run_companion_kind === 'final');
    expect(finals).toHaveLength(1);
    expect(finals[0].id).toBe(run.final_response.delivery_post_id);
    expect(finals[0].message).toContain(expectedLabel);
    expect(finals[0].message).toContain(expectedValue);
    expect(finals[0].props.trace_id).toBeTruthy();
    return {source_message: source.id, channel: channel.id, run: anchor.props.agent_run_id, task: run.task_id,
        trace: finals[0].props.trace_id, final_post: finals[0].id, url: page.url()};
}

async function activeRun(page: Page, channel: any, source: any, bot: any) {
    let anchor: any;
    await expect.poll(async () => {
        anchor = (await replies(page, channel, source, bot)).find(p => p.props.agent_run_id &&
            ['anchor', 'final'].includes(p.props.agent_run_companion_kind));
        return anchor?.props?.agent_run_id || '';
    }, {timeout: 180_000, intervals: [1000, 2000]}).not.toBe('');
    const run = await json(page, edge(`agent-runs/${anchor.props.agent_run_id}`));
    return {anchor, run};
}

async function fault(action: 'stop' | 'crash' | 'recover' | 'status') {
    const script = process.env.E2E_FAULT_CONTROL;
    if (!script) throw new Error('E2E_FAULT_CONTROL is not configured by the trusted runner');
    const {stdout} = await execFileAsync(process.env.E2E_PYTHON || 'python3', [script, action], {
        env: process.env, timeout: 180_000, maxBuffer: 1024 * 1024,
    });
    return JSON.parse(stdout.trim().split('\n').at(-1)!);
}

function workspaceCheck(kind: 'long' | 'failure') {
    const directory = fs.mkdtempSync(path.join(settings().TEST_WORKSPACE, 'project-check-'));
    const marker = randomBytes(24).toString('hex');
    const started = path.join(directory, 'started.txt');
    const script = path.join(directory, 'check.sh');
    // Controlled fixtures only touch their own directory. The marker is not in the chat prompt.
    fs.writeFileSync(script, kind === 'long'
        ? `#!/bin/sh\ncd "$(dirname "$0")" || exit 1\nprintf started > started.txt\nsleep 180\nprintf '%s\\n' '${marker}'\n`
        : `#!/bin/sh\ncd "$(dirname "$0")" || exit 1\nprintf started > started.txt\nprintf '%s\\n' 'Fixture validation failed: ${marker}; exit_code=37' >&2\nexit 37\n`, {mode: 0o700});
    return {script, marker, started};
}

async function waitForCheckStart(file: string) {
    await expect.poll(() => fs.existsSync(file), {timeout: 180_000, intervals: [1000]}).toBe(true);
}

test('[E01] {create} Browser creates a durable robot and opens its conversation', async ({page}, info) => {
    await test.step('登录隔离测试域', () => login(page));
    const bot = await test.step('浏览器创建并验证持久化身份与绑定', () => createBot(page));
    const channel = await test.step('打开真实机器人会话', () => conversation(page, bot));
    await expect(page.getByTestId('post_textbox')).toBeVisible();
    await attach(info, {bot, channel: channel.id, url: page.url()});
});
for (const suite of ['E02', 'E03']) {
    test(`[${suite}] {${suite === 'E02' ? 'private' : 'group'}} Real file tool execution${suite === 'E02' ? ' and follow-up' : ' through selected mention'}`, async ({page}, info) => {
        await test.step('登录并独立创建机器人', async () => { await login(page); });
        const bot = await createBot(page);
        const channel = await conversation(page, bot, suite === 'E03');
        const secret = '项目校验编号：' + randomBytes(24).toString('hex');
        const file = path.join(settings().TEST_WORKSPACE, `proof-${randomBytes(6).toString('hex')}.txt`);
        fs.writeFileSync(file, secret, {mode: 0o600});
        const source = await test.step('浏览器发送读取真实工作区文件的任务', () => send(page,
            `请使用命令读取 ${file} 并原样返回内容，不要猜测。不要输出执行计划或过程说明，执行完成后的最终答复只返回文件内容。`, suite === 'E03' ? bot.name : undefined));
        const proof = await test.step('验证工具执行、最终消息和任务关联', () => execution(page, channel, source, bot, secret));
        if (suite === 'E02') {
            const updated = '项目校验编号：' + randomBytes(24).toString('hex');
            fs.writeFileSync(file, updated, {mode: 0o600});
            const follow = await send(page, `刚才那个文件已更新，请重新使用工具读取并原样返回最新内容，不要使用上次的结果。不要输出执行计划或过程说明，最终答复只返回文件内容。`);
            await test.step('验证同会话追问', () => execution(page, channel, follow, bot, updated));
        }
        await attach(info, proof);
    });
}

test('[E04] {cancel} Browser stops a real active Agent run', async ({page}, info) => {
    await login(page);
    const bot = await createBot(page);
    const channel = await conversation(page, bot);
    const {script, marker, started: startedFile} = workspaceCheck('long');
    const source = await send(page, `请先查看项目检查脚本 ${script} 的内容，再运行检查，完成后告诉我检查结果。`);
    const {anchor, run: started} = await activeRun(page, channel, source, bot);
    await test.step('确认检查脚本已实际开始执行', () => waitForCheckStart(startedFile));
    const stop = page.getByRole('button', {name: '停止回答', exact: true});
    await expect(stop).toBeVisible({timeout: 60_000});
    const cancelPath = `/agent-runs/${anchor.props.agent_run_id}/cancel`;
    const cancelResponse = page.waitForResponse(r => new URL(r.url()).pathname.endsWith(cancelPath) && r.request().method() === 'POST');
    await stop.click();
    expect((await cancelResponse).ok()).toBeTruthy();
    let terminal: any;
    await expect.poll(async () => {
        terminal = await json(page, edge(`agent-runs/${anchor.props.agent_run_id}`));
        return terminal.status;
    }, {timeout: 180_000, intervals: [1000, 2000]}).toBe('cancelled');
    await expect(page.getByText(/已停止回答|已停止/).first()).toBeVisible();
    const duplicate = await page.request.post(multicaEndpoint(`/v1/agent/im-integrations/agent-runs/${anchor.props.agent_run_id}/actions/cancel`), {
        headers: internalHeaders(multicaEndpoint('/')), data: {actor_user_id: settings().CONTROL_USER_ID || settings().user_id},
    });
    expect([200, 409]).toContain(duplicate.status());
    await page.waitForTimeout(5000);
    const finals = (await replies(page, channel, source, bot)).filter(p => p.props.agent_run_companion_kind === 'final');
    expect(finals.filter(p => p.message.includes(marker))).toHaveLength(0);
    await attach(info, {source_message: source.id, channel: channel.id, run: anchor.props.agent_run_id,
        task: started.task_id, expected_terminal_status: 'cancelled', duplicate_cancel_status: duplicate.status(), url: page.url()});
});

test('[E05] {tool-failure} Failed command is preserved and explained to the user', async ({page}, info) => {
    await login(page);
    const bot = await createBot(page);
    const channel = await conversation(page, bot);
    const {script, marker, started: startedFile} = workspaceCheck('failure');
    const source = await send(page, `请运行项目检查脚本 ${script}，告诉我检查结果、退出码和错误详情。`);
    const proof = await execution(page, channel, source, bot, marker, 'failed');
    await waitForCheckStart(startedFile);
    const run = await json(page, edge(`agent-runs/${proof.run}`));
    const serialized = JSON.stringify(run);
    expect(serialized).toContain(marker);
    expect(run.final_response.markdown).toMatch(/\b37\b/);
    await attach(info, {...proof, fault_injection: {kind: 'tool-command', marker, exit_code: 37},
        expected_terminal_status: 'completed'});
});

test('[E05] {terminal-failure} Dedicated Daemon crash becomes visible and recovers', async ({page}, info) => {
    test.skip(settings().E2E_RESILIENCE_ENABLED !== true, 'Dedicated resilience control is not configured');
    await login(page);
    const bot = await createBot(page);
    const channel = await conversation(page, bot);
    const {script, started: startedFile} = workspaceCheck('long');
    const source = await send(page, `请先查看项目检查脚本 ${script} 的内容，再运行检查，完成后告诉我检查结果。`);
    const {anchor, run: started} = await activeRun(page, channel, source, bot);
    await test.step('确认检查脚本已实际开始执行', () => waitForCheckStart(startedFile));
    let injected: any, recovery: any, terminal: any;
    let failureError: unknown, recoveryError: unknown;
    try {
        injected = await fault('crash');
        expect(injected).toMatchObject({status: 'stopped', fault: 'process-crash'});
        // Server liveness detection is 150s + a 30s sweep, followed by message projection.
        const timeout = Number(settings().E2E_FAILURE_TIMEOUT_SECONDS || 240) * 1000;
        await expect.poll(async () => {
            terminal = await json(page, edge(`agent-runs/${anchor.props.agent_run_id}`));
            return terminal.status;
        }, {timeout, intervals: [2000, 5000]}).toBe('failed');
        await expect(page.getByText(/未完成|失败|不可用/).first()).toBeVisible();
    } catch (error) {
        failureError = error;
    } finally {
        try { recovery = await fault('recover'); } catch (error) { recoveryError = error; }
        await attach(info, {source_message: source.id, channel: channel.id, run: anchor.props.agent_run_id,
            task: started.task_id, fault_injection: injected, recovery,
            observed_status: terminal?.status, failure: terminal?.failure || terminal?.error,
            assertion_error: failureError ? String(failureError) : null,
            recovery_error: recoveryError ? String(recoveryError) : null, url: page.url()});
    }
    if (failureError) throw failureError;
    if (recoveryError) throw recoveryError;
    expect(recovery).toMatchObject({status: 'running', readiness: 'passed'});
    await attach(info, {source_message: source.id, channel: channel.id, run: anchor.props.agent_run_id,
        task: started.task_id, fault_injection: injected, recovery,
        expected_terminal_status: 'failed', failure: terminal?.failure || terminal?.error, url: page.url()});
});

test('[E06] {event-replay} Browser message remains single after native Job idempotency replay', async ({page}, info) => {
    await login(page);
    const bot = await createBot(page);
    const channel = await conversation(page, bot);
    const marker = '项目校验编号：' + randomBytes(24).toString('hex');
    const file = path.join(settings().TEST_WORKSPACE, `proof-${randomBytes(6).toString('hex')}.txt`);
    fs.writeFileSync(file, marker, {mode: 0o600});
    const source = await send(page, `请使用命令读取 ${file} 并原样返回内容，不要猜测。不要输出执行计划或过程说明，执行完成后的最终答复只返回文件内容。`);
    const {anchor, run: started} = await activeRun(page, channel, source, bot);
    const job = await json(page, multicaEndpoint(`/v1/agent/jobs/${started.task_id}`));
    expect(job.job_id).toBe(started.task_id);
    // Schedule's direct_job uses the real source event ID as the Job idempotency key.
    // This is a hybrid API-boundary check, not a replay of the complete gateway envelope.
    const payload = {agent_id: job.agent_id, prompt: source.message, idempotency_key: source.id};
    const endpoint = multicaEndpoint('/v1/agent/jobs');
    const replayResponses = await Promise.all([0, 1].map(() => page.request.post(endpoint, {
        headers: internalHeaders(endpoint), data: payload,
    })));
    for (const response of replayResponses) expect(response.ok()).toBeTruthy();
    const replayBodies = await Promise.all(replayResponses.map(r => r.json()));
    await attach(info, {kind: 'hybrid-browser-native-job-idempotency', source_message: source.id,
        channel: channel.id, run: anchor.props.agent_run_id, task: started.task_id, replay_responses: replayBodies});
    for (const body of replayBodies) expect(body.job_id).toBe(started.task_id);
    let terminal: any;
    await expect.poll(async () => {
        terminal = await json(page, edge(`agent-runs/${anchor.props.agent_run_id}`));
        return ['completed', 'failed', 'cancelled', 'blocked'].includes(terminal.status);
    }, {timeout: 300_000, intervals: [2000]}).toBe(true);
    expect(terminal.status, 'Idempotency cannot hide a failed original Agent task').toBe('completed');
    await page.waitForTimeout(5000);
    const related = await replies(page, channel, source, bot);
    expect(related.filter(p => p.props.agent_run_companion_kind === 'final')).toHaveLength(1);
    const finalMessage = related.find(p => p.props.agent_run_companion_kind === 'final').message;
    const [markerLabel, markerValue] = marker.split('：', 2);
    expect(finalMessage).toContain(markerLabel);
    expect(finalMessage).toContain(markerValue);
    await attach(info, {kind: 'hybrid-browser-native-job-idempotency', source_message: source.id,
        channel: channel.id, run: anchor.props.agent_run_id, task: started.task_id,
        duplicate_count: replayBodies.filter(body => body.job_id === started.task_id).length,
        replay_responses: replayBodies, url: page.url()});
});
for (const item of [{id: 'rule', prompt: '你好', decision: 'rule', answer: 'deterministic'},
    {id: 'model', prompt: '请用一句话解释 TCP 三次握手的目的，只需要静态知识回答。', decision: 'model', answer: 'model'}]) {
    test(`[DR] {${item.id}} Real ${item.id} direct answer without an execution task`, async ({page}, info) => {
        await login(page);
        const bot = await createBot(page);
        const channel = await conversation(page, bot);
        const source = await test.step('浏览器触发真实直答链路', () => send(page, item.prompt));
        let result: any[] = [];
        await expect.poll(async () => {
            result = await replies(page, channel, source, bot);
            return result.filter(p => p.props.agent_direct_reply === true).length;
        }, {timeout: 180_000}).toBe(1);
        // Observe late duplicate/Ack delivery, not only the first response.
        await page.waitForTimeout(5000);
        result = await replies(page, channel, source, bot);
        expect(result).toHaveLength(1);
        expect(result[0].props).toMatchObject({agent_direct_reply: true,
            agent_direct_reply_decision_source: item.decision, agent_direct_reply_answer_source: item.answer,
            agent_reply_type: 'final'});
        expect(result[0].props.agent_run_id).toBeFalsy();
        expect(result[0].props.agent_task_id).toBeFalsy();
        const tasks = await json(page, `http://localhost:18080/v1/agent/im-integrations/post-tasks?post_id=${source.id}&channel_id=${channel.id}`);
        expect(tasks.tasks).toEqual([]);
        await expect(page.getByText(result[0].message, {exact: false}).first()).toBeVisible();
        await attach(info, {source_message: source.id, reply: result[0], url: page.url(), kind: 'direct-reply'});
    });
}

test('[DR-contract] {contract} Integration: concurrent owners, sources and grapheme boundaries', async ({page}, info) => {
    await login(page);
    const bot = await createBot(page);
    const other = await createBot(page);
    const channel = await conversation(page, bot, true);
    await json(page, `/api/v4/channels/${channel.id}/members`, {user_id: other.bot_id});
    const cfg = settings();
    const make = async (text: string) => {
        // Fixture creation through API is intentional: this suite is integration, not browser E2E.
        const source = await json(page, '/api/v4/posts', {channel_id: channel.id, message: 'contract fixture ' + randomBytes(8).toString('hex')});
        return {source_event_id: 'e2e-' + randomBytes(16).toString('hex'), source_post_id: source.id,
            trace_id: 'e2e-' + randomBytes(16).toString('hex'), channel_id: channel.id, actor_user_id: cfg.user_id,
            reply_owner_agent_id: bot.bot_id, kind: 'general_qa', text, language: 'zh',
            decision_source: 'model', answer_source: 'model',
            destination: {bot_user_id: bot.bot_id, bot_username: bot.bot_username, team_id: cfg.team_id,
                group_id: channel.id, conversation_type: 'group'}};
    };
    const endpoint = 'http://localhost:18684/v1/agent';
    const payload = await make('并发幂等验证');
    const responses = await test.step('同事件并发、重复及不同 owner', async () => {
        const values = await Promise.all(Array.from({length: 6}, (_, index) => page.request.post(`${endpoint}/direct-replies`, {
            headers: internalHeaders(endpoint + '/'), data: {...payload, reply_owner_agent_id: index % 2 ? other.bot_id : bot.bot_id}})));
        for (const response of values) expect(response.ok()).toBeTruthy();
        return Promise.all(values.map(r => r.json()));
    });
    expect(new Set(responses.map(r => r.reply_id)).size).toBe(1);
    const replyID = responses[0].reply_id;
    expect(replyID).toBeTruthy();
    const durable = await json(page, `${endpoint}/governance-runs/${replyID}`);
    expect(JSON.stringify(durable)).toContain(payload.source_post_id);
    const delivered = async (sourceID: string) => {
        const data = await json(page, `/api/v4/channels/${channel.id}/posts`);
        return Object.values(data.posts).filter((p: any) => p.props?.source_post_id === sourceID && p.props?.agent_direct_reply === true) as any[];
    };
    await expect.poll(async () => (await delivered(payload.source_post_id)).length, {timeout: 60_000}).toBe(1);
    await page.waitForTimeout(5000);
    expect(await delivered(payload.source_post_id)).toHaveLength(1);
    await expect(page.getByText(payload.text, {exact: false}).first()).toBeVisible();
    await test.step('非法来源及 501 字素拒绝且不产生消息', async () => {
        for (const fields of [{decision_source: 'invalid'}, {answer_source: 'invalid'},
            {decision_source: 'rule', answer_source: 'model'}, {text: 'e\u0301'.repeat(501)}]) {
            const body = {...await make('invalid'), ...fields};
            const response = await page.request.post(`${endpoint}/direct-replies`, {data: body, headers: internalHeaders(endpoint + '/')});
            expect(response.status()).toBe(400);
            expect(await delivered(body.source_post_id)).toHaveLength(0);
        }
    });
    const boundary = await make('e\u0301'.repeat(500));
    const accepted = await json(page, `${endpoint}/direct-replies`, boundary);
    expect(accepted.reply_id).toBeTruthy();
    await expect.poll(async () => (await delivered(boundary.source_post_id)).length, {timeout: 60_000}).toBe(1);
    expect((await delivered(boundary.source_post_id))[0].message).toBe(boundary.text);
    await attach(info, {kind: 'integration', replyID, source: payload.source_post_id, durable,
        boundary_reply: accepted.reply_id, url: page.url()});
});
