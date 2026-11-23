# The website upload queue: the wire format against a throwaway local server, retry behaviour, and the record kept.
import asyncio
import email
import http.server
import json
import tempfile
import threading
import unittest
from unittest import mock

import uploader
from uploader import WebUploader, UploadLog


def item(docnum='100', kind='invoice'):
	return dict(job='job-20261102-090507', key='ACC1', kind=kind, account='ACC1', docnum=docnum, payload=json.dumps({'docnum': docnum}), pdf=b'%PDF-1.4 x')


class FakeSite(http.server.BaseHTTPRequestHandler):
	replies = []        # (status, body) taken in turn; the last one repeats
	seen = []

	def do_POST(self):
		body = self.rfile.read(int(self.headers['Content-Length']))
		FakeSite.seen.append((self.path, self.headers['Authorization'], self.headers['Content-Type'], body))
		status, text = FakeSite.replies[min(len(FakeSite.seen), len(FakeSite.replies)) - 1]
		self.send_response(status)
		self.send_header('Content-Type', 'application/json')
		self.end_headers()
		self.wfile.write(text.encode())

	def log_message(self, *a):
		pass


class TestWire(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.httpd = http.server.HTTPServer(('127.0.0.1', 0), FakeSite)
		threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
		cls.url = 'http://127.0.0.1:%d/' % cls.httpd.server_port

	@classmethod
	def tearDownClass(cls):
		cls.httpd.shutdown()
		cls.httpd.server_close()

	def setUp(self):
		FakeSite.replies, FakeSite.seen = [(201, '{}')], []
		self.log = UploadLog(None, limit=5)
		patch = mock.patch.object(uploader, 'settings', lambda: (self.url, 'secret'))
		patch.start()
		self.addCleanup(patch.stop)
		patch = mock.patch.object(uploader, 'RETRY_DELAYS', (0.01, 0.01))
		patch.start()
		self.addCleanup(patch.stop)

	def run_queue(self, *items):
		async def go():
			up = WebUploader(log=self.log)
			up.start()
			for i in items:
				up.append(i)
			await up.close(10)
		asyncio.run(go())

	def test_request_is_a_multipart_post_with_the_token(self):
		self.run_queue(item('100'), item('7', 'statement'))
		(path, auth, ctype, body), (spath, _, _, _) = FakeSite.seen
		self.assertEqual(('/api/ingest/invoice/', 'Token secret', '/api/ingest/statement/'), (path, auth, spath))
		msg = email.message_from_bytes(b'Content-Type: ' + ctype.encode() + b'\r\n\r\n' + body)
		parts = {p.get_param('name', header='content-disposition'): p for p in msg.get_payload()}
		self.assertEqual({'docnum': '100'}, json.loads(parts['payload'].get_payload(decode=True)))
		self.assertEqual(b'%PDF-1.4 x', parts['pdf'].get_payload(decode=True))

	def test_created_and_replaced_are_recorded(self):
		FakeSite.replies = [(201, '{}'), (200, '{}')]
		self.run_queue(item('1'), item('1'))
		self.assertEqual(['replaced', 'created'], [r['outcome'] for r in self.log.records])         # newest first
		self.assertEqual([None, None], [r['error'] for r in self.log.records])

	def test_a_refusal_is_final_and_says_why(self):
		FakeSite.replies = [(400, '{"date": ["bad"]}')]
		self.run_queue(item())
		(rec,) = self.log.records
		self.assertEqual(('failed', 400), (rec['outcome'], rec['status']))
		self.assertIn('bad', rec['error'])
		self.assertEqual(1, len(FakeSite.seen))                       # not retried
		self.assertNotIn('secret', repr(rec))

	def test_a_server_error_is_retried_then_succeeds(self):
		FakeSite.replies = [(503, '<html>'), (500, ''), (201, '{}')]
		self.run_queue(item())
		self.assertEqual(3, len(FakeSite.seen))
		self.assertEqual('created', self.log.records[0]['outcome'])

	def test_gives_up_after_the_last_retry(self):
		FakeSite.replies = [(502, '<html>')]
		self.run_queue(item())
		self.assertEqual(3, len(FakeSite.seen))
		self.assertEqual(('failed', 502), (self.log.records[0]['outcome'], self.log.records[0]['status']))
		self.assertNotIn('<html>', self.log.records[0]['error'])

	def test_an_unreachable_site_is_retried_and_reported(self):
		with mock.patch.object(uploader, 'settings', lambda: ('http://127.0.0.1:1/', 'secret')):
			self.run_queue(item())
		(rec,) = self.log.records
		self.assertEqual('failed', rec['outcome'])
		self.assertIn('could not reach', rec['error'])

	def test_the_next_document_goes_after_a_failure(self):
		FakeSite.replies = [(400, '{}'), (201, '{}')]
		self.run_queue(item('1'), item('2'))
		self.assertEqual(['created', 'failed'], [r['outcome'] for r in self.log.records])


class TestSettings(unittest.TestCase):
	def test_off_by_default(self):
		self.assertFalse(uploader.enabled())

	def test_needs_both_settings(self):
		with mock.patch.object(uploader, 'settings', lambda: ('https://x/', '')):
			self.assertFalse(uploader.enabled())
		with mock.patch.object(uploader, 'settings', lambda: ('https://x/', 'k')):
			self.assertTrue(uploader.enabled())


class TestLog(unittest.TestCase):
	def test_print_history_has_its_own_setting_too(self):
		import printing
		from settings import config
		self.assertEqual(200, printing.PrintLog(None).limit)               # the default
		config.set('Printing', 'result_count', '3')
		self.addCleanup(config.set, 'Printing', 'result_count', '200')
		self.assertEqual(3, printing.PrintLog(None).limit)

	def test_capped_by_the_web_setting_not_the_gmail_one(self):
		from settings import config
		config.set('Web', 'result_count', '2')
		self.addCleanup(config.set, 'Web', 'result_count', '120')
		log = UploadLog(None)
		for n in range(5):
			log.add(dict(job='j%d' % n, error=None))
		self.assertEqual(['j4', 'j3'], [r['job'] for r in log.records])

	def test_persisted_and_capped(self):
		with tempfile.TemporaryDirectory() as d:
			log = UploadLog(d + '/upload.pickle', limit=2)
			for n in range(3):
				log.add(dict(job='j%d' % n, error=None))
			log.flush()
			again = UploadLog(d + '/upload.pickle', limit=2)
			self.assertEqual(['j2', 'j1'], [r['job'] for r in again.records])
			self.assertEqual(['j2'], [r['job'] for r in again.for_job('j2')])


if __name__ == '__main__':
	unittest.main()
