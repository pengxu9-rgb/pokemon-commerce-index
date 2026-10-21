'use strict';

// Optional, operator-installed Playwright runtime. No downloads, account cookies,
// hidden endpoint calls, or CAPTCHA solving are performed by this transport.
const dns = require('node:dns/promises');
const net = require('node:net');
const { performance } = require('node:perf_hooks');
const RESOURCE_HOSTS = new Set(['jp.mercari.com', 'api.mercari.jp',
  'web-jp-assets-v2.mercdn.net', 'web-jp-assets.mercdn.net', 'static.mercdn.net', 'static.jp.mercari.com']);

function targetUrl(value) {
  const u = new URL(value);
  if (u.protocol !== 'https:' || u.hostname !== 'jp.mercari.com' || u.port ||
      u.username || u.password || u.hash || u.pathname !== '/search' ||
      [...u.searchParams.keys()].some(k => k !== 'keyword') ||
      !u.searchParams.get('keyword') || value.length > 2048) throw Error('unsafe_url');
  return u.href;
}

function resourceAllowed(request, pinnedHosts = RESOURCE_HOSTS) {
  let u;
  try { u = new URL(request.url()); } catch { return false; }
  if (u.protocol !== 'https:' || u.username || u.password || u.port) return false;
  if (!['GET', 'POST'].includes(request.method())) return false;
  if (['image', 'media', 'font'].includes(request.resourceType())) return false;
  const h = u.hostname;
  if (!pinnedHosts.has(h)) return false;
  if (/\/(?:purchase|checkout|cart|payment|transactions?|orders?|sell)(?:\/|$)/i.test(u.pathname)) return false;
  if (h === 'api.mercari.jp') {
    // These are the read-only requests made by the public search UI itself.
    // No application code constructs an API call or copies browser credentials.
    if (request.method() === 'POST') return ['/v2/entities:search', '/v2/facets:suggest'].includes(u.pathname) && !u.search;
    return /^\/(?:master\/v2\/datasets\/|services\/master\/v1\/)/.test(u.pathname) ||
      u.pathname === '/v2/getCurrencyConversionRate/country';
  }
  return request.method() === 'GET';
}

function isPublicAddress(address) {
  if (net.isIPv4(address)) {
    const [a,b,c] = address.split('.').map(Number);
    return !(a === 0 || a === 10 || a === 127 || a >= 224 ||
      (a === 100 && b >= 64 && b <= 127) || (a === 169 && b === 254) ||
      (a === 172 && b >= 16 && b <= 31) || (a === 192 && (b === 168 || b === 0 || (b === 88 && c === 99))) ||
      (a === 198 && (b === 18 || b === 19 || (b === 51 && c === 100))) || (a === 203 && b === 0 && c === 113));
  }
  return net.isIPv6(address) && /^[23][0-9a-f]{3}:/i.test(address) && !/^2001:db8:/i.test(address);
}

function bounded(promise, milliseconds, code) {
  let timer;
  return Promise.race([promise, new Promise((_, reject) => {
    timer = setTimeout(() => reject(Error(code)), milliseconds);
  })]).finally(() => clearTimeout(timer));
}

async function buildHostRules(lookup = dns.lookup, timeoutMs = 2000) {
  // A slow optional asset host must not serially consume the render deadline.
  // Every host still needs a checked public address before Chrome may use it.
  const resolved = await Promise.all([...RESOURCE_HOSTS].map(async host => {
    try {
      const addresses = await bounded(Promise.resolve().then(() => lookup(host, { all: true })),
        timeoutMs, 'browser_renderer_dns_unavailable');
      if (!Array.isArray(addresses) || !addresses.length ||
          addresses.some(a => !a || !isPublicAddress(a.address))) return null;
      const chosen = addresses.find(a => net.isIPv4(a.address));
      return chosen ? [host, chosen.address] : null;
    } catch { return null; }
  }));
  const entries = resolved.filter(Boolean);
  const hosts = new Set(entries.map(([host]) => host));
  if (!hosts.has('jp.mercari.com')) throw Error('browser_renderer_dns_unavailable');
  return { hosts, rules: entries.map(([host, address]) => `MAP ${host} ${address}`)
    .concat('MAP * ~NOTFOUND').join(', ') };
}

function launchOptions(env = process.env) {
  return { ...(env.POKEMON_PUBLIC_BROWSER_BUNDLED === '1' ? {} : { channel: 'chrome' }),
    headless: true, chromiumSandbox: true };
}

const ERROR_CODES = new Set([
  'browser_renderer_dns_unavailable', 'browser_renderer_navigation_timeout',
  'browser_renderer_navigation_failed', 'browser_renderer_source_unavailable',
  'browser_renderer_challenge', 'browser_renderer_no_listing_links',
  'browser_renderer_request_budget_exhausted', 'browser_renderer_deadline_exhausted',
  'browser_renderer_response_too_large', 'browser_renderer_failed',
]);

async function renderPublicPage(value, maxBytes, {
  chromium, lookup = dns.lookup, now = () => performance.now(),
  deadlineMs = 20000, dnsTimeoutMs = 2000, maxRequests = 64,
} = {}) {
  const started = now();
  const diagnostics = { schema: 'pokemon.public-browser-diagnostics.v1', stage: 'validation',
    elapsed_ms: 0, requests: 0, allowed_requests: 0, blocked_requests: 0,
    failed_requests: 0, responses: 0, pinned_hosts: 0, listing_links: 0,
    search_status: null, search_api_status: null, blocked_api_requests: 0 };
  let browser, timer, stopped = false, failure, rejectStop;
  const stopPromise = new Promise((_, reject) => { rejectStop = reject; });
  const stop = code => {
    if (stopped) return;
    stopped = true;
    failure = Error(code);
    rejectStop(failure);
    if (browser) browser.close().catch(() => {});
  };
  const remaining = ceiling => {
    if (stopped) throw failure;
    const budget = Math.floor(deadlineMs - (now() - started));
    if (budget <= 0) throw Error('browser_renderer_deadline_exhausted');
    return Math.max(1, Math.min(ceiling, budget));
  };
  const work = async () => {
    const target = targetUrl(value);
    if (!Number.isInteger(maxBytes) || maxBytes < 1024 || maxBytes > 1_000_000) throw Error('invalid_bound');
    diagnostics.stage = 'dns';
    const pinned = await buildHostRules(lookup, Math.min(dnsTimeoutMs, remaining(dnsTimeoutMs)));
    diagnostics.pinned_hosts = pinned.hosts.size;
    diagnostics.stage = 'launch';
    browser = await chromium.launch({ ...launchOptions(), timeout: remaining(5000),
      args: [`--host-resolver-rules=${pinned.rules}`] });
    // A launch finishing after the whole-operation timer still owns a process.
    // Close it before the abandoned work promise can proceed to a context.
    if (stopped) {
      try { await bounded(browser.close(), 500, 'close_timeout'); } catch {}
      throw failure;
    }
    remaining(1);
    const context = await browser.newContext({ serviceWorkers: 'block', acceptDownloads: false });
    await context.route('**/*', route => {
      const request = route.request();
      if (stopped) return route.abort();
      diagnostics.requests++;
      // Include denied requests in a second cap so a page cannot create an
      // unlimited stream of blocked media or analytics requests either.
      if (diagnostics.requests > maxRequests * 2) {
        stop('browser_renderer_request_budget_exhausted');
        return route.abort();
      }
      if (!resourceAllowed(request, pinned.hosts) ||
          (request.isNavigationRequest?.() && request.url() !== target)) {
        diagnostics.blocked_requests++;
        try { if (new URL(request.url()).hostname === 'api.mercari.jp') diagnostics.blocked_api_requests++; } catch {}
        return route.abort();
      }
      if (diagnostics.allowed_requests >= maxRequests) {
        stop('browser_renderer_request_budget_exhausted');
        return route.abort();
      }
      diagnostics.allowed_requests++;
      return route.continue();
    });
    const page = await context.newPage();
    page.on('requestfailed', () => { if (!stopped) diagnostics.failed_requests++; });
    page.on('response', response => {
      if (stopped) return;
      diagnostics.responses++;
      try {
        const u = new URL(response.url());
        if (u.hostname === 'api.mercari.jp' && u.pathname === '/v2/entities:search') {
          diagnostics.search_api_status = response.status();
        }
      } catch {}
    });
    diagnostics.stage = 'navigation';
    let response;
    try {
      response = await page.goto(target, { waitUntil: 'domcontentloaded', timeout: remaining(12000) });
    } catch (error) {
      if (stopped) throw failure;
      throw Error(error && error.name === 'TimeoutError'
        ? 'browser_renderer_navigation_timeout' : 'browser_renderer_navigation_failed');
    }
    diagnostics.search_status = response ? response.status() : null;
    if (!response || response.status() !== 200 || page.url() !== target) throw Error('browser_renderer_source_unavailable');
    diagnostics.stage = 'hydration';
    // Only public page rendering; do not click login, purchase or challenge UI.
    try { await page.locator('a[href*="/item/m"]').first().waitFor({ timeout: remaining(5000) }); } catch (error) {
      if (stopped) throw failure;
      if (!error || error.name !== 'TimeoutError') throw Error('browser_renderer_failed');
    }
    remaining(1);
    diagnostics.stage = 'inspection';
    const text = await page.locator('body').innerText({ timeout: remaining(1000) });
    if (/verify you are human|unusual traffic|access denied|captcha|ロボットではない/i.test(text)) throw Error('browser_renderer_challenge');
    const links = await page.locator('a[href]').evaluateAll(nodes => [...new Set(nodes.map(n => n.href)
      .filter(u => /^https:\/\/jp\.mercari\.com\/item\/m[0-9]+$/.test(u)))].slice(0, 25));
    diagnostics.listing_links = links.length;
    if (!links.length) throw Error('browser_renderer_no_listing_links');
    // Only discovery coordinates leave the child. Page text, headers, cookies,
    // search request bodies, and arbitrary exception messages are never emitted.
    const body = '<html><body>' + links.map(u => `<a href="${u}">Listing</a>`).join('') + '</body></html>';
    if (Buffer.byteLength(body, 'utf8') > maxBytes) throw Error('browser_renderer_response_too_large');
    remaining(1);
    diagnostics.stage = 'complete';
    return { status: 200, body, url: target, headers: { 'content-type': 'text/html' } };
  };
  timer = setTimeout(() => stop('browser_renderer_deadline_exhausted'), deadlineMs);
  let result;
  try { result = await Promise.race([work(), stopPromise]); }
  catch (error) {
    result = { error: { code: ERROR_CODES.has(error && error.message) ? error.message : 'browser_renderer_failed' } };
  } finally {
    stopped = true;
    clearTimeout(timer);
    if (browser) {
      try { await bounded(browser.close(), 500, 'close_timeout'); } catch {}
    }
    diagnostics.elapsed_ms = Math.max(0, Math.min(22000, Math.ceil(now() - started)));
  }
  return { ...result, diagnostics };
}

async function main() {
  const { chromium } = require('playwright');
  if (process.argv[2] === '--probe') {
    const browser = await chromium.launch(launchOptions());
    try {
      const context = await browser.newContext({ serviceWorkers: 'block', acceptDownloads: false });
      await context.route('**/*', route => route.abort());
      const page = await context.newPage();
      await page.setContent('<p>offline-runtime-check</p>');
      if (await page.locator('p').innerText() !== 'offline-runtime-check') throw Error('runtime_probe_failed');
      process.stdout.write(JSON.stringify({ ok: true, sandbox_enabled: true, version: browser.version() }));
    } finally { await browser.close(); }
    return;
  }
  const result = await renderPublicPage(process.argv[2], Number(process.argv[3]), { chromium });
  process.stdout.write(JSON.stringify(result));
  if (result.error) process.exitCode = 1;
}

module.exports = { targetUrl, resourceAllowed, isPublicAddress, buildHostRules, launchOptions, renderPublicPage };
if (require.main === module) main().catch(() => {
  process.stdout.write(JSON.stringify({ error: { code: 'browser_renderer_failed' } }));
  process.exitCode = 1;
});
