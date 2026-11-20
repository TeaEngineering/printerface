# The LPD receiver and the web server on their own, without main.py: protocol behaviour that the end to end
# tests in test_integration.py take for granted.
import asyncio
import http.client
import os
import socket
import tempfile
import threading
import unittest

from httpserver import HttpServer, Redirect
from lpdserver import LpdServer


class LoopThread(object):
	def __init__(self):
		self.loop = asyncio.new_event_loop()
		self.thread = threading.Thread(target=lambda: (asyncio.set_event_loop(self.loop), self.loop.run_forever()), daemon=True)
		self.thread.start()

	def call(self, coro):
		return asyncio.run_coroutine_threadsafe(coro, self.loop).result(10)

	def stop(self):
		self.loop.call_soon_threadsafe(self.loop.stop)
		self.thread.join()
		self.loop.close()


class TestLpd(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.loop = LoopThread()
		cls.received = []
		cls.controller_fails = False

		def controller(queue, peer, local, control, data):
			if cls.controller_fails:
				raise RuntimeError('boom')
			cls.received.append((queue, control, data))
		cls.server = cls.loop.call(LpdServer(controller, ip='127.0.0.1', port=0).start())

	@classmethod
	def tearDownClass(cls):
		cls.loop.call(cls.server.close())
		cls.loop.stop()

	def setUp(self):
		del self.received[:]
		type(self).controller_fails = False

	def connect(self):
		s = socket.create_connection(('127.0.0.1', self.server.port), timeout=5)
		self.addCleanup(s.close)
		return s

	def ack(self, s):
		self.assertEqual(b'\x00', s.recv(1), 'no ack')

	def to_data_file(self, s, queue=b'q', control=b'Hhost\nPuser\n', size=None, size_of=None):
		s.sendall(b'\x02' + queue + b'\n'); self.ack(s)
		s.sendall(b'\x02%d cfA001host\n' % len(control)); self.ack(s)
		s.sendall(control + b'\x00'); self.ack(s)

	def wait_for(self, n):
		for _ in range(100):
			if len(self.received) >= n:
				return
			threading.Event().wait(0.02)
		self.fail('job not received')

	def test_well_formed_job_keeps_its_trailing_null(self):
		s = self.connect()
		self.to_data_file(s)
		s.sendall(b'\x03%d dfA001host\n' % 6); self.ack(s)
		s.sendall(b'hello\n\x00'); self.ack(s)
		self.assertEqual(b'', s.recv(1))          # the server closes after the data file
		self.wait_for(1)
		self.assertEqual([('q', {'H': 'host', 'P': 'user'}, 'hello\n\x00')], self.received)

	def test_sender_that_closes_to_mark_the_end(self):
		s = self.connect()
		self.to_data_file(s)
		s.sendall(b'\x03%d dfA001host\n' % 0x7fffffff); self.ack(s)
		s.sendall(b'caf\xe9 \x0c\n')
		s.shutdown(socket.SHUT_WR)
		self.assertEqual(b'\x00', s.recv(1))
		self.wait_for(1)
		self.assertEqual('caf\xe9 \x0c\n', self.received[0][2])      # one byte, one character

	def test_sender_that_vanishes_after_the_data_still_gets_its_job_kept(self):
		s = self.connect()
		self.to_data_file(s)
		s.sendall(b'\x03%d dfA001host\n' % 0x7fffffff); self.ack(s)
		s.sendall(b'abc')
		s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b'\x01\x00\x00\x00\x00\x00\x00\x00')    # RST on close
		s.close()
		self.wait_for(1)
		self.assertEqual('abc', self.received[0][2])

	def test_a_job_cut_off_before_its_data_is_dropped(self):
		s = self.connect()
		self.to_data_file(s)
		s.close()
		threading.Event().wait(0.3)
		self.assertEqual([], self.received)

	def test_a_failing_controller_does_not_stop_the_server(self):
		type(self).controller_fails = True
		s = self.connect()
		self.to_data_file(s)
		s.sendall(b'\x03%d dfA001host\n' % 1); self.ack(s)
		s.sendall(b'x\x00'); self.ack(s)
		self.assertEqual(b'', s.recv(1))
		type(self).controller_fails = False
		s = self.connect()
		self.to_data_file(s)
		s.sendall(b'\x03%d dfA001host\n' % 1); self.ack(s)
		s.sendall(b'y\x00'); self.ack(s)
		self.wait_for(1)
		self.assertEqual('y\x00', self.received[0][2])

	def test_unknown_commands_are_ignored(self):
		s = self.connect()
		s.sendall(b'\x09nonsense\n')                  # not acknowledged, and not fatal
		self.to_data_file(s)
		s.sendall(b'\x07what\n')                      # an unknown subcommand between files
		s.sendall(b'\x03%d dfA001host\n' % 1); self.ack(s)
		s.sendall(b'z\x00'); self.ack(s)
		self.wait_for(1)

	def test_two_senders_at_once(self):
		a, b = self.connect(), self.connect()
		self.to_data_file(a, queue=b'A')
		self.to_data_file(b, queue=b'B')
		for s, text in ((b, b'bb\x00'), (a, b'aa\x00')):
			s.sendall(b'\x03%d dfA001host\n' % 2); self.ack(s)
			s.sendall(text); self.ack(s)
		self.wait_for(2)
		self.assertEqual({('A', 'aa\x00'), ('B', 'bb\x00')}, {(q, d) for q, c, d in self.received})


class TestHttp(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.webroot = tempfile.mkdtemp(prefix='printerface-web-')
		cls.addClassCleanup(lambda: __import__('shutil').rmtree(cls.webroot, ignore_errors=True))
		os.makedirs(os.path.join(cls.webroot, 'css'))
		os.makedirs(os.path.join(cls.webroot, 'withindex'))
		with open(os.path.join(cls.webroot, 'css', 'x.css'), 'wb') as f:
			f.write(b'body { color: red }\n')
		with open(os.path.join(cls.webroot, 'withindex', 'index.html'), 'wb') as f:
			f.write(b'<p>index</p>')
		with open(os.path.join(os.path.dirname(cls.webroot), 'outside.txt'), 'wb') as f:
			f.write(b'secret')
		cls.addClassCleanup(lambda: os.remove(os.path.join(os.path.dirname(cls.webroot), 'outside.txt')))
		cls.seen = {}

		def echo(query_string=None, resp=None, postreq=None):
			cls.seen = dict(query=query_string, post=postreq)
			if postreq is not None:
				return Redirect('/echo?done=1')
			resp.add_header('X-Extra', 'yes')
			return ('caf\xe9 %s' % query_string, 'text/plain')

		def broken(query_string=None, resp=None, postreq=None):
			raise RuntimeError('boom')

		def blob(query_string=None, resp=None):
			import io
			return (io.BytesIO(b'%PDF-1.4 data'), 'application/pdf')

		cls.loop = LoopThread()
		cls.server = cls.loop.call(HttpServer({'/echo': echo, '/broken': broken, '/blob': blob}, cls.webroot, ip='127.0.0.1', port=0).start())

	@classmethod
	def tearDownClass(cls):
		cls.loop.call(cls.server.close())
		cls.loop.stop()

	def request(self, method, path, body=None, headers=None):
		conn = http.client.HTTPConnection('127.0.0.1', self.server.port, timeout=5)
		conn.request(method, path, body=body, headers=headers or {})
		r = conn.getresponse()
		data = r.read()
		conn.close()
		return r, data

	def test_handler_get_with_query_string_and_extra_header(self):
		r, body = self.request('GET', '/echo?a=1&a=2&b=x%20y&empty=')
		self.assertEqual(200, r.status)
		self.assertEqual({'a': ['1', '2'], 'b': ['x y']}, self.seen['query'])         # blank values are dropped, as before
		self.assertEqual('yes', r.getheader('X-Extra'))
		self.assertEqual('text/plain; charset=utf-8', r.getheader('Content-Type'))
		self.assertEqual('caf\xe9', body.decode().split()[0])
		self.assertEqual(str(len(body)), r.getheader('Content-Length'))

	def test_head_has_the_headers_but_no_body(self):
		r, body = self.request('HEAD', '/echo')
		self.assertEqual((200, b''), (r.status, body))
		self.assertTrue(int(r.getheader('Content-Length')) > 0)

	def test_post_form_fields_and_redirect(self):
		r, body = self.request('POST', '/echo?from=url', 'name=a+b&name=c&empty=',
			{'Content-Type': 'application/x-www-form-urlencoded'})
		self.assertEqual(303, r.status)
		self.assertEqual('/echo?done=1', r.getheader('Location'))
		self.assertEqual({'name': ['a b', 'c'], 'empty': ['']}, self.seen['post'])
		self.assertEqual({'from': ['url']}, self.seen['query'])

	def test_file_object_bodies(self):
		r, body = self.request('GET', '/blob')
		self.assertEqual((200, b'%PDF-1.4 data', 'application/pdf'), (r.status, body, r.getheader('Content-Type')))

	def test_a_failing_handler_is_a_500_and_the_server_carries_on(self):
		self.assertEqual(500, self.request('GET', '/broken')[0].status)
		self.assertEqual(500, self.request('POST', '/broken', 'a=1')[0].status)
		self.assertEqual(200, self.request('GET', '/echo')[0].status)

	def test_unknown_paths_and_methods(self):
		self.assertEqual(404, self.request('GET', '/nothing')[0].status)
		self.assertEqual(404, self.request('POST', '/nothing', 'a=1')[0].status)
		self.assertEqual(501, self.request('DELETE', '/echo')[0].status)

	def test_static_files(self):
		r, body = self.request('GET', '/css/x.css')
		self.assertEqual((200, b'body { color: red }\n', 'text/css'), (r.status, body, r.getheader('Content-Type')))
		self.assertIsNotNone(r.getheader('Last-Modified'))
		self.assertEqual(b'<p>index</p>', self.request('GET', '/withindex/')[1])
		r, _ = self.request('GET', '/withindex')
		self.assertEqual((301, '/withindex/'), (r.status, r.getheader('Location')))
		self.assertEqual(404, self.request('GET', '/css/')[0].status)        # no directory listings

	def test_static_files_cannot_leave_the_web_root(self):
		for path in ('/../outside.txt', '/css/../../outside.txt', '/%2e%2e/outside.txt', '/..%2foutside.txt'):
			r, body = self.request('GET', path)
			self.assertNotEqual(b'secret', body, path)

	def test_keep_alive_serves_several_requests_on_one_connection(self):
		conn = http.client.HTTPConnection('127.0.0.1', self.server.port, timeout=5)
		for _ in range(3):
			conn.request('GET', '/echo')
			r = conn.getresponse()
			r.read()
			self.assertEqual(200, r.status)
		conn.close()


if __name__ == '__main__':
	unittest.main()
