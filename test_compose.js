// Tests for web/js/compose.js with a minimal stand-in for the DOM. Run by test_compose_js.py, or: node test_compose.js
const assert = require('assert');
const {init, initPrint, initSend} = require('./web/js/compose.js');

function element(props) {
	const handlers = {};
	return Object.assign({
		style: {},
		addEventListener(type, fn) { (handlers[type] = handlers[type] || []).push(fn); },
		fire(type) { (handlers[type] || []).forEach(fn => fn({preventDefault() {}})); },
		getAttribute(name) { return (this.attrs || {})[name]; },
	}, props);
}

// options.subject: initial subject text, or null for a page without a subject box
function setup(addresses, text, options = {}) {
	const url = 'url' in options ? options.url : '/email_body?name=job-1&key=ACC1';
	const boxes = addresses.map(a => element({name: 'em', value: a, checked: true}));
	const area = element({value: text, attrs: url ? {'data-url': url} : {}});
	const subject = 'subject' in options && options.subject === null ? undefined : element({value: options.subject || ''});
	const notice = element({style: {display: 'none'}});
	const reapply = element({});
	const byId = {inputBody: area, inputSubject: subject, bodyNotice: notice, bodyReapply: reapply};
	const doc = {getElementById: id => byId[id], querySelectorAll: () => boxes};
	const requests = [];
	// answer({subject, body}) or answer('body only')
	const fetchFn = u => new Promise(resolve => requests.push({
		url: u,
		answer: a => resolve({json: () => Promise.resolve(typeof a === 'string' ? {body: a} : a)}),
	}));
	return {boxes, area, subject, notice, reapply, requests, api: init(doc, fetchFn)};
}
const settle = () => new Promise(resolve => setImmediate(resolve));
const untick = (t, i) => { t.boxes[i].checked = false; t.boxes[i].fire('change'); };

(async () => {
	// ticking and unticking asks the server with exactly the ticked addresses, in page order, and uses the answer
	let t = setup(['ann@x.com', 'bob+co@x.com'], 'To Ann and Bob\n', {subject: 'Invoice 1'});
	untick(t, 0);
	assert.strictEqual(t.requests.length, 1);
	assert.strictEqual(t.requests[0].url, '/email_body?name=job-1&key=ACC1&em=bob%2Bco%40x.com');
	t.requests[0].answer({subject: 'Invoice 1 for Bob', body: 'To Bob\n'});
	await settle();
	assert.strictEqual(t.area.value, 'To Bob\n');
	assert.strictEqual(t.subject.value, 'Invoice 1 for Bob');
	assert.strictEqual(t.notice.style.display, 'none');

	// nothing ticked: no em at all
	untick(t, 1);
	assert.strictEqual(t.requests[1].url, '/email_body?name=job-1&key=ACC1');
	t.requests[1].answer({subject: 'Invoice 1', body: 'To Sir or Madam\n'});
	await settle();
	assert.strictEqual(t.area.value, 'To Sir or Madam\n');
	assert.strictEqual(t.subject.value, 'Invoice 1');

	// an edited body is kept, with a notice, while the untouched subject still follows the recipients
	t = setup(['ann@x.com', 'bob@x.com'], 'To Ann and Bob\n', {subject: 'For Ann and Bob'});
	t.area.value = 'To Ann and Bob\nmy own words\n';
	untick(t, 1);
	t.requests[0].answer({subject: 'For Ann', body: 'To Ann\n'});
	await settle();
	assert.strictEqual(t.area.value, 'To Ann and Bob\nmy own words\n');
	assert.strictEqual(t.subject.value, 'For Ann');
	assert.strictEqual(t.notice.style.display, '');

	// the link replaces everything using the current ticks
	t.reapply.fire('click');
	assert.strictEqual(t.requests[1].url, '/email_body?name=job-1&key=ACC1&em=ann%40x.com');
	t.requests[1].answer({subject: 'For Ann', body: 'To Ann\n'});
	await settle();
	assert.strictEqual(t.area.value, 'To Ann\n');
	assert.strictEqual(t.notice.style.display, 'none');

	// an edited subject is kept while the body follows; and both edited means both kept
	t = setup(['ann@x.com', 'bob@x.com'], 'To Ann and Bob\n', {subject: 'For Ann and Bob'});
	t.subject.value = 'My own subject';
	untick(t, 1);
	t.requests[0].answer({subject: 'For Ann', body: 'To Ann\n'});
	await settle();
	assert.strictEqual(t.subject.value, 'My own subject');
	assert.strictEqual(t.area.value, 'To Ann\n');
	assert.strictEqual(t.notice.style.display, '');
	t.area.value = 'typed';
	t.boxes[1].checked = true; t.boxes[1].fire('change');
	t.requests[1].answer({subject: 'For Ann and Bob', body: 'To Ann and Bob\n'});
	await settle();
	assert.deepStrictEqual([t.subject.value, t.area.value], ['My own subject', 'typed']);
	t.reapply.fire('click');
	t.requests[2].answer({subject: 'For Ann and Bob', body: 'To Ann and Bob\n'});
	await settle();
	assert.deepStrictEqual([t.subject.value, t.area.value, t.notice.style.display], ['For Ann and Bob', 'To Ann and Bob\n', 'none']);

	// text that was refreshed by us is not "edited": a second tick updates it again without a notice
	t = setup(['ann@x.com', 'bob@x.com'], 'To Ann and Bob\n', {subject: 'S1'});
	untick(t, 0); t.requests[0].answer({subject: 'S2', body: 'To Bob\n'}); await settle();
	t.boxes[0].checked = true; t.boxes[0].fire('change'); t.requests[1].answer({subject: 'S1', body: 'To Ann and Bob\n'}); await settle();
	assert.deepStrictEqual([t.subject.value, t.area.value, t.notice.style.display], ['S1', 'To Ann and Bob\n', 'none']);

	// answers arriving out of order: only the answer to the latest tick is used
	t = setup(['ann@x.com', 'bob@x.com'], 'To Ann and Bob\n', {subject: 'S1'});
	untick(t, 0); untick(t, 1);
	t.requests[1].answer({subject: 'Latest', body: 'To Sir or Madam\n'});
	await settle();
	t.requests[0].answer({subject: 'Stale', body: 'To Bob\n'});
	await settle();
	assert.deepStrictEqual([t.subject.value, t.area.value], ['Latest', 'To Sir or Madam\n']);

	// a page with no subject box still updates the body
	t = setup(['ann@x.com'], 'To Ann\n', {subject: null});
	untick(t, 0); t.requests[0].answer({subject: 'x', body: 'To Sir or Madam\n'}); await settle();
	assert.strictEqual(t.area.value, 'To Sir or Madam\n');

	// an answer missing a field leaves that box as it was (never the text 'undefined')
	t = setup(['ann@x.com'], 'To Ann\n', {subject: 'Keep me'});
	untick(t, 0); t.requests[0].answer('To Sir or Madam\n'); await settle();
	assert.deepStrictEqual([t.subject.value, t.area.value], ['Keep me', 'To Sir or Madam\n']);

	// a failed request leaves the text alone
	t = setup(['ann@x.com'], 'To Ann\n', {subject: 'S'});
	const failing = {getElementById: id => ({inputBody: t.area, inputSubject: t.subject}[id]), querySelectorAll: () => t.boxes};
	const api = init(failing, () => Promise.reject(new Error('offline')));
	await api.refresh(false);
	assert.deepStrictEqual([t.subject.value, t.area.value], ['S', 'To Ann\n']);

	// a page without the compose form is left alone
	assert.strictEqual(setup(['a@x.com'], 'x', {url: null}).api, undefined);
	// printing posts a form: choosing a printer fills it in and submits it, and the click itself is cancelled
	const submitted = [];
	const printerField = {value: ''};
	const printForm = {elements: {printer: printerField}, submit() { submitted.push(printerField.value); }};
	const clickHandlers = [];
	const printItem = {getAttribute: () => 'HP_TONY', addEventListener: (type, fn) => clickHandlers.push(fn)};
	initPrint({getElementById: id => ({printForm}[id]), querySelectorAll: () => [printItem]});
	let prevented = 0;
	clickHandlers[0]({preventDefault() { prevented++; }});
	assert.deepStrictEqual([submitted, prevented], [['HP_TONY'], 1]);
	assert.strictEqual(initPrint({getElementById: () => null, querySelectorAll: () => []}), undefined);   // no print form: nothing to do

	// the send button is disabled as the form is submitted, so a double click can't send twice
	const sendButton = {disabled: false};
	let onSubmit;
	initSend({getElementById: id => id === 'composeForm' ? {addEventListener: (type, fn) => { if (type === 'submit') onSubmit = fn; }} : sendButton});
	assert.strictEqual(sendButton.disabled, false);
	onSubmit();
	assert.strictEqual(sendButton.disabled, true);
	assert.strictEqual(initSend({getElementById: () => null}), undefined);

	console.log('compose.js: all tests passed');
})().catch(e => { console.error(e); process.exit(1); });
