const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

test('a newer reset link replaces the token in an already open popup', async () => {
  const source = fs.readFileSync(path.join(__dirname, 'app.js'), 'utf8');
  const nodes = new Map();
  function element(tag) {
    return {
      tagName: tag.toUpperCase(), children: [], value: '',
      append(...children) { this.children.push(...children); },
      replaceChildren(...children) { this.children = children; },
      setAttribute() {}, addEventListener() {}, showModal() {}, close() {},
    };
  }
  const requests = [];
  const events = {};
  let pending;
  const context = vm.createContext({
    $: id => {
      if (!nodes.has(id)) nodes.set(id, element('div'));
      return nodes.get(id);
    },
    el: element,
    location: { hash: '#reset=first-token' },
    history: { replaceState(_state, _title, hash) { context.location.hash = hash; } },
    window: { addEventListener(name, callback) { events[name] = callback; } },
    session: { user: null },
    action: task => { pending = task(); },
    send: async (url, options) => requests.push({ url, ...options }),
    showError() {},
  });
  vm.runInContext(source.slice(source.indexOf('const HR = (() => {')), context);
  const handlerStart = source.indexOf('window.addEventListener("hashchange",');
  const handlerEnd = source.indexOf('\n});', handlerStart) + '\n});'.length;
  vm.runInContext(source.slice(handlerStart, handlerEnd), context);
  const originalForm = nodes.get('hr-form-content').children[0];
  context.location.hash = '#reset=newest-token';
  events.hashchange();
  const form = nodes.get('hr-form-content').children[0];
  assert.notEqual(form, originalForm);
  for (const wrapper of form.children[0].children) {
    wrapper.children[1].value = 'New-password-123!';
  }
  form.onsubmit({ preventDefault() {} });
  await pending;
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, '/api/v1/hr/password-reset');
  assert.equal(requests[0].body.token, 'newest-token');
  assert.equal(requests[0].authenticated, false);
});
