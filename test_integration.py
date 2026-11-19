# End to end tests: a real RFC 1179 client -> LpdServer -> main.saveJob -> parse -> PDF, then read back
# over HTTP. Runs against a throwaway PRINTERFACE_HOME, never ~/printerface.
import asyncore
import http.client
import json
import os
import pickle
import shutil
import socket
import tempfile
import urllib.parse
import threading
import time
import unittest

import main
import mailer
import emailtemplates
from stationary import DocFormatter
from lpdserver import LpdServer
from httpserver import ToyHttpServer
from textutil import split_lines

def put(lines, row, col, text):
	for i, part in enumerate(text.split('\n')):
		line = lines[row + i]
		lines[row + i] = line[:col] + part + line[col + len(part):]

def make_invoice(doc_num='12345', acc='ACC001', pages=2):
	"""A synthetic Invoice print: 48 blank lines, then 48 lines per page. Each page ends in a form feed,
	and the totals carry an 8-bit pound sign as the Windows print driver sends it."""
	lines = [' ' * 130 for _ in range(48 * (pages + 1))]
	for p in range(pages):
		base = (p + 1) * 48
		put(lines, base + 0, 0, 'INVOICE')
		put(lines, base + 0, 95, '01/10/26')
		put(lines, base + 2, 95, 'Page %d' % (p + 1))
		put(lines, base + 4, 95, doc_num)
		put(lines, base + 8, 12, 'ACME WINES LTD\n1 HIGH STREET\nLONDON')
		put(lines, base + 16, 0, acc)
		put(lines, base + 16, 9, 'PO-7')
		put(lines, base + 16, 20, '289073')
		put(lines, base + 19, 0, 'B0321021\nB0308206')
		put(lines, base + 19, 19, 'BAUCHET Customer Label\nDRAPPIER Carte D\'Or')
		put(lines, base + 19, 55, '12\n6')
		put(lines, base + 42, 89, '\xa3123.45')
		lines[base + 47] = lines[base + 47][:100] + '\x0c'
	return '\r\n'.join(lines) + '\r\n'

def lpr(port, queue, control, data):
	"""Minimal RFC 1179 'receive a printer job' client. control is str, data is bytes."""
	s = socket.create_connection(('127.0.0.1', port), timeout=10)
	def ack():
		assert s.recv(1) == b'\x00', 'no ack'
	try:
		s.sendall(b'\x02' + queue.encode() + b'\n'); ack()
		c = control.encode('latin-1')
		s.sendall(b'\x02%d cfA001testhost\n' % len(c)); ack()
		s.sendall(c + b'\x00'); ack()
		s.sendall(b'\x03%d dfA001testhost\n' % len(data)); ack()
		s.sendall(data + b'\x00'); ack()
	finally:
		s.close()

class ServerThread(threading.Thread):
	def __init__(self):
		threading.Thread.__init__(self)
		self.daemon = True
		self.running = True
	def run(self):
		while self.running:
			asyncore.loop(timeout=0.05, count=1)

class TestPrinterface(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		# test discovery imports main before we get here, so repoint it (and everything derived from
		# settings.HOME) at a scratch directory rather than the real ~/printerface
		cls.home = tempfile.mkdtemp(prefix='printerface-test-')
		main.email_pickle = os.path.join(cls.home, 'email.pickle')
		main.jobdir = os.path.join(cls.home, 'data', 'pickle')
		main.pdfdir = os.path.join(cls.home, 'data', 'pdf') + os.sep
		main.formatter = DocFormatter(main.pdfdir)
		mailer.pickle_file = os.path.join(cls.home, 'mailer.pickle')
		cls.old_user_dir, emailtemplates.USER_DIR = emailtemplates.USER_DIR, os.path.join(cls.home, 'templates')
		for x in [main.jobdir, main.pdfdir]:
			os.makedirs(x, exist_ok=True)
		cls.lpd = LpdServer(main.saveJob, ip='127.0.0.1', port=0)
		cls.http = ToyHttpServer(ip='127.0.0.1', port=0, pathhandlers=main.path_handlers, webroot=main.web_dir)
		cls.lpd_port = cls.lpd.socket.getsockname()[1]
		cls.http_port = cls.http.socket.getsockname()[1]
		cls.thread = ServerThread()
		cls.thread.start()

	@classmethod
	def tearDownClass(cls):
		cls.thread.running = False
		cls.thread.join()
		cls.lpd.close()
		cls.http.close()
		emailtemplates.USER_DIR = cls.old_user_dir
		shutil.rmtree(cls.home, ignore_errors=True)

	def get(self, path, headers=None):
		conn = http.client.HTTPConnection('127.0.0.1', self.http_port, timeout=10)
		conn.request('GET', path, headers=headers or {})
		r = conn.getresponse()
		body = r.read()
		conn.close()
		return r, body

	def post(self, path, **fields):
		conn = http.client.HTTPConnection('127.0.0.1', self.http_port, timeout=10)
		body = urllib.parse.urlencode(fields).encode('utf-8')
		conn.request('POST', path, body=body, headers={'Content-Type': 'application/x-www-form-urlencoded'})
		r = conn.getresponse()
		data = r.read()
		conn.close()
		return r, data

	def setUp(self):
		main.jobs.clear()
		main.email_addresses.clear()
		shutil.rmtree(emailtemplates.USER_DIR, ignore_errors=True)

	def send_invoice(self, **kw):
		before = len(main.jobs)
		lpr(self.lpd_port, 'RAW', 'Hlocalhost\nPtester\nJInvoice\nldfA001testhost\n', make_invoice(**kw).encode('latin-1'))
		deadline = time.time() + 20
		while len(main.jobs) == before and time.time() < deadline:
			time.sleep(0.05)
		self.assertEqual(before + 1, len(main.jobs), 'job was not received')
		return main.jobs[0]

	def test_lpd_to_parsed_job(self):
		j = self.send_invoice()
		# 8-bit data survives the transport as latin-1, and is blanked in the cleaned 'plain' text
		self.assertEqual('Invoice', j['doctype'])
		self.assertEqual('invoice', j['templ'])
		self.assertIn('\xa3123.45', j['data'])
		self.assertNotIn('\xa3', j['plain'])
		self.assertEqual(['ACC001'], list(j['parsed']))
		pages = j['parsed']['ACC001']
		self.assertEqual(2, len(pages))
		# fixed row/column extraction must not be thrown off by the form feeds at the end of each page
		self.assertEqual('12345', pages[0]['doc_num'])
		self.assertEqual('ACC001', pages[1]['accno'])
		self.assertEqual('ACME WINES LTD\n1 HIGH STREET\nLONDON\n\n\n', pages[0]['addr_invoice'])
		self.assertEqual('B0321021\nB0308206', pages[0]['prod_code'].strip('\n'))
		self.assertEqual('123.45', pages[0]['tot_due'].strip())
		self.assertEqual(('ACME WINES LTD',), main.email_accounts['ACC001'])
		self.assertEqual({('ACC001',), ('accounts',)}, set(j['groupfiles']))

	def test_job_pickle_is_protocol_2_and_recoverable(self):
		j = self.send_invoice()
		matches = [os.path.join(d, f) for d, _, fs in os.walk(main.jobdir) for f in fs if f == j['name']]
		self.assertEqual(1, len(matches))
		with open(matches[0], 'rb') as f:
			raw = f.read()
		self.assertEqual(b'\x80\x02', raw[:2])
		name, data = j['name'], j['data']
		main.jobs.clear()
		main.recover()
		again = [x for x in main.jobs if x['name'] == name]
		self.assertEqual(1, len(again))
		self.assertEqual(data, again[0]['data'])
		self.assertEqual('12345', again[0]['parsed']['ACC001'][0]['doc_num'])

	def test_http_endpoints(self):
		j = self.send_invoice()
		name = j['name']

		r, body = self.get('/recent?fmt=json')
		self.assertEqual(200, r.status)
		self.assertTrue(r.getheader('Content-Type').startswith('text/json'))
		results = json.loads(body.decode('utf-8'))['results']
		self.assertEqual(name, results[0]['name'])
		self.assertEqual('Invoice', results[0]['doctype'])

		r, body = self.get('/recent?templ=invoice')
		self.assertEqual(200, r.status)
		self.assertIn(name.encode(), body)

		r, body = self.get('/job?name=' + name)
		parsed = json.loads(body.decode('utf-8'))
		self.assertEqual('12345', parsed['parsed']['ACC001'][0]['doc_num'])
		pdf_uri = parsed['stationary']['ACC001']
		self.assertTrue(pdf_uri.endswith('.pdf'))

		r, body = self.get('/raw?name=' + name)
		self.assertEqual(j['plain'], body.decode('utf-8'))
		self.assertEqual(len(body), int(r.getheader('Content-Length')))
		# page 1 starts on row 48 and page 2 on row 96, i.e. form feeds did not add rows
		rows = split_lines(j['plain'])
		self.assertTrue(rows[48].startswith('INVOICE'))
		self.assertTrue(rows[96].startswith('INVOICE'))

		r, body = self.get('/pdf_file?name=%s&key=ACC001' % name)
		self.assertEqual(200, r.status)
		self.assertEqual('application/pdf', r.getheader('Content-Type'))
		self.assertEqual(b'%PDF', body[:4])
		self.assertEqual(len(body), int(r.getheader('Content-Length')))

		r, body = self.get('/pdf_file?name=%s&key=ACC001&attach=1' % name)
		self.assertIn('attachment', r.getheader('Content-Disposition'))

		for path in ['/home', '/sent', '/printers', '/settings/email', '/settings/template',
				'/pdf?name=' + name, '/debug?name=' + name, '/plaintext?name=' + name, '/']:
			r, body = self.get(path)
			self.assertEqual(200, r.status, path)
			self.assertTrue(body.strip(), path)
			# mako (format_exceptions=True) renders a template failure as a normal 200 page
			self.assertNotIn(b'Mako Runtime Error', body, path)
			self.assertNotIn(b'Traceback', body, path)

		# one <pre> per printed page: the two invoice pages are separated by form feeds
		r, body = self.get('/plaintext?name=' + name)
		self.assertEqual(2, body.count(b'<pre '))
		self.assertIn(b'INVOICE', body)

		r, body = self.get('/css/print.css')
		self.assertEqual(200, r.status)
		self.assertTrue(r.getheader('Content-Type').startswith('text/css'))
		r, body = self.get('/no/such/file')
		self.assertEqual(404, r.status)

	def test_email_settings_with_non_ascii_contact(self):
		self.send_invoice()
		r, body = self.get('/settings/email?account=ACC001&email=jose%40example.com&contact=Jos%C3%A9')
		self.assertEqual(200, r.status)
		self.assertIn('Jos\xe9'.encode('utf-8'), body)
		self.assertEqual('Jos\xe9', main.email_addresses['ACC001']['jose@example.com'])
		# saved address book reloads
		main.email_addresses.clear()
		main.recover()
		self.assertEqual('Jos\xe9', main.email_addresses['ACC001']['jose@example.com'])
		r, body = self.get('/settings/email?account=ACC001&delete=jose%40example.com')
		self.assertNotIn(b'jose@example.com', body)

	def test_recent_json_ts_is_per_job(self):
		first = self.send_invoice(doc_num='111')
		second = self.send_invoice(doc_num='222')
		self.assertNotEqual(first['ts'], second['ts'])
		r, body = self.get('/recent?fmt=json')
		rows = {x['name']: x for x in json.loads(body.decode('utf-8'))['results']}
		# ts is the job's own (naive, utc) receive time; it used to be the oldest loaded job's for every row
		self.assertEqual(first['ts'].isoformat(), rows[first['name']]['ts'])
		self.assertEqual(second['ts'].isoformat(), rows[second['name']]['ts'])

	INVOICE_TEXT = 'To %s\n\nPlease find your latest invoice 289073 attached for account ACC001, for \xa3123.45.'

	def test_compose_form_is_prefilled_from_the_invoice_template(self):
		j = self.send_invoice()
		r, body = self.get('/pdf?name=%s&key=ACC001' % j['name'])
		self.assertEqual(200, r.status)
		self.assertNotIn(b'Mako Runtime Error', body)
		self.assertIn((self.INVOICE_TEXT % 'Sir or Madam').encode('utf-8'), body)
		self.assertIn(b'/settings/templates?kind=invoice&amp;docnum=12345', body)
		# with contacts on the account the greeting names them, and html in a name is escaped in the textarea
		self.get('/settings/email?account=ACC001&email=a%40example.com&contact=Ann')
		self.get('/settings/email?account=ACC001&email=b%40example.com&contact=Bob+%26+Co')
		r, body = self.get('/pdf?name=%s&key=ACC001' % j['name'])
		self.assertIn((self.INVOICE_TEXT % 'Ann and Bob &amp; Co').encode('utf-8'), body)

	def test_documents_without_a_template_keep_the_default_text(self):
		main.email_template = 'DEFAULT TEXT'
		try:
			lpr(self.lpd_port, 'RAW', 'Hlocalhost\nPtester\nJDelvnote\nldfA001testhost\n', make_invoice().encode('latin-1'))
			deadline = time.time() + 20
			while not main.jobs and time.time() < deadline:
				time.sleep(0.05)
			r, body = self.get('/pdf?name=%s' % main.jobs[0]['name'])
			self.assertEqual('delnote', main.jobs[0]['templ'])
			self.assertIn(b'DEFAULT TEXT', body)
			self.assertNotIn(b'/settings/templates?kind', body)
		finally:
			main.email_template = ''

	def test_template_editor_preview_save_and_revert(self):
		j = self.send_invoice(doc_num='424242')
		path = emailtemplates.user_path('invoice')

		r, body = self.get('/settings/templates?kind=invoice')
		self.assertEqual(200, r.status)
		self.assertNotIn(b'Mako Runtime Error', body)
		self.assertIn(b'default template shipped with printerface', body)
		self.assertIn(b'Please find your latest invoice 289073 attached', body)       # preview of the newest invoice
		for kind in ('purchase', 'statement'):
			r, body = self.get('/settings/templates?kind=' + kind)
			self.assertEqual(200, r.status)
			self.assertNotIn(b'Mako Runtime Error', body)
			self.assertIn(b'No ' + emailtemplates.KINDS[kind].lower().encode() + b' document found', body)

		# the filter picks the document; unknown numbers say so
		r, body = self.get('/settings/templates?kind=invoice&docnum=424242')
		self.assertIn(j['name'].encode(), body)
		r, body = self.get('/settings/templates?kind=invoice&docnum=nope')
		self.assertIn(b'No invoice document found matching', body)
		self.assertIn(b'nope', body)

		# preview renders what is typed without saving it
		r, body = self.post('/settings/templates', kind='invoice', action='preview', docnum='424242',
			template='Hi ${email.name}, invoice ${doc.doc_num} for \xa3${doc.tot_due}.')
		self.assertEqual(200, r.status)
		self.assertIn('Hi Sir or Madam, invoice 424242 for \xa3123.45.'.encode('utf-8'), body)
		self.assertFalse(os.path.exists(path))

		# save writes the user template, and the compose form then uses it
		r, body = self.post('/settings/templates', kind='invoice', action='save', docnum='',
			template='Dear ${email.name}\r\nInvoice ${doc.doc_num}\r\n')
		self.assertIn(b'Saved the invoice template', body)
		self.assertIn(b'Using your customised template', body)
		with open(path, encoding='utf-8') as f:
			self.assertEqual('Dear ${email.name}\nInvoice ${doc.doc_num}\n', f.read())
		r, body = self.get('/pdf?name=%s&key=ACC001' % j['name'])
		self.assertIn(b'Dear Sir or Madam\nInvoice 424242', body)

		# revert goes back to the shipped text
		r, body = self.post('/settings/templates', kind='invoice', action='revert')
		self.assertIn(b'Reverted to the default invoice template', body)
		self.assertFalse(os.path.exists(path))
		r, body = self.get('/pdf?name=%s&key=ACC001' % j['name'])
		self.assertIn((self.INVOICE_TEXT.replace('289073', '289073') % 'Sir or Madam').encode('utf-8'), body)

	def test_template_editor_refuses_templates_that_could_run_code(self):
		self.send_invoice()
		canary = os.path.join(emailtemplates.USER_DIR, '..', 'canary')
		evil = [
			"${__import__('os').makedirs(%r)}" % canary,
			"<%% import os; os.makedirs(%r) %%>" % canary,
			"% import os",
			"${doc.__class__}",
		]
		for text in evil:
			for action in ('preview', 'save'):
				r, body = self.post('/settings/templates', kind='invoice', action=action, template=text)
				self.assertEqual(200, r.status)
				self.assertIn(b"This template can", body, text)
				self.assertFalse(os.path.exists(emailtemplates.user_path('invoice')), text)
				self.assertFalse(os.path.exists(canary), text)
		# the kind comes from a fixed list, never from a path
		r, body = self.post('/settings/templates', kind='../../etc/passwd', action='save', template='x')
		self.assertEqual(200, r.status)
		self.assertFalse(os.path.exists(os.path.join(emailtemplates.USER_DIR, '..', '..', 'etc')))

	def test_keepalive_two_requests_one_connection(self):
		self.send_invoice()
		conn = http.client.HTTPConnection('127.0.0.1', self.http_port, timeout=10)
		for _ in range(2):
			conn.request('GET', '/recent?fmt=json')
			r = conn.getresponse()
			self.assertEqual(200, r.status)
			json.loads(r.read().decode('utf-8'))
		conn.close()

if __name__ == "__main__":
	unittest.main()
