'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { resourceAllowed, isPublicAddress, buildHostRules } = require('./renderPublicPage.cjs');
const request = (url, method = 'GET', type = 'fetch') => ({url: () => url, method: () => method, resourceType: () => type});

test('browser allows only exact public resource hosts and observed read-only search POSTs', () => {
  assert.equal(resourceAllowed(request('https://web-jp-assets-v2.mercdn.net/_next/static/chunk.js', 'GET', 'script')), true);
  assert.equal(resourceAllowed(request('https://api.mercari.jp/v2/entities:search', 'POST')), true);
  for (const [url,method] of [
    ['https://internal.mercari.com/admin','POST'],
    ['https://api.mercari.jp/api?operation=createOrder','POST'],
    ['https://api.mercari.jp/v2/entities:search?operation=createOrder','POST'],
    ['https://jp.mercari.com/purchase/item','GET'],
    ['https://api.mercari.jp/v2/entities:search','DELETE'],
    ['https://127.0.0.1/admin','GET'],
    ['https://jp.mercari.com.evil.invalid/search','GET']]) {
    assert.equal(resourceAllowed(request(url,method)), false, url);
  }
});

test('private and reserved addresses never become browser DNS rules', async () => {
  for (const ip of ['127.0.0.1','10.1.2.3','169.254.169.254','172.16.1.1','192.168.1.1','100.64.0.1','::1','fc00::1','fe80::1','::ffff:127.0.0.1','2001:db8::1']) {
    assert.equal(isPublicAddress(ip), false, ip);
  }
  const mapped = await buildHostRules(async host => [{address:host === 'api.mercari.jp' ? '127.0.0.1' : '93.184.216.34',family:4}]);
  assert.equal(mapped.hosts.has('api.mercari.jp'), false);
  assert.match(mapped.rules, /MAP jp\.mercari\.com 93\.184\.216\.34/);
  assert.ok(mapped.rules.endsWith('MAP * ~NOTFOUND'));
  await assert.rejects(buildHostRules(async () => [{address:'127.0.0.1',family:4}]));
});

const { renderPublicPage } = require('./renderPublicPage.cjs');
const TARGET = 'https://jp.mercari.com/search?keyword=Pikachu+173%2F165';
const publicLookup = async () => [{ address: '93.184.216.34', family: 4 }];

function browserFixture({ gotoError, hangNavigation = false, bodyText = 'Public search',
  hrefs = ['https://jp.mercari.com/item/m123456'], resources = [], status = 200 } = {}) {
  const calls = { continued: [], aborted: [], closed: 0, launches: [], context: [] };
  const handlers = {};
  let routeHandler;
  const page = {
    on(event, handler) { handlers[event] = handler; },
    url() { return TARGET; },
    async goto() {
      if (gotoError) throw gotoError;
      if (hangNavigation) return new Promise(() => {});
      for (const req of resources) {
        await routeHandler({ request: () => req,
          continue: async () => { calls.continued.push(req.url()); },
          abort: async () => { calls.aborted.push(req.url()); handlers.requestfailed?.(); } });
      }
      handlers.response?.({ url: () => TARGET, status: () => status });
      return { status: () => status };
    },
    locator(selector) {
      return { first() { return this; }, async waitFor() {},
        async innerText() { return bodyText; },
        async evaluateAll(fn) { return fn(hrefs.map(href => ({ href }))); } };
    },
  };
  const browser = { async close() { calls.closed++; },
    async newContext(options) {
      calls.context.push(options);
      return { async route(_pattern, handler) { routeHandler = handler; }, async newPage() { return page; } };
    } };
  return { calls, chromium: { async launch(options) { calls.launches.push(options); return browser; } } };
}

test('DNS lookups start together; slow optional hosts expire without losing the target pin', async () => {
  const calls = [];
  const pending = buildHostRules(async host => {
    calls.push(host);
    return host === 'jp.mercari.com' ? [{ address: '93.184.216.34', family: 4 }] : new Promise(() => {});
  }, 20);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls.length, 6);
  const result = await pending;
  assert.deepEqual([...result.hosts], ['jp.mercari.com']);
  assert.equal(result.rules, 'MAP jp.mercari.com 93.184.216.34, MAP * ~NOTFOUND');
});

test('successful render emits only validated listing coordinates, sandbox and bounded safe diagnostics', async () => {
  const fake = browserFixture({ bodyText: 'public content secret-marker', hrefs: [
    'https://jp.mercari.com/item/m123456', 'https://jp.mercari.com/item/m123456',
    'https://jp.mercari.com/item/m123456?token=private-query', 'https://evil.invalid/item/m1'],
  resources: [request(TARGET), request('https://api.mercari.jp/private-token?secret=marker', 'POST')] });
  const result = await renderPublicPage(TARGET, 750000, { chromium: fake.chromium, lookup: publicLookup });
  assert.equal(result.status, 200);
  assert.equal(result.body, '<html><body><a href="https://jp.mercari.com/item/m123456">Listing</a></body></html>');
  assert.equal(result.url, TARGET);
  assert.equal(result.diagnostics.listing_links, 1);
  assert.equal(result.diagnostics.allowed_requests, 1);
  assert.equal(result.diagnostics.blocked_requests, 1);
  assert.equal(result.diagnostics.blocked_api_requests, 1);
  assert.equal(result.diagnostics.stage, 'complete');
  assert.equal(fake.calls.launches[0].chromiumSandbox, true);
  assert.deepEqual(fake.calls.context[0], { serviceWorkers: 'block', acceptDownloads: false });
  assert.equal(fake.calls.continued.length, 1);
  assert.equal(fake.calls.closed, 1);
  assert.doesNotMatch(JSON.stringify(result), /secret-marker|private-query|private-token/);
});

test('navigation timeouts and arbitrary failures are distinct, redacted and close the browser', async () => {
  for (const [name, code] of [['TimeoutError', 'browser_renderer_navigation_timeout'],
    ['Error', 'browser_renderer_navigation_failed']]) {
    const error = Error('private-token https://internal.invalid'); error.name = name;
    const fake = browserFixture({ gotoError: error });
    const result = await renderPublicPage(TARGET, 750000, { chromium: fake.chromium, lookup: publicLookup });
    assert.equal(result.error.code, code);
    assert.equal(result.diagnostics.stage, 'navigation');
    assert.equal(fake.calls.closed, 1);
    assert.doesNotMatch(JSON.stringify(result), /private-token|internal.invalid/);
  }
});

test('a public-source DNS failure cannot launch Chromium', async () => {
  let launches = 0;
  const result = await renderPublicPage(TARGET, 750000, {
    chromium: { async launch() { launches++; } }, lookup: async () => [{ address: '127.0.0.1', family: 4 }],
  });
  assert.equal(result.error.code, 'browser_renderer_dns_unavailable');
  assert.equal(result.diagnostics.stage, 'dns');
  assert.equal(launches, 0);
});

test('request cap stops network dispatch and a hung navigation meets the whole-operation deadline', async () => {
  const fake = browserFixture({ resources: [request(TARGET), request(TARGET), request(TARGET), request(TARGET)] });
  const result = await renderPublicPage(TARGET, 750000, { chromium: fake.chromium, lookup: publicLookup, maxRequests: 2 });
  assert.equal(result.error.code, 'browser_renderer_request_budget_exhausted');
  assert.equal(fake.calls.continued.length, 2);
  assert.equal(result.diagnostics.allowed_requests, 2);
  const hung = browserFixture({ hangNavigation: true });
  const timeout = await renderPublicPage(TARGET, 750000, { chromium: hung.chromium, lookup: publicLookup, deadlineMs: 25 });
  assert.equal(timeout.error.code, 'browser_renderer_deadline_exhausted');
  assert.equal(timeout.diagnostics.stage, 'navigation');
  assert.ok(hung.calls.closed >= 1);
});

test('access challenges, unavailable pages and empty hydrated search remain explicit failures', async () => {
  for (const [options, code] of [[{ bodyText: 'Verify you are human' }, 'browser_renderer_challenge'],
    [{ status: 403 }, 'browser_renderer_source_unavailable'], [{ hrefs: [] }, 'browser_renderer_no_listing_links']]) {
    const fake = browserFixture(options);
    const result = await renderPublicPage(TARGET, 750000, { chromium: fake.chromium, lookup: publicLookup });
    assert.equal(result.error.code, code);
    assert.equal(result.body, undefined);
  }
});

test('a late browser launch after deadline is closed without creating a context', async () => {
  const fake = browserFixture();
  const launch = fake.chromium.launch;
  fake.chromium.launch = async options => {
    await new Promise(resolve => setTimeout(resolve, 35));
    return launch(options);
  };
  const result = await renderPublicPage(TARGET, 750000, { chromium: fake.chromium, lookup: publicLookup, deadlineMs: 10 });
  assert.equal(result.error.code, 'browser_renderer_deadline_exhausted');
  assert.equal(result.diagnostics.stage, 'launch');
  await new Promise(resolve => setTimeout(resolve, 45));
  assert.equal(fake.calls.closed, 1);
  assert.equal(fake.calls.context.length, 0);
});

test('blocked subrequests have their own cap and navigation cannot silently follow a different page', async () => {
  const fake = browserFixture({ resources: Array.from({ length: 6 }, () => request('https://analytics.invalid/pixel')) });
  const result = await renderPublicPage(TARGET, 750000, { chromium: fake.chromium, lookup: publicLookup, maxRequests: 2 });
  assert.equal(result.error.code, 'browser_renderer_request_budget_exhausted');
  assert.equal(result.diagnostics.requests, 5);
  assert.equal(fake.calls.continued.length, 0);
  const redirected = request('https://jp.mercari.com/login', 'GET', 'document');
  redirected.isNavigationRequest = () => true;
  const nav = browserFixture({ resources: [redirected] });
  await renderPublicPage(TARGET, 750000, { chromium: nav.chromium, lookup: publicLookup });
  assert.equal(nav.calls.continued.length, 0);
  assert.deepEqual(nav.calls.aborted, ['https://jp.mercari.com/login']);
});
