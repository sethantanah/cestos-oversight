const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

test('My profile submits activity and leave through self-service routes', async () => {
  const nodes = new Map();
  function el(tag, text) {
    return {tagName: tag.toUpperCase(), text, children: [], value: '', files: [],
      append(...items) { this.children.push(...items); },
      replaceChildren(...items) { this.children = items; },
      addEventListener() {}, setAttribute() {}, showModal() {}, close() {}};
  }
  const requests = [];
  let pending;
  const context = vm.createContext({
    el, Date,
    $: id => { if (!nodes.has(id)) nodes.set(id, el('div')); return nodes.get(id); },
    location: {hash: '#home'},
    action: task => { pending = task(); },
    api: async (url, options) => {
      requests.push({url, options});
      return url.endsWith('/me') ? {first_name: 'Ada'} : [];
    },
  });
  const source = fs.readFileSync(path.join(__dirname, 'app.js'), 'utf8');
  vm.runInContext(source.slice(source.indexOf('const HR = (() => {')), context);
  await vm.runInContext('HR.self()', context);
  const find = (node, text) => node.text === text ? node : node.children.map(n => find(n, text)).find(Boolean);
  find(nodes.get('my-profile-content'), 'Log activity').onclick();
  await pending;
  let form = nodes.get('hr-form-content').children[0];
  const fill = (form, values) => {
    for (const wrapper of form.children[0].children) {
      const input = wrapper.children[1];
      if (input.id in values) input.value = values[input.id];
    }
  };
  fill(form, {'hr-date': '2026-09-08', 'hr-notes': 'Inspected equipment'});
  form.onsubmit({preventDefault() {}});
  await pending;
  const activity = requests.find(r => r.options?.method === 'POST');
  assert.equal(activity.url, '/api/v1/hr/me/time-logs');
  assert.equal(activity.options.body.notes, 'Inspected equipment');
  assert.equal(activity.options.body.check_in, null);
  find(nodes.get('my-profile-content'), 'Request leave').onclick();
  await pending;
  form = nodes.get('hr-form-content').children[0];
  fill(form, {'hr-start_date': '2026-10-01', 'hr-end_date': '2026-10-03', 'hr-reason': 'Family visit'});
  form.onsubmit({preventDefault() {}});
  await pending;
  const leave = requests.find(r => r.url.endsWith('/leave-requests') && r.options?.method === 'POST');
  assert.equal(leave.url, '/api/v1/hr/me/leave-requests');
  assert.equal(leave.options.body.end_date, '2026-10-03');
});
