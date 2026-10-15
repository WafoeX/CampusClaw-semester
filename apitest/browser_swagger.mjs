// Optional real-browser supplement to the HTTP runner. No stored token, HAR, or trace.
import { chromium } from '../frontend/node_modules/@playwright/test/index.mjs';
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { createServer } from 'node:net';
import { spawn, execFileSync } from 'node:child_process';

const origin = 'http://127.0.0.1:18088';
// Docker Desktop may omit host bindings on internal-only networks. If needed,
// tunnel loopback TCP through docker exec to this isolated gateway; do not attach
// an egress network or expose the API/database. Forward no traffic elsewhere.
let bridge;
const connections = new Set();
try {
  await fetch(origin + '/health');
} catch {
  const label = execFileSync('docker', ['inspect', 'campusclaw-apitest-gateway-1', '--format', '{{index .Config.Labels "com.docker.compose.project"}}'], { encoding: 'utf8' }).trim();
  assert.equal(label, 'campusclaw-apitest');
  bridge = createServer(socket => {
    const child = spawn('docker', ['exec', '-i', 'campusclaw-apitest-gateway-1', 'nc', '127.0.0.1', '8080'], { stdio: ['pipe', 'pipe', 'ignore'] });
    connections.add(socket);
    socket.pipe(child.stdin);
    child.stdout.pipe(socket);
    child.on('error', () => socket.destroy());
    child.stdin.on('error', () => socket.destroy());
    socket.on('error', () => child.kill());
    socket.on('close', () => { connections.delete(socket); child.kill(); });
  });
  await new Promise((resolve, reject) => { bridge.once('error', reject); bridge.listen(18088, '127.0.0.1', resolve); });
}
const browser = await chromium.launch();
const context = await browser.newContext();
const page = await context.newPage();
const errors = [];
const external = [];
page.on('pageerror', () => errors.push('page_error'));
page.on('console', message => { if (message.type() === 'error') errors.push('console_error'); });
page.on('request', request => { if (!request.url().startsWith(origin + '/')) external.push('external_request'); });
let stage = 'load';
try {
  await page.goto(origin + '/api/docs');
  await page.locator('.swagger-ui .info').waitFor();
  // Tags are part of the generated contract; discover the operation by its stable ID.
  stage = 'login';
  const actualLogin = page.locator('[id$="-post_api_auth_login"]');
  assert.equal(await actualLogin.count(), 1);
  await actualLogin.locator('.opblock-summary').click();
  await actualLogin.getByRole('button', { name: 'Try it out' }).click();
  await actualLogin.locator('textarea').fill(JSON.stringify({ account: 'teacher.alpha', password: 'apitest-account-only' }));
  const loginResponse = page.waitForResponse(response => response.url() === origin + '/api/auth/login' && response.request().method() === 'POST');
  await actualLogin.getByRole('button', { name: 'Execute', exact: true }).click();
  const response = await loginResponse;
  assert.equal(response.status(), 200);
  const identity = await response.json();
  await actualLogin.locator('.opblock-summary').click();
  stage = 'authorize';
  await page.locator('.auth-wrapper').getByRole('button', { name: /Authorize/ }).click();
  stage = 'authorize_input';
  const dialog = page.locator('.dialog-ux');
  await dialog.locator('input').fill(identity.access_token);
  stage = 'authorize_submit';
  await dialog.locator('button.authorize').click();
  stage = 'authorize_close';
  await dialog.getByRole('button', { name: 'Close', exact: true }).last().click();
  stage = 'try_out';
  const me = page.locator('[id$="-get_api_auth_me"]');
  await me.locator('.opblock-summary').click();
  await me.getByRole('button', { name: 'Try it out' }).click();
  const meResponse = page.waitForResponse(response => response.url() === origin + '/api/auth/me' && response.request().method() === 'GET');
  await me.getByRole('button', { name: 'Execute', exact: true }).click();
  const authorized = await meResponse;
  assert.equal(authorized.status(), 200);
  const headers = await authorized.request().headersArray();
  const auth = headers.filter(header => header.name.toLowerCase() === 'authorization');
  assert.equal(auth.length, 1);
  assert.equal(auth[0].value, `Bearer ${identity.access_token}`);
  const value = await authorized.json();
  for (const key of ['user_id', 'account', 'role', 'class_id']) assert.equal(value[key], identity[key]);
  // Logout the UI and reload before capturing; response panels/curl snippets can contain tokens.
  stage = 'capture';
  await page.reload();
  await page.locator('.swagger-ui .info').waitFor();
  assert.equal(await page.locator('[id*="operations-"]').count() >= 30, true);
  assert.equal(errors.length, 0);
  assert.equal(external.length, 0);
  await mkdir('apitest/artifacts', { recursive: true });
  await page.screenshot({ path: 'apitest/artifacts/task9-swagger.png' });
  const result = { gateway: true, login_try_out: true, authorized_try_out: true, same_principal: true, bearer_header_count: 1, page_errors: errors.length, external_requests: external.length, loopback_docker_exec_bridge: Boolean(bridge) };
  await writeFile('apitest/artifacts/task9-browser.json', JSON.stringify(result, null, 2) + '\n');
  console.log('Swagger browser acceptance passed; one Bearer header, same principal, no external requests.');
} catch {
  console.error(`Swagger browser acceptance failed at ${stage} (content redacted).`);
  process.exitCode = 1;
} finally {
  await context.close();
  await browser.close();
  for (const socket of connections) socket.destroy();
  if (bridge) await new Promise(resolve => bridge.close(resolve));
}
