const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const source = fs.readFileSync(path.join(__dirname, 'app.js'), 'utf8');

function setup({ reset = false, expired = false } = {}) {
  const storage = new Map([['cestos.refresh-token', 'saved-refresh']]);
  const calls = [];
  const context = vm.createContext({
    SESSION_KEY: 'cestos.refresh-token', openedResetLink: reset,
    session: {}, refreshing: null, Date,
    sessionStorage: { getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value) },
    action: task => task(),
    send: async (url, options) => {
      calls.push({url, options});
      if (expired) throw {status: 401};
      return {access_token: 'new-access', refresh_token: 'rotated-refresh', expires_in: 900};
    },
    api: async () => ({first_name: 'Ada'}),
    showWorkspace: async user => calls.push({user}),
    signOutLocally: () => { storage.clear(); calls.push({logout: true}); },
    showError: () => {},
  });
  vm.runInContext(source.slice(source.indexOf('function saveTokens('), source.indexOf('async function api(')), context);
  vm.runInContext(source.slice(source.indexOf('async function restoreSession('), source.indexOf('window.addEventListener("DOMContentLoaded"')), context);
  return {context, storage, calls};
}

test('reload exchanges the saved refresh token and persists its replacement', async () => {
  const {context, storage, calls} = setup();
  await vm.runInContext('restoreSession()', context);
  assert.equal(calls[0].url, '/api/v1/auth/refresh');
  assert.equal(calls[0].options.body.refresh_token, 'saved-refresh');
  assert.equal(storage.get('cestos.refresh-token'), 'rotated-refresh');
  assert.equal(calls[1].user.first_name, 'Ada');
});

test('expired refresh tokens return to signed-out state', async () => {
  const {context, storage, calls} = setup({expired: true});
  await vm.runInContext('restoreSession()', context);
  assert.equal(storage.size, 0);
  assert.equal(calls.at(-1).logout, true);
});

test('password-reset links do not restore a previous login', async () => {
  const {context, calls} = setup({reset: true});
  await vm.runInContext('restoreSession()', context);
  assert.equal(calls.length, 0);
});
