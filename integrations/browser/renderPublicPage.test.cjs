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
