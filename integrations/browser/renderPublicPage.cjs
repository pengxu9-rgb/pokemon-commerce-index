'use strict';

// Optional, operator-installed Playwright runtime. No downloads, account cookies,
// hidden endpoint calls, or CAPTCHA solving are performed by this transport.
const dns = require('node:dns/promises');
const net = require('node:net');
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

async function buildHostRules(lookup = dns.lookup) {
  const hosts = new Set();
  const rules = [];
  for (const host of RESOURCE_HOSTS) {
    let addresses;
    try { addresses = await lookup(host, { all: true }); } catch { continue; }
    if (!addresses.length || addresses.some(a => !isPublicAddress(a.address))) continue;
    // Pin Chrome's lookup to the checked IPv4 address; unknown hosts cannot use
    // Chrome's independent resolver to bypass the public-address check.
    const chosen = addresses.find(a => net.isIPv4(a.address));
    if (!chosen) continue;
    hosts.add(host);
    rules.push(`MAP ${host} ${chosen.address}`);
  }
  if (!hosts.has('jp.mercari.com')) throw Error('public_source_dns_unavailable');
  rules.push('MAP * ~NOTFOUND');
  return { hosts, rules: rules.join(', ') };
}

async function main() {
  const { chromium } = require('playwright');
  const target = targetUrl(process.argv[2]);
  const maxBytes = Number(process.argv[3]);
  if (!Number.isInteger(maxBytes) || maxBytes < 1024 || maxBytes > 1_000_000) throw Error('invalid_bound');
  const pinned = await buildHostRules();
  const browser = await chromium.launch({ channel: 'chrome', headless: true, chromiumSandbox: true,
    args: [`--host-resolver-rules=${pinned.rules}`] });
  try {
    const context = await browser.newContext({ serviceWorkers: 'block', acceptDownloads: false });
    await context.route('**/*', route => resourceAllowed(route.request(), pinned.hosts) ? route.continue() : route.abort());
    const page = await context.newPage();
    const response = await page.goto(target, { waitUntil: 'domcontentloaded', timeout: 12000 });
    if (!response || response.status() !== 200 || page.url() !== target) throw Error('source_unavailable');
    // Only public page rendering; do not click login, purchase or challenge UI.
    try { await page.locator('a[href*="/item/m"]').first().waitFor({ timeout: 7000 }); } catch {}
    const text = await page.locator('body').innerText({ timeout: 1000 });
    if (/verify you are human|unusual traffic|access denied|captcha|ロボットではない/i.test(text)) throw Error('source_challenge');
    const links = await page.locator('a[href]').evaluateAll(nodes => [...new Set(nodes.map(n => n.href)
      .filter(u => /^https:\/\/jp\.mercari\.com\/item\/m[0-9]+$/.test(u)))].slice(0, 25));
    // The consumer needs discovery coordinates only; omit page scripts/media and
    // all unrelated content from the rendered transport response.
    const body = '<html><body>' + links.map(u => `<a href="${u}">Listing</a>`).join('') + '</body></html>';
    if (Buffer.byteLength(body, 'utf8') > maxBytes) throw Error('response_too_large');
    process.stdout.write(JSON.stringify({ status: 200, body, url: target, headers: { 'content-type': 'text/html' } }));
  } finally {
    await browser.close();
  }
}

module.exports = { targetUrl, resourceAllowed, isPublicAddress, buildHostRules };
if (require.main === module) main().catch(() => { process.exitCode = 1; });
