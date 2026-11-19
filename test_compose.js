// Tests for web/js/compose.js with a minimal stand-in for the DOM. Run by test_compose_js.py, or: node test_compose.js
const assert = require('assert');
const {init} = require('./web/js/compose.js');

function element(props) {
	const handlers = {};
	return Object.assign({
		style: {},
		addEventListener(type, fn) { (handlers[type] = handlers[type] || []).push(fn); },
		fire(type) { (handlers[type] || []).forEach(fn => fn({preventDefault() {}})); },
		getAttribute(name) { return (this.attrs || {})[name]; },
	}, props);
}

function setup(addresses, text, url = '/email_body?name=job-1&key=ACC1') {
	const boxes = addresses.map(a => element({name: 'em', value: a, checked: true}));
	const area = element({value: text, attrs: url ? {'data-url': url} : {}});
	const notice = element({style: {display: 'none'}});
	const reapply = element({});
	const byId = {inputBody: area, bodyNotice: notice, bodyReapply: reapply};
	const doc = {getElementById: id => byId[id], querySelectorAll: () => boxes};
	const requests = [];
	const fetchFn = u => new Promise(resolve => requests.push({url: u, answer: body => resolve({json: () => Promise.resolve({body})})}));
	return {boxes, area, notice, reapply, requests, api: init(doc, fetchFn)};
}
const settle = () => new Promise(resolve => setImmediate(resolve));

(async () => {
	// ticking and unticking asks the server with exactly the ticked addresses, in page order, and uses the answer
	let t = setup(['ann@x.com', 'bob+co@x.com'], 'To Ann and Bob\n');
	t.boxes[0].checked = false;
	t.boxes[0].fire('change');
	assert.strictEqual(t.requests.length, 1);
	assert.strictEqual(t.requests[0].url, '/email_body?name=job-1&key=ACC1&em=bob%2Bco%40x.com');
	t.requests[0].answer('To Bob\n');
	await settle();
	assert.strictEqual(t.area.value, 'To Bob\n');
	assert.strictEqual(t.notice.style.display, 'none');

	// nothing ticked: no em at all
	t.boxes[1].checked = false;
	t.boxes[1].fire('change');
	assert.strictEqual(t.requests[1].url, '/email_body?name=job-1&key=ACC1');
	t.requests[1].answer('To Sir or Madam\n');
	await settle();
	assert.strictEqual(t.area.value, 'To Sir or Madam\n');

	// edited text is kept, with a notice; the link replaces it using the current ticks
	t = setup(['ann@x.com', 'bob@x.com'], 'To Ann and Bob\n');
	t.area.value = 'To Ann and Bob\nmy own words\n';
	t.boxes[1].checked = false;
	t.boxes[1].fire('change');
	t.requests[0].answer('To Ann\n');
	await settle();
	assert.strictEqual(t.area.value, 'To Ann and Bob\nmy own words\n');
	assert.strictEqual(t.notice.style.display, '');
	t.reapply.fire('click');
	assert.strictEqual(t.requests[1].url, '/email_body?name=job-1&key=ACC1&em=ann%40x.com');
	t.requests[1].answer('To Ann\n');
	await settle();
	assert.strictEqual(t.area.value, 'To Ann\n');
	assert.strictEqual(t.notice.style.display, 'none');

	// text that was refreshed by us is not "edited": a second tick updates it again without a notice
	t = setup(['ann@x.com', 'bob@x.com'], 'To Ann and Bob\n');
	t.boxes[0].checked = false; t.boxes[0].fire('change'); t.requests[0].answer('To Bob\n'); await settle();
	t.boxes[0].checked = true; t.boxes[0].fire('change'); t.requests[1].answer('To Ann and Bob\n'); await settle();
	assert.strictEqual(t.area.value, 'To Ann and Bob\n');
	assert.strictEqual(t.notice.style.display, 'none');

	// answers arriving out of order: only the answer to the latest tick is used
	t = setup(['ann@x.com', 'bob@x.com'], 'To Ann and Bob\n');
	t.boxes[0].checked = false; t.boxes[0].fire('change');
	t.boxes[1].checked = false; t.boxes[1].fire('change');
	t.requests[1].answer('To Sir or Madam\n');
	await settle();
	t.requests[0].answer('To Bob\n');
	await settle();
	assert.strictEqual(t.area.value, 'To Sir or Madam\n');

	// a failed request leaves the text alone
	t = setup(['ann@x.com'], 'To Ann\n');
	const failing = {getElementById: id => ({inputBody: t.area}[id]), querySelectorAll: () => t.boxes};
	const api = init(failing, () => Promise.reject(new Error('offline')));
	await api.refresh(false);
	assert.strictEqual(t.area.value, 'To Ann\n');

	// a page without the compose form is left alone
	assert.strictEqual(setup(['a@x.com'], 'x', null).api, undefined);
	console.log('compose.js: all tests passed');
})().catch(e => { console.error(e); process.exit(1); });
