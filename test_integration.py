# End to end tests: a real RFC 1179 client -> LpdServer -> main.saveJob -> parse -> PDF, then read back
# over HTTP. Runs against a throwaway PRINTERFACE_HOME, never ~/printerface.
import asyncio
import http.client
import io
import re
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
from datetime import datetime
from unittest import mock

import main
import mailer
import printing
import printstatus
import derived
import uploader
import emailtemplates
from stationary import DocFormatter
from lpdserver import LpdServer
from httpserver import HttpServer
from textutil import split_lines

def put(lines, row, col, text):
	for i, part in enumerate(text.split('\n')):
		line = lines[row + i]
		lines[row + i] = line[:col] + part + line[col + len(part):]

def make_invoice(doc_num='12345', acc='ACC001', pages=2, doc_nums=None, totals=None, net=None, vat=None):
	"""A synthetic Invoice print: 48 blank lines, then 48 lines per page. Each page ends in a form feed,
	and the totals carry an 8-bit pound sign as the Windows print driver sends it. By default every page is
	part of invoice doc_num; doc_nums gives each page its own invoice (and totals its own amount)."""
	lines = [' ' * 130 for _ in range(48 * (pages + 1))]
	for p in range(pages):
		base = (p + 1) * 48
		put(lines, base + 0, 0, 'INVOICE')
		put(lines, base + 0, 95, '01/10/26')
		put(lines, base + 2, 95, 'Page %d' % (p + 1))
		put(lines, base + 4, 95, doc_nums[p] if doc_nums else doc_num)
		put(lines, base + 8, 12, 'ACME WINES LTD\n1 HIGH STREET\nLONDON')
		put(lines, base + 16, 0, acc)
		put(lines, base + 16, 9, 'PO-7')
		put(lines, base + 16, 20, '289073')
		put(lines, base + 19, 0, 'B0321021\nB0308206')
		put(lines, base + 19, 19, 'BAUCHET Customer Label\nDRAPPIER Carte D\'Or')
		put(lines, base + 19, 55, '12\n6')
		put(lines, base + 42, 89, totals[p] if totals else '\xa3123.45')
		if net:
			put(lines, base + 37, 89, net)
			put(lines, base + 39, 89, vat)
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

def mailer_results():
	return main.mailqueue.results

class ServerThread(threading.Thread):
	"""An event loop in a thread, so that the servers run as they do in main.py (handlers and the LPD receiver
	on one loop thread) while the tests, in this thread, are their clients."""
	def __init__(self):
		threading.Thread.__init__(self)
		self.daemon = True
		self.loop = asyncio.new_event_loop()

	def run(self):
		asyncio.set_event_loop(self.loop)
		self.loop.run_forever()

	def call(self, coro):
		return asyncio.run_coroutine_threadsafe(coro, self.loop).result(30)

	def stop(self):
		self.loop.call_soon_threadsafe(self.loop.stop)
		self.join()
		self.loop.close()

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
		cls.old_derived, main.derivedcache = main.derivedcache, derived.DerivedCache(os.path.join(cls.home, 'derived.pickle'))
		cls.old_uploadlog, main.uploadqueue.log = main.uploadqueue.log, uploader.UploadLog(os.path.join(cls.home, 'upload.pickle'))
		cls.old_printlog, printing.printlog = printing.printlog, printing.PrintLog(os.path.join(cls.home, 'printer.pickle'))
		cls.old_user_dir, emailtemplates.USER_DIR = emailtemplates.USER_DIR, os.path.join(cls.home, 'templates')
		for x in [main.jobdir, main.pdfdir]:
			os.makedirs(x, exist_ok=True)
		# Nothing in these tests may print. Delivery notes and pick lists are auto-printed (defaults.cfg), which
		# would run lpr: on a machine without CUPS that fails, and on one with a printer called HP_TONY it would print.
		cls.print_patch = mock.patch.object(main, 'printFile')
		cls.printed = cls.print_patch.start()
		# likewise the Printers page: lpstat is only ever the canned text, never the machine's own CUPS
		cls.lpstat_patch = mock.patch.object(printstatus, 'run_lpstat', return_value=printstatus.SAMPLE)
		cls.lpstat_patch.start()
		cls.thread = ServerThread()
		cls.thread.start()
		cls.lpd = cls.thread.call(LpdServer(main.saveJob, ip='127.0.0.1', port=0).start())
		cls.http = cls.thread.call(HttpServer(main.path_handlers, main.web_dir, ip='127.0.0.1', port=0).start())
		cls.lpd_port = cls.lpd.port
		cls.http_port = cls.http.port

	@classmethod
	def tearDownClass(cls):
		cls.thread.call(cls.lpd.close())
		cls.thread.call(cls.http.close())
		cls.thread.stop()
		cls.print_patch.stop()
		cls.lpstat_patch.stop()
		printing.printlog = cls.old_printlog
		main.uploadqueue.log = cls.old_uploadlog
		main.derivedcache = cls.old_derived
		emailtemplates.USER_DIR = cls.old_user_dir
		shutil.rmtree(cls.home, ignore_errors=True)

	def test_printers_page(self):
		printstatus.reset_cache()
		old = main.config.get('Robot', 'auto_printer')
		try:
			main.config.set('Robot', 'auto_printer', 'DESK_LASER')
			r, body = self.get('/printers')
			self.assertEqual(r.status, 200)
			text = body.decode()
			for expected in ['OFFICE_MFP', 'HALL_COPIER_192.0.2.10', 'Connecting to printer...', 'socket://192.0.2.10', 'OFFICE_MFP-41071']:
				self.assertIn(expected, text)
			# DESK_LASER has a 2017 job waiting
			self.assertIn('may not be working', text)
			main.config.set('Robot', 'auto_printer', 'NOPE')
			printstatus.reset_cache()
			self.assertIn('no printer called NOPE', self.get('/printers')[1].decode())
		finally:
			main.config.set('Robot', 'auto_printer', old)
			printstatus.reset_cache()

	def test_printers_page_without_cups(self):
		printstatus.reset_cache()
		with mock.patch.object(printstatus, 'run_lpstat', side_effect=printstatus.LpstatError('cupsd is <down>')):
			r, body = self.get('/printers')
		self.assertEqual(r.status, 200)
		self.assertIn("Can't read the printer status", body.decode())
		self.assertIn('cupsd is &lt;down&gt;', body.decode())
		printstatus.reset_cache()

	def get(self, path, headers=None):
		conn = http.client.HTTPConnection('127.0.0.1', self.http_port, timeout=10)
		conn.request('GET', path, headers=headers or {})
		r = conn.getresponse()
		body = r.read()
		conn.close()
		return r, body

	def post(self, path, **fields):
		conn = http.client.HTTPConnection('127.0.0.1', self.http_port, timeout=10)
		body = urllib.parse.urlencode(fields, doseq=True).encode('utf-8')
		conn.request('POST', path, body=body, headers={'Content-Type': 'application/x-www-form-urlencoded'})
		r = conn.getresponse()
		data = r.read()
		conn.close()
		return r, data

	def post_redirect(self, path, **fields):
		"""POST, expect the 303 that sends the browser back to a GET page, and return (location, that page)."""
		r, data = self.post(path, **fields)
		self.assertEqual(303, r.status, data[:300])
		location = r.getheader('Location')
		r2, page = self.get(location)
		self.assertEqual(200, r2.status, location)
		return location, page

	def add_contact(self, account, email, name):
		self.post_redirect('/settings/email', account=account, email=email, contact=name)

	def setUp(self):
		self.printed.reset_mock()
		main.jobs.clear()
		main.email_addresses.clear()
		shutil.rmtree(emailtemplates.USER_DIR, ignore_errors=True)

	def send_invoice(self, jtype='Invoice', **kw):
		before = len(main.jobs)
		lpr(self.lpd_port, 'RAW', 'Hlocalhost\nPtester\nJ%s\nldfA001testhost\n' % jtype, make_invoice(**kw).encode('latin-1'))
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

		for path in ['/home', '/sent', '/printed', '/printers', '/settings/email', '/settings/templates',
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
		self.assertIn(b'Debug Info', body)
		self.assertIn(b'Document Pages', body)

		r, body = self.get('/css/print.css')
		self.assertEqual(200, r.status)
		self.assertTrue(r.getheader('Content-Type').startswith('text/css'))
		r, body = self.get('/no/such/file')
		self.assertEqual(404, r.status)

	def test_email_settings_with_non_ascii_contact(self):
		self.send_invoice()
		location, body = self.post_redirect('/settings/email', account='ACC001', email='jose@example.com', contact='Jos\xe9')
		self.assertEqual('/settings/email', location)
		self.assertIn('Jos\xe9'.encode('utf-8'), body)
		self.assertEqual('Jos\xe9', main.email_addresses['ACC001']['jose@example.com'])
		# saved address book reloads
		main.email_addresses.clear()
		main.recover()
		self.assertEqual('Jos\xe9', main.email_addresses['ACC001']['jose@example.com'])
		location, body = self.post_redirect('/settings/email', account='ACC001', delete='jose@example.com')
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

	# The wording of the shipped templates is theirs to change, so these check the facts rather than every word
	INVOICE_SUBJECT = r'New Invoice \d+'                      # 'New Invoice 12345', as operations write it

	def assertInvoiceBody(self, page, names, doc_num='12345', msg=None):
		self.assertRegex(page.decode('utf-8'), r'To %s,?\n\nPlease find your latest invoice %s attached for account ACC001, for \xa3123\.45\.' % (re.escape(names), doc_num), msg)

	def assertDefaultBody(self, page, names, msg=None):
		self.assertRegex(page.decode('utf-8'), r'To %s,?\n\nPlease find your (?:\w+ )?document attached\.' % re.escape(names), msg)

	def assertSubjectBox(self, page, pattern, msg=None):
		self.assertRegex(page.decode('utf-8'), r'name="subject" placeholder="Subject" value="%s"' % pattern, msg)

	def test_compose_form_is_prefilled_from_the_invoice_template(self):
		j = self.send_invoice()
		r, body = self.get('/pdf?name=%s&key=ACC001' % j['name'])
		self.assertEqual(200, r.status)
		self.assertNotIn(b'Mako Runtime Error', body)
		self.assertInvoiceBody(body, 'Sir or Madam')
		self.assertSubjectBox(body, self.INVOICE_SUBJECT)
		self.assertNotRegex(body.decode('utf-8'), self.INVOICE_SUBJECT + '[^<\n]*\n\n?To ')   # the subject is not repeated in the text
		self.assertIn(b'/settings/templates?kind=invoice&amp;docnum=12345', body)
		# with contacts on the account the greeting names them, and html in a name is escaped in the textarea
		self.add_contact('ACC001', 'a@example.com', 'Ann')
		self.add_contact('ACC001', 'b@example.com', 'Bob & Co')
		r, body = self.get('/pdf?name=%s&key=ACC001' % j['name'])
		self.assertInvoiceBody(body, 'Ann and Bob &amp; Co')

	DEFAULT_SUBJECT_PATTERN = 'Document[^"]*attached'

	def test_other_documents_use_the_default_template(self):
		j = self.send_invoice('Delvnote')
		self.assertEqual('delnote', j['templ'])
		r, body = self.get('/pdf?name=' + j['name'])
		self.assertEqual(200, r.status)
		self.assertNotIn(b'Mako Runtime Error', body)
		self.assertDefaultBody(body, 'Sir or Madam')
		self.assertSubjectBox(body, self.DEFAULT_SUBJECT_PATTERN)
		self.assertIn(('/settings/templates?kind=default&amp;docnum=' + j['name']).encode(), body)
		self.assertIn(b'Edit the default email template', body)

	def test_template_editor_preview_save_and_revert(self):
		j = self.send_invoice(doc_num='424242')
		path = emailtemplates.user_path('invoice')

		r, body = self.get('/settings/templates?kind=invoice')
		self.assertEqual(200, r.status)
		self.assertNotIn(b'Mako Runtime Error', body)
		self.assertIn(b'<p>Template <code>invoice.mako</code></p>', body)
		self.assertNotIn(b'Revert to default', body)                    # nothing customised yet, so nothing to revert
		self.assertIn(b'Please find your latest invoice 424242 attached', body)       # preview of the newest invoice
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
			template='Re ${doc.doc_num}\n\nHi ${email.name}, invoice ${doc.doc_num} for \xa3${doc.tot_due}.')
		self.assertEqual(200, r.status)
		self.assertIn(b'<strong>Subject:</strong> Re 424242', body)
		self.assertIn('Hi Sir or Madam, invoice 424242 for \xa3123.45.'.encode('utf-8'), body)
		self.assertFalse(os.path.exists(path))
		# a first line that renders empty means no subject, and the editor says so
		r, body = self.post('/settings/templates', kind='invoice', action='preview', docnum='424242', template='\nJust text')
		self.assertIn(b'the first line of the template is empty', body)
		self.assertIn(b'Just text', body)

		# save writes the user template, and the compose form then uses it
		location, body = self.post_redirect('/settings/templates', kind='invoice', action='save', docnum='',
			template='Dear ${email.name}\r\nInvoice ${doc.doc_num}\r\n')
		self.assertEqual('/settings/templates?kind=invoice&docnum=&saved=1', location)
		self.assertIn(b'Saved the invoice template', body)
		self.assertIn(b'<p>Template <code>invoice.mako</code></p>', body)      # the same line, customised or not
		self.assertIn(b'Revert to default', body)
		with open(path, encoding='utf-8') as f:
			self.assertEqual('Dear ${email.name}\nInvoice ${doc.doc_num}\n', f.read())
		r, body = self.get('/pdf?name=%s&key=ACC001' % j['name'])
		self.assertIn(b'value="Dear Sir or Madam"', body)                      # the first line is the subject...
		self.assertIn(b'Invoice 424242', body)                                  # ...and the rest is the text
		self.assertNotIn(b'Dear Sir or Madam\nInvoice', body)

		# revert goes back to the shipped text
		location, body = self.post_redirect('/settings/templates', kind='invoice', action='revert')
		self.assertIn(b'Reverted to the shipped invoice template', body)
		for _ in range(2):                                                      # refreshing the page after it just says the same
			self.assertIn(b'Reverted to the shipped invoice template', self.get(location)[1])
		self.assertFalse(os.path.exists(path))
		r, body = self.get('/pdf?name=%s&key=ACC001' % j['name'])
		self.assertInvoiceBody(body, 'Sir or Madam', doc_num='424242')
		self.assertSubjectBox(body, self.INVOICE_SUBJECT)

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
		self.assertEqual(303, r.status)
		self.assertIn('kind=invoice', r.getheader('Location'))             # an unknown kind means the first one, not a path
		self.assertFalse(os.path.exists(os.path.join(emailtemplates.USER_DIR, '..', '..', 'etc')))
		self.assertEqual(['invoice.mako'], os.listdir(emailtemplates.USER_DIR))

	def test_email_body_follows_the_ticked_contacts(self):
		j = self.send_invoice()
		self.add_contact('ACC001', 'ann@x.com', 'Ann')
		self.add_contact('ACC001', 'bob@x.com', 'Bob')

		def body(*ticked):
			query = ['name=' + j['name'], 'key=ACC001'] + ['em=' + urllib.parse.quote(e) for e in ticked]
			r, data = self.get('/email_body?' + '&'.join(query))
			self.assertEqual(200, r.status)
			self.assertTrue(r.getheader('Content-Type').startswith('text/json'))
			answer = json.loads(data.decode('utf-8'))
			self.assertIsNone(answer['warning'])
			return answer['body']

		self.assertRegex(body('ann@x.com', 'bob@x.com'), r'\ATo Ann and Bob,?\n\nPlease find your latest invoice 12345')
		self.assertRegex(body('bob@x.com'), r'\ATo Bob,?\n\nPlease find')
		self.assertRegex(body(), r'\ATo Sir or Madam,?\n\nPlease find')              # nobody ticked
		self.assertRegex(body('stranger@x.com'), r'\ATo Sir or Madam,?\n')            # not in the address book: no name to use
		query = 'name=%s&key=ACC001&em=bob%%40x.com&em=ann%%40x.com' % j['name']
		self.assertTrue(json.loads(self.get('/email_body?' + query)[1].decode())['subject'].startswith('New Invoice '))
		# subject and body both follow the recipients: first line is the subject, the rest the body
		self.post('/settings/templates', kind='invoice', action='save', template='For ${email.name}\n\n${email.name} <${email.address}>')
		answer = json.loads(self.get('/email_body?' + query)[1].decode())
		self.assertEqual(('For Bob and Ann', 'Bob and Ann <bob@x.com>\n'), (answer['subject'], answer['body']))   # the first ticked address
		answer = json.loads(self.get('/email_body?name=%s&key=ACC001' % j['name'])[1].decode())
		self.assertEqual(('For Sir or Madam', 'Sir or Madam <>\n'), (answer['subject'], answer['body']))

	def test_compose_form_is_wired_for_live_updates(self):
		j = self.send_invoice()
		self.add_contact('ACC001', 'bob@x.com', 'Bob & Co')
		r, body = self.get('/pdf?name=%s&key=ACC001' % j['name'])
		self.assertNotIn(b'Mako Runtime Error', body)
		self.assertIn(('data-url="/email_body?name=%s&amp;key=ACC001"' % j['name']).encode(), body)
		self.assertIn(b'id="bodyNotice"', body)
		self.assertIn(b'<script src="/js/compose.js"></script>', body)
		# contact names and addresses are escaped where they are shown and where they are values
		self.assertIn(b'<input type="checkbox" name="em" value="bob@x.com" checked> Bob &amp; Co', body)
		r, js = self.get('/js/compose.js')
		self.assertEqual(200, r.status)
		self.assertIn('javascript', r.getheader('Content-Type'))

	def test_default_template_editor(self):
		self.send_invoice(doc_num='111')                  # an invoice does not count as "another document"
		r, body = self.get('/settings/templates?kind=default')
		self.assertEqual(200, r.status)
		self.assertNotIn(b'Mako Runtime Error', body)
		self.assertIn(b'No document found', body)
		j = self.send_invoice('Delvnote')
		r, body = self.get('/settings/templates?kind=default')
		self.assertNotIn(b'Mako Runtime Error', body)
		self.assertIn(j['name'].encode(), body)
		self.assertIn(b'<strong>Delvnote</strong>', body)
		self.assertIn(b'job name or document type', body)
		self.assertIn(b'${company.name}', body)           # the company details are available here too
		self.assertNotIn(b'${doc.', body)
		self.assertIn(b'Default</a>', body)               # the tab
		# the filter takes a job name or a document type
		for term in (j['name'], 'delvnote'):
			r, body = self.get('/settings/templates?kind=default&docnum=' + term)
			self.assertIn(j['name'].encode(), body, term)
		r, body = self.get('/settings/templates?kind=default&docnum=Nonesuch')
		self.assertIn(b'No document found matching', body)

		r, body = self.post('/settings/templates', kind='default', action='preview', docnum='', template='${job.doctype} for ${email.name}')
		self.assertIn(b'Delvnote for Sir or Madam', body)
		r, body = self.post('/settings/templates', kind='default', action='preview', docnum='', template='From ${company.name} <${company.email}>\n\nHi ${email.name}')
		self.assertIn(b'From YOUR DOMAIN LTD. &lt;sales@yourdomain.com&gt;', body)      # the placeholder company in defaults.cfg
		# only email and job exist here
		for text in ('${doc.ourref}', '% for d in docs:\n% endfor'):
			r, body = self.post('/settings/templates', kind='default', action='save', template=text)
			self.assertIn(b"This template can", body, text)
			self.assertFalse(os.path.exists(emailtemplates.user_path('default')), text)
		location, body = self.post_redirect('/settings/templates', kind='default', action='save', template='Hello ${email.name}, re ${job.doctype}')
		self.assertIn(b'Saved the default template', body)
		r, body = self.get('/pdf?name=' + j['name'])
		self.assertIn(b'Hello Sir or Madam, re Delvnote', body)
		location, body = self.post_redirect('/settings/templates', kind='default', action='revert')
		self.assertIn(b'Reverted to the shipped default template', body)
		r, body = self.get('/pdf?name=' + j['name'])
		self.assertDefaultBody(body, 'Sir or Madam')

	def test_the_old_single_email_text_is_migrated_once_at_startup(self):
		import contextlib
		j = self.send_invoice('Delvnote')
		# the old text lives in email.pickle, which recover() reads back at startup
		main.email_template = 'Please find it attached.\r\n\r\nRegards,\r\nTony Page'
		try:
			with contextlib.redirect_stdout(io.StringIO()):
				main.saveEmails()
				main.jobs.clear(); main.recover()
			r, body = self.get('/pdf?name=' + j['name'])
			self.assertIn(b'Please find it attached.\n\nRegards,\nTony Page', body)
			self.assertSubjectBox(body, self.DEFAULT_SUBJECT_PATTERN)
			with open(emailtemplates.seed_path('default'), encoding='utf-8') as f:
				shipped_subject_line = f.readline().rstrip('\n')
			with open(emailtemplates.user_path('default'), encoding='utf-8') as f:
				self.assertEqual(shipped_subject_line + '\n\nPlease find it attached.\n\nRegards,\nTony Page\n', f.read())
			# reverting is not undone by the next restart
			self.post('/settings/templates', kind='default', action='revert')
			with contextlib.redirect_stdout(io.StringIO()):
				main.jobs.clear(); main.recover()
			self.assertFalse(os.path.exists(emailtemplates.user_path('default')))
		finally:
			main.email_template = ''
			with contextlib.redirect_stdout(io.StringIO()):
				main.saveEmails()

	def test_the_old_default_text_editor_is_gone(self):
		r, body = self.get('/settings/template')
		self.assertEqual(404, r.status)
		r, body = self.get('/home')
		self.assertNotIn(b'Default Email Text', body)
		self.assertIn(b'/settings/templates', body)

	def test_sent_items_shows_only_the_latest_100(self):
		import datetime
		def fake(i):
			now = datetime.datetime(2026, 11, 19, 12, 0, 0)
			return dict(to=['a%d@x.com' % i], subject='subject-%d' % i, added=now, completed=now, error=None, status=None, body='', attachment='')
		original = list(mailer_results())
		try:
			mailer_results()[:] = [fake(i) for i in range(250)]                  # newest first, as the mail thread keeps it
			r, body = self.get('/sent')
			self.assertEqual(200, r.status)
			self.assertNotIn(b'Mako Runtime Error', body)
			self.assertEqual(100, len(re.findall(rb'<tr class="(?:success|error)">', body)))
			self.assertIn(b'subject-0<', body)
			self.assertIn(b'subject-99<', body)
			self.assertNotIn(b'subject-100<', body)
			self.assertIn(b'Showing the latest 100 of 250 sent emails.', body)
			# a history that fits is shown whole, with no note
			mailer_results()[:] = [fake(i) for i in range(3)]
			r, body = self.get('/sent')
			self.assertEqual(3, len(re.findall(rb'<tr class="(?:success|error)">', body)))
			self.assertNotIn(b'Showing the latest', body)
		finally:
			mailer_results()[:] = original

	def fake_sent(self, attachment, subject, to=('a@x.com',), error=None):
		import datetime
		now = datetime.datetime(2026, 11, 19, 12, 0, 0)
		return dict(to=list(to), subject=subject, added=now, completed=now, error=error, status=None, body='', attachment=attachment)

	def test_sent_items_link_to_the_job_and_the_job_lists_them(self):
		j = self.send_invoice(doc_num='777')
		other = self.send_invoice(doc_num='888')
		name = j['name']
		made_here = main.pdfdir + '2026/ACC001/%s-ACC001.pdf' % name
		long_gone = '/home/printerface/printerface/data/pdf/2015/OLD001/job-20150715-101010-OLD001.pdf'
		original = list(mailer_results())
		try:
			mailer_results()[:] = [                                        # newest first
				self.fake_sent(long_gone, 'sent long ago'),
				self.fake_sent(made_here, 'second mail', to=['ann@x.com', 'bob@x.com'], error='boom <b>'),
				self.fake_sent(made_here, 'first mail'),
				self.fake_sent('', 'no attachment'),
			]
			r, body = self.get('/sent')
			self.assertEqual(200, r.status)
			self.assertNotIn(b'Mako Runtime Error', body)
			self.assertEqual(2, body.count(('href="/pdf?name=%s&amp;key=ACC001"' % name).encode()))     # one link per email from the loaded job
			self.assertEqual(2, body.count(('>%s / ACC001</a>' % name).encode()))                       # the whole "job / key" is the link text
			self.assertIn(b'job-20150715-101010 / OLD001', body)                                       # the old job is named...
			self.assertNotIn(b'name=job-20150715-101010', body)                                        # ...but not linked
			self.assertLess(body.index(b'<th>Document</th>'), body.index(b'<th>To</th>'))              # Document is the first column
			self.assertIn(b'font-size: 11px', body)                                                    # the table is set small

			# the job page lists the emails made from it, and only those
			r, body = self.get('/pdf?name=%s&key=ACC001' % name)
			self.assertNotIn(b'Mako Runtime Error', body)
			self.assertIn(b'<h4>Sent from this job</h4>', body)
			self.assertIn(b'first mail', body)
			self.assertIn(b'second mail', body)
			self.assertLess(body.index(b'second mail'), body.index(b'first mail'))                      # newest first
			self.assertIn(b'ann@x.com, bob@x.com', body)
			self.assertIn(b'boom &lt;b&gt;', body)                                                      # escaped
			self.assertNotIn(b'sent long ago', body)
			# a job nothing was sent from has no such section
			r, body = self.get('/pdf?name=%s&key=ACC001' % other['name'])
			self.assertNotIn(b'Sent from this job', body)
		finally:
			mailer_results()[:] = original

	def test_several_invoices_for_one_account_make_one_email(self):
		# two invoices for one account in one print run, as for VAD101: one PDF, one email
		j = self.send_invoice(doc_nums=['777', '778'], totals=['\xa3569.73', '\xa344.92'])
		self.assertEqual(['777', '778'], [p['doc_num'] for p in j['parsed']['ACC001']])
		r, body = self.get('/pdf?name=%s&key=ACC001' % j['name'])
		self.assertNotIn(b'Mako Runtime Error', body)
		self.assertSubjectBox(body, 'New Invoices 777/8')
		page = body.decode('utf-8')
		self.assertRegex(page, r'Please find your latest invoices attached for account ACC001, for a total of \xa3614\.65:')
		self.assertRegex(page, r'777 +\xa3569\.73\n778 +\xa344\.92\n')
		self.assertNotIn('\xa344.92.', page)                              # not "for \xa344.92", the last invoice alone
		# the live update and the editor preview say the same
		answer = json.loads(self.get('/email_body?name=%s&key=ACC001' % j['name'])[1].decode())
		self.assertEqual('New Invoices 777/8', answer['subject'])
		self.assertIn('for a total of \xa3614.65', answer['body'])
		r, body = self.get('/settings/templates?kind=invoice&docnum=778')
		self.assertIn(b'<strong>Subject:</strong> New Invoices 777/8', body)
		self.assertIn(b'all.numbers', body)                                # the helper is listed in the editor

	# ---- anything that changes something is a POST, and redirects to a page that is safe to refresh

	def test_sending_an_email_is_a_post_that_redirects(self):
		from unittest import mock
		j = self.send_invoice()
		self.add_contact('ACC001', 'ann@x.com', 'Ann')
		fields = dict(name=j['name'], key='ACC001', action='send', subject='Hello there', emailbody='The text')
		with mock.patch.object(main.mailqueue, 'append') as append:
			# a GET carrying every send parameter only shows the page: it must never send
			r, body = self.get('/pdf?' + urllib.parse.urlencode(dict(fields, em='ann@x.com')))
			self.assertEqual(200, r.status)
			self.assertNotIn(b'Queued the email', body)
			append.assert_not_called()

			# the POST queues it once and answers with a redirect to the page
			r, data = self.post('/pdf', em=['ann@x.com'], **fields)
			self.assertEqual(303, r.status)
			self.assertEqual('0', r.getheader('Content-Length'))
			location = r.getheader('Location')
			self.assertEqual('/pdf?name=%s&key=ACC001&queued=1' % j['name'], location)
			append.assert_called_once()
			item = append.call_args[0][0]
			self.assertEqual((['ann@x.com'], 'Hello there', 'The text'), (item['to'], item['subject'], item['body']))
			self.assertTrue(item['attachment'].endswith('-ACC001.pdf'), item['attachment'])

			# the page it lands on says so; refreshing it (or following the link again) sends nothing more
			for _ in range(3):
				r, body = self.get(location)
				self.assertEqual(200, r.status)
				self.assertIn(b'Queued the email to 1 recipient.', body)
			append.assert_called_once()

	def test_a_refused_send_keeps_what_was_typed_and_who_was_ticked(self):
		from unittest import mock
		j = self.send_invoice()
		self.add_contact('ACC001', 'ann@x.com', 'Ann')
		self.add_contact('ACC001', 'bob@x.com', 'Bob')
		with mock.patch.object(main.mailqueue, 'append') as append:
			r, data = self.post('/pdf', name=j['name'], key='ACC001', action='send', em=['bob@x.com'], subject='x', emailbody='my own words')
			self.assertEqual(200, r.status)                                   # not a redirect: nothing happened, so say why here
			page = data.decode('utf-8')
			self.assertIn('Some fields missing or incomplete', page)
			self.assertIn('my own words', page)
			self.assertRegex(page, r'name="subject" placeholder="Subject" value="x"')
			self.assertRegex(page, r'value="bob@x.com" checked')
			self.assertNotRegex(page, r'value="ann@x.com" checked')
			append.assert_not_called()
			# no recipient at all is refused too
			r, data = self.post('/pdf', name=j['name'], key='ACC001', action='send', subject='Hello there', emailbody='text')
			self.assertEqual(200, r.status)
			append.assert_not_called()

	def test_printing_is_a_post_that_redirects(self):
		from unittest import mock
		j = self.send_invoice()
		with mock.patch.object(main, 'printFile') as printed:
			r, body = self.get('/print?name=%s&key=ACC001&printer=default' % j['name'])      # the old kind of link
			self.assertEqual(200, r.status)
			printed.assert_not_called()
			self.assertIn(b'printed from their', body)

			r, data = self.post('/print', name=j['name'], key='ACC001', printer='default')
			self.assertEqual(303, r.status)
			location = r.getheader('Location')
			self.assertEqual('/pdf?name=%s&key=ACC001&printed=default' % j['name'], location)
			printed.assert_called_once()
			self.assertTrue(printed.call_args[0][0].endswith('-ACC001.pdf'))
			self.assertEqual('default', printed.call_args[0][1])
			for _ in range(2):
				self.assertIn(b'Sent the document to printer default.', self.get(location)[1])
			printed.assert_called_once()
			# the job page offers printers through a POST form, not links
			r, body = self.get('/pdf?name=%s&key=ACC001' % j['name'])
			self.assertIn(b'<form id="printForm" method="post" action="/print"', body)
			self.assertNotIn(b'href="/print?', body)
			# and the menu offers the CUPS queues, never a made-up 'default' that lpr would reject
			self.assertIn(b'data-printer="OFFICE_MFP"', body)
			self.assertNotIn(b'data-printer="default"', body)
			# an unknown job prints nothing
			r, data = self.post('/print', name='job-19990101-000000', printer='default')
			self.assertEqual(200, r.status)
			printed.assert_called_once()

	def test_uploading_to_the_website_is_a_post_that_queues_every_document_in_the_pdf(self):
		sent = []
		async def start():
			main.uploadqueue.transport = lambda item, base, key: (sent.append((item, base, key)) or (201, '{}'))
			main.uploadqueue.start()
		j = self.send_invoice(pages=2, doc_nums=['501', '502'], totals=['72.00', '48.00'], net='60.00', vat='12.00')
		# not configured: no button, and a POST is refused with a reason
		self.assertNotIn(b'Upload to website', self.get('/pdf?name=%s&key=ACC001' % j['name'])[1])
		r, body = self.post('/pdf', name=j['name'], key='ACC001', action='upload')
		self.assertEqual(200, r.status)
		self.assertIn(b'not set up', body)
		with mock.patch.object(uploader, 'settings', lambda: ('https://stage.example/', 'tok')):
			self.thread.call(start())
			try:
				self.assertIn(b'Upload to website', self.get('/pdf?name=%s&key=ACC001' % j['name'])[1])
				r, data = self.post('/pdf', name=j['name'], key='ACC001', action='upload')
				self.assertEqual(303, r.status)
				self.assertEqual('/pdf?name=%s&key=ACC001&uploading=2' % j['name'], r.getheader('Location'))
				deadline = time.time() + 10
				while len(main.uploadqueue.log.for_job(j['name'])) < 2 and time.time() < deadline:
					time.sleep(0.05)
				self.assertEqual(['502', '501'], [rec['docnum'] for rec in main.uploadqueue.log.for_job(j['name'])])
				self.assertEqual({('https://stage.example/', 'tok')}, {(b, k) for _, b, k in sent})
				first = json.loads(sent[0][0]['payload'])
				self.assertEqual(('501', '60.00', '72.00'), (first['docnum'], first['total_net'], first['total_gross']))
				from pypdf import PdfReader
				self.assertEqual([1, 1], [len(PdfReader(io.BytesIO(i['pdf'])).pages) for i, _, _ in sent])    # one page each
				body = self.get('/pdf?name=%s&key=ACC001&uploading=2' % j['name'])[1]
				self.assertIn(b'Uploaded from this job', body)
				self.assertIn(b'>501 / ACC001</a>', body)
				self.assertIn(b'Queued 2 documents for the website', body)
				# other types of document have no button
				d = self.send_invoice(jtype='Delvnote')
				self.assertNotIn(b'Upload to website', self.get('/pdf?name=%s&key=ACC001' % d['name'])[1])
			finally:
				self.thread.call(main.uploadqueue.close())

	def test_web_uploads_settings_and_uploads_pages(self):
		from unittest import mock
		r, body = self.get('/settings/web')
		self.assertEqual(200, r.status)
		self.assertIn(b'not set', body)
		self.assertIn(b'Web Uploads', self.get('/home')[1])            # in the Settings menu
		self.assertIn(b'href="/uploads"', self.get('/home')[1])
		with mock.patch.object(uploader, 'settings', lambda: ('https://stage.example/', 'abcdefghijklmnopXYZ')):
			body = self.get('/settings/web')[1]
		self.assertIn(b'<a href="https://stage.example/" target="_blank" rel="noopener noreferrer"><code>https://stage.example/</code></a>', body)
		self.assertIn(b'****XYZ', body)
		self.assertNotIn(b'abcdefghijklmnop', body)
		with mock.patch.object(uploader, 'settings', lambda: ('https://stage.example/', 'short')):
			body = self.get('/settings/web')[1]
			self.assertIn(b'<code>****</code>', body)                    # too short to give any of it away
			self.assertNotIn(b'<code>short', body)
		j = self.send_invoice()
		main.uploadqueue.log.add(dict(job=j['name'], key='ACC001', kind='invoice', account='ACC001', docnum='777', added=datetime.now(), outcome='created', status=201, error=None))
		main.uploadqueue.log.add(dict(job='job-19990101-000000', key='ACC001', kind='statement', account='ACC002', docnum='st1', added=datetime.now(), outcome='failed', status=400, error='HTTP 400 bad'))
		body = self.get('/uploads')[1]
		self.assertIn(b'>777 / ACC001</a>', body)                        # a loaded job links to its page
		self.assertIn(b'st1 / ACC002', body)
		self.assertNotIn(b'job-19990101-000000&', body)
		self.assertIn(b'HTTP 400 bad', body)

	def test_documents_of_the_auto_upload_types_are_uploaded_on_arrival(self):
		sent = []
		async def start():
			main.uploadqueue.transport = lambda item, base, key: (sent.append(item) or (201, '{}'))
			main.uploadqueue.start()
		def wait_for(n):
			deadline = time.time() + 10
			while len(sent) < n and time.time() < deadline:
				time.sleep(0.05)
		def arrive(**kw):
			return self.send_invoice(pages=1, totals=['144.00'], net='120.00', vat='24.00', **kw)
		main.config.set('Web', 'auto_types', 'statement, invoice')
		self.addCleanup(main.config.set, 'Web', 'auto_types', '')
		self.assertIn(b'<strong>invoice</strong>', self.get('/settings/web')[1].replace(b'statement,', b''))
		with mock.patch.object(uploader, 'settings', lambda: ('https://stage.example/', 'tok')):
			self.thread.call(start())
			try:
				j = arrive(doc_num='6001')
				wait_for(1)
				self.assertEqual(['6001'], [i['docnum'] for i in sent])
				self.assertEqual('created', main.uploadqueue.log.for_job(j['name'])[0]['outcome'])
				self.send_invoice(jtype='Delvnote')             # not a listed kind
				arrive(doc_num='6002', jtype='Cr-note')         # a credit note: not listed either
				time.sleep(0.5)
				self.assertEqual(['6001'], [i['docnum'] for i in sent])
				main.config.set('Web', 'auto_types', '')
				arrive(doc_num='6003')
				time.sleep(0.5)
				self.assertEqual(['6001'], [i['docnum'] for i in sent])      # off when blank
			finally:
				self.thread.call(main.uploadqueue.close())

	def test_the_colouring_is_not_kept_but_the_debug_page_still_shows_it(self):
		j = self.send_invoice()
		self.assertNotIn('colouring', j)
		self.assertTrue(j['parsed'] and j['groupfiles'])                # the PDFs are made from the parsed pages alone
		r, body = self.get('/debug?name=%s' % j['name'])
		self.assertEqual(200, r.status)
		self.assertIn(b'background-color: #', body)                     # the fields are coloured in
		self.assertIn(b'title="doc_num"', body)
		d = self.send_invoice(jtype='Delvnote')
		self.assertNotIn('colouring', d)
		raw = self.send_invoice(jtype='Mystery')                        # nothing recognises it: plain PDF, no colouring
		self.assertFalse(raw['parsed'])
		self.assertEqual(200, self.get('/debug?name=%s' % raw['name'])[0].status)

	def reload_raw(self, j):
		"""The job as it is when read back from its pickle at startup, before cleanJob."""
		for root, dirs, files in os.walk(main.jobdir):
			if j['name'] in files:
				p = os.path.join(root, j['name'])
				with open(p, 'rb') as f:
					raw = main.load_job_pickle(f)
				raw['name'], raw['stat'] = j['name'], main.file_stat(p)
				return raw

	def test_a_job_with_a_good_cache_entry_is_not_parsed_or_drawn_again(self):
		j = self.send_invoice(pages=1, totals=['144.00'], net='120.00', vat='24.00')
		main.derivedcache.dirty = True
		main.derivedcache.flush(main.jobs, force=True)
		cache = derived.DerivedCache(main.derivedcache.path)         # as read at the next start
		raw = self.reload_raw(j)
		with mock.patch.object(main.mainparser, 'parse', side_effect=AssertionError('parsed')), \
				mock.patch.object(main.formatter, 'format', side_effect=AssertionError('drawn')):
			self.assertEqual('hit', main.cleanJob(raw, cache.lookup(raw['name'], raw['stat'])))
		for key in ('parsed', 'groupkey', 'groupfiles', 'render_stamp', 'summary', 'doctype', 'templ', 'plain', 'autoprint'):
			self.assertEqual(j[key], raw[key], key)
		self.assertIn('ACC001', main.email_accounts)                  # the address book is still filled in from the cached pages

		# a PDF that has gone is drawn again, from the cached pages
		os.remove(main.pdfdir + next(iter(raw['groupfiles'].values())))
		raw2 = self.reload_raw(j)
		with mock.patch.object(main.mainparser, 'parse', side_effect=AssertionError('parsed')):
			self.assertEqual('drawn', main.cleanJob(raw2, cache.lookup(raw2['name'], raw2['stat'])))
		self.assertTrue(os.path.exists(main.pdfdir + next(iter(raw2['groupfiles'].values()))))

		# a job file that is not the one the entry was made from is parsed again
		raw3 = self.reload_raw(j)
		self.assertIsNone(cache.lookup(raw3['name'], (raw3['stat'][0] + 1, raw3['stat'][1])))
		self.assertEqual('parsed', main.cleanJob(raw3, None))
		self.assertEqual(j['parsed'], raw3['parsed'])

	def test_stationery_page_redraws_jobs_drawn_under_older_stationery(self):
		j = self.send_invoice(pages=1, totals=['144.00'], net='120.00', vat='24.00')
		self.assertEqual(main.derivedcache.render_stamp, j['render_stamp'])
		self.assertIn(b'were drawn under today', self.get('/settings/stationery')[1])
		old = config_terms = main.config.get('Printing', 'terms')
		main.config.set('Printing', 'terms', old + ' (changed)')
		self.addCleanup(main.config.set, 'Printing', 'terms', old)
		main.derivedcache.render_stamp = derived.render_stamp()      # what the next start would see
		self.addCleanup(setattr, main.derivedcache, 'render_stamp', derived.render_stamp())
		body = self.get('/settings/stationery')[1]
		self.assertIn(b'were drawn under older stationery', body)
		self.assertIn(b'Draw them again', body)
		self.assertIn(b'href="/settings/stationery"', self.get('/home')[1])
		pdf = main.pdfdir + next(iter(j['groupfiles'].values()))
		before = os.path.getmtime(pdf)
		time.sleep(0.05)
		r, data = self.post('/settings/stationery')                   # no button: nothing happens
		self.assertEqual(303, r.status)
		self.assertEqual(before, os.path.getmtime(pdf))
		r, data = self.post('/settings/stationery', regenerate='1')
		self.assertEqual(303, r.status)
		self.assertRegex(r.getheader('Location'), r'redrawn=\d+')
		self.assertGreater(os.path.getmtime(pdf), before)
		self.assertEqual(main.derivedcache.render_stamp, j['render_stamp'])
		body = self.get(r.getheader('Location'))[1]
		self.assertIn(b'again.', body)
		self.assertIn(b'were drawn under today', body)
		self.assertTrue(main.derivedcache.dirty)                       # the new stamps are written at the next flush

	def test_print_history_is_listed_on_the_job_page(self):
		j = self.send_invoice()
		self.assertNotIn(b'Printed from this job', self.get('/pdf?name=%s&key=ACC001' % j['name'])[1])
		printing.printlog.add({'job': j['name'], 'key': 'ACC001', 'file': 'x', 'printer': 'OFFICE_MFP',
			'request_id': 'OFFICE_MFP-777', 'added': datetime.now(), 'error': None})
		printing.printlog.add({'job': j['name'], 'key': 'accounts', 'file': 'x', 'printer': 'OFFICE_MFP',
			'request_id': None, 'added': datetime.now(), 'error': 'lp: <bad>'})
		printing.printlog.add({'job': 'job-19990101-000000', 'key': 'ACC001', 'file': 'x', 'printer': 'OTHER',
			'request_id': 'OTHER-1', 'added': datetime.now(), 'error': None})
		body = self.get('/pdf?name=%s&key=ACC001' % j['name'])[1]
		self.assertIn(b'Printed from this job', body)
		self.assertIn(b'OFFICE_MFP-777', body)
		self.assertIn(b'lp: &lt;bad&gt;', body)
		self.assertNotIn(b'OTHER-1', body)

	def test_printed_items_page(self):
		j = self.send_invoice()
		for job, req, err in [(j['name'], 'OFFICE_MFP-778', None), ('job-19990101-000000', None, 'lp: <bad>')]:
			printing.printlog.add({'job': job, 'key': 'ACC001', 'file': 'x', 'printer': 'OFFICE_MFP',
				'request_id': req, 'added': datetime.now(), 'error': err})
		r, body = self.get('/printed')
		self.assertEqual(200, r.status)
		self.assertIn(b'<th>Document</th><th>Printer</th><th>ID</th><th>Problems?</th>', body)
		self.assertIn(('href="/pdf?name=%s&amp;key=ACC001"' % j['name']).encode(), body)    # loaded: linked
		self.assertIn(b'OFFICE_MFP-778', body)
		self.assertIn(b'lp: &lt;bad&gt;', body)
		self.assertNotIn(b'name=job-19990101-000000', body)                                  # no longer loaded: not linked
		self.assertIn(b'<a href="/printed">Printed Documents</a>', body)

	def test_a_refused_print_says_why(self):
		j = self.send_invoice()
		with mock.patch.object(main, 'printFile', side_effect=printing.PrintError('lp: no such queue <x>')):
			r, body = self.post('/print', name=j['name'], key='ACC001', printer='nope')
		self.assertEqual(200, r.status)
		self.assertIn(b'was not printed: lp: no such queue &lt;x&gt;', body)

	def test_the_address_book_only_changes_on_a_post(self):
		self.send_invoice()
		# a GET with add or delete parameters (an old link, a bookmark, a refresh) changes nothing
		self.get('/settings/email?account=ACC001&email=ann%40x.com&contact=Ann')
		self.assertEqual({}, dict(main.email_addresses.get('ACC001', {})))
		self.add_contact('ACC001', 'ann@x.com', 'Ann')
		self.get('/settings/email?account=ACC001&delete=ann%40x.com')
		self.assertEqual({'ann@x.com': 'Ann'}, main.email_addresses['ACC001'])
		# adding the same contact again (a refreshed POST) changes nothing either
		self.add_contact('ACC001', 'ann@x.com', 'Ann')
		self.assertEqual({'ann@x.com': 'Ann'}, main.email_addresses['ACC001'])
		# an unknown account is reported on the page the redirect lands on, escaped
		location, body = self.post_redirect('/settings/email', account='NOPE<b>', email='z@x.com', contact='Z')
		self.assertEqual('/settings/email?warning=Unknown+account+NOPE%3Cb%3E', location)
		self.assertIn(b'Unknown account NOPE&lt;b&gt;', body)
		self.assertNotIn(b'NOPE<b>', body)
		self.assertNotIn('NOPE<b>', main.email_addresses)
		# removing it takes a POST
		self.post_redirect('/settings/email', account='ACC001', delete='ann@x.com')
		self.assertEqual({}, main.email_addresses['ACC001'])
		# the forms on the page post
		r, body = self.get('/settings/email')
		self.assertNotIn(b'method="get" class="form-inline"', body)
		self.assertIn(b'method="post" class="form-inline" action="/settings/email"', body)

	def test_the_template_editor_ignores_actions_that_arrive_by_get(self):
		self.send_invoice()
		path = emailtemplates.user_path('invoice')
		r, body = self.get('/settings/templates?kind=invoice&action=save&template=Hijacked')
		self.assertEqual(200, r.status)
		self.assertFalse(os.path.exists(path))
		emailtemplates.save('invoice', 'mine')
		r, body = self.get('/settings/templates?kind=invoice&action=revert')
		self.assertTrue(os.path.exists(path))
		# the flash notes are only notes
		r, body = self.get('/settings/templates?kind=invoice&saved=1')
		self.assertIn(b'Saved the invoice template', body)
		self.assertTrue(os.path.exists(path))
		# a save that is refused is shown straight away with what was typed, not redirected
		r, body = self.post('/settings/templates', kind='invoice', action='save', template='${__import__("os")}')
		self.assertEqual(200, r.status)
		self.assertIn(b'__import__', body)

	def test_delivery_notes_are_auto_printed(self):
		j = self.send_invoice('Delvnote')
		self.assertEqual(main.config.get('Robot', 'auto_printer'), j['autoprint'])
		self.printed.assert_called_once()
		path, printer = self.printed.call_args[0]
		self.assertEqual(main.config.get('Robot', 'auto_printer'), printer)
		self.assertTrue(path.startswith(main.pdfdir) and path.endswith('.pdf'), path)
		# an invoice is not an auto-print type
		self.printed.reset_mock()
		self.send_invoice('Invoice')
		self.printed.assert_not_called()

	def test_a_printing_failure_does_not_lose_the_job(self):
		# without lpr (a container, a CI runner) or with CUPS down, printing raises; the job must still be there
		self.printed.side_effect = FileNotFoundError(2, 'No such file or directory', 'lpr')
		try:
			j = self.send_invoice('Delvnote')
		finally:
			self.printed.side_effect = None
		self.assertEqual(1, len(main.jobs))
		self.assertEqual(j['name'], main.jobs[0]['name'])
		self.printed.assert_called_once()
		r, body = self.get('/pdf?name=' + j['name'])                          # it can be opened, emailed and so on
		self.assertEqual(200, r.status)
		self.assertNotIn(b'Mako Runtime Error', body)
		r, body = self.get('/recent?fmt=json')
		self.assertIn(j['name'], body.decode())
		with open(os.path.join(main.jobdir, j['name'][4:10], j['name']), 'rb') as f:          # and it was saved to disk
			self.assertTrue(f.read(2) == b'\x80\x02')

	def test_pdf_page_for_a_job_that_is_not_loaded_is_a_message_not_an_error(self):
		self.send_invoice()
		r, body = self.get('/pdf?name=job-19990101-000000')
		self.assertEqual(200, r.status)
		self.assertNotIn(b'Mako Runtime Error', body)
		self.assertNotIn(b'Traceback', body)
		self.assertIn(b'There is no job job-19990101-000000 loaded', body)
		self.assertIn(b'href="/recent"', body)
		r, body = self.get('/pdf?name=%3Cb%3Ex%3C/b%3E')                                                # the name is echoed back, escaped
		self.assertEqual(200, r.status)
		self.assertIn(b'&lt;b&gt;x&lt;/b&gt;', body)
		self.assertNotIn(b'<b>x</b>', body)
		r, body = self.get('/pdf')
		self.assertEqual(200, r.status)
		self.assertIn(b'(none given)', body)
		main.jobs.clear()
		r, body = self.get('/pdf?name=job-19990101-000000')                                              # even with nothing loaded at all
		self.assertEqual(200, r.status)

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
