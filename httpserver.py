"""
The web server, on aiohttp.

Pages are plain functions registered by path (`pathhandlers`), the same ones the asyncore server called:
`handler(query_string=..., resp=...)` for GET and HEAD and `handler(query_string=..., postreq=...)` for POST,
where the query string and the form fields arrive as {name: [values]}. A handler returns `(body, content type)`,
with body a str, bytes or binary file object, or a `Redirect`; raising `NotFound` answers 404. Anything else is served as a file from the
web root.

Handlers run on the event loop, one at a time, exactly as before: they and the LPD receiver share one thread, so
the job list and the other data they touch need no locking. A handler that blocks (printing, rendering a big
PDF) holds up everything else for its duration, and that is deliberate, not an oversight.
"""

import asyncio
import io
import mimetypes
import os
import posixpath
import sys
import time
import traceback
import urllib.parse
from email.utils import formatdate

from aiohttp import web

# bodies we generate are utf-8
BODY_ENCODING = 'utf-8'

# a form post (an email body, a template) is small; this only stops a runaway client
MAX_REQUEST_BYTES = 16 * 1024 * 1024


class NotFound(Exception):
	"""A path handler raises this to answer 404, for a thing that is not there (a file it was asked for by name)."""


class Redirect(object):
	"""A path handler returns this instead of (body, content type) to answer with a redirect. It is a 303 See
	Other, so the browser fetches the location with GET: after handling a POST this means the page the user ends
	up on can be refreshed without repeating the POST."""
	def __init__(self, location):
		self.location = location


def _body_file(f, ctype):
	"""Normalise whatever a path handler returned into (binary file object, content type).
	Handlers return str (json, plain), bytes (mako output, pdf) or a binary file object."""
	if isinstance(f, str):
		f = f.encode(BODY_ENCODING)
	if isinstance(f, (bytes, bytearray)):
		f = io.BytesIO(f)
	if ctype.startswith('text/') and 'charset' not in ctype:
		ctype += '; charset=' + BODY_ENCODING
	return f, ctype


if not mimetypes.inited:
	mimetypes.init()  # try to read system mime.types
extensions_map = mimetypes.types_map.copy()
extensions_map.update({
	'': 'application/octet-stream',  # Default
	'.py': 'text/plain',
	'.c': 'text/plain',
	'.h': 'text/plain',
})


def guess_type(path):
	base, ext = posixpath.splitext(path)
	return extensions_map.get(ext) or extensions_map.get(ext.lower()) or extensions_map['']


class ResponseGatherer(object):
	"""What a GET handler is given to add response headers to (a download's Content-Disposition)."""
	def __init__(self):
		self.headers = []

	def add_header(self, key, value):
		self.headers.append((key, value))


class HttpServer(object):
	"""Serves pathhandlers and the files under webroot. Use as `await server.start()`; `server.port` is the
	port actually bound (pass port=0 to be given one)."""

	def __init__(self, pathhandlers, webroot, ip='', port=8081):
		self.handlers = pathhandlers
		self.webroot = webroot
		self.ip = ip
		self.port = port
		self.runner = None

	async def start(self):
		app = web.Application(client_max_size=MAX_REQUEST_BYTES)
		app.router.add_route('*', '/{tail:.*}', self._handle)
		self.runner = web.AppRunner(app, access_log=None)
		await self.runner.setup()
		site = web.TCPSite(self.runner, self.ip or None, self.port, backlog=100)
		await site.start()
		self.port = self.runner.addresses[0][1]
		print("[httpd] aiohttp running on port %s, serving from %s" % (self.port, self.webroot))
		return self

	async def close(self):
		if self.runner:
			await self.runner.cleanup()

	def log(self, request, status, size):
		peer = request.transport.get_extra_info('peername') if request.transport else None
		peer = peer or ('-', 0)
		print('[httpd-%d] %s %s "%s %s HTTP/%d.%d" %s %s' % (peer[1], time.strftime('%d/%b/%Y %H:%M:%S'), peer[0],
			request.method, request.raw_path, request.version.major, request.version.minor, status, size))

	def reply(self, request, status, body=b'', headers=None):
		response = web.Response(status=status, body=body, headers=headers)
		self.log(request, status, len(body) if body else '-')
		return response

	def error(self, request, status, message):
		page = ('<html><head><title>%d %s</title></head><body><h1>%d %s</h1></body></html>' % (
			status, message, status, message)).encode(BODY_ENCODING)
		return self.reply(request, status, page, {'Content-Type': 'text/html; charset=' + BODY_ENCODING})

	async def _handle(self, request):
		path = request.path
		query_string = urllib.parse.parse_qs(request.rel_url.raw_query_string)
		handler = self.handlers.get(path)
		if request.method == 'POST':
			if not handler:
				return self.error(request, 404, 'Not Found')
			# only urlencoded form bodies are understood; fields arrive as {name: [values]}, like query_string
			body = (await request.read()).decode(BODY_ENCODING, 'replace')
			postreq = urllib.parse.parse_qs(body, keep_blank_values=True)
			return self.run_handler(request, handler, dict(query_string=query_string, postreq=postreq))
		if request.method not in ('GET', 'HEAD'):
			return self.error(request, 501, 'Unsupported method (%r)' % request.method)
		if handler:
			gatherer = ResponseGatherer()
			return self.run_handler(request, handler, dict(query_string=query_string, resp=gatherer), gatherer)
		return self.static(request, path)

	def run_handler(self, request, handler, kwargs, gatherer=None):
		try:
			result = handler(**kwargs)
			if isinstance(result, Redirect):
				return self.reply(request, 303, b'', {'Location': result.location})
			(f, ctype) = _body_file(*result)
			headers = dict(gatherer.headers) if gatherer else {}
			headers['Content-Type'] = ctype
			body = f.read()
			f.close()
			return self.reply(request, 200, body, headers)
		except NotFound:
			return self.error(request, 404, 'Not Found')
		except Exception:
			print(traceback.format_exc())
			return self.error(request, 500, 'Internal Server Error')

	def translate_path(self, path):
		"""The file under the web root for a /-separated URL path. Components that mean something to the
		file system (drives, '..') are ignored, so a request can't leave the web root."""
		path = posixpath.normpath(urllib.parse.unquote(path))
		result = self.webroot
		for word in [w for w in path.split('/') if w]:
			drive, word = os.path.splitdrive(word)
			head, word = os.path.split(word)
			if word in (os.curdir, os.pardir):
				continue
			result = os.path.join(result, word)
		return result

	def static(self, request, urlpath):
		path = self.translate_path(urlpath)
		if os.path.isdir(path):
			if not urlpath.endswith('/'):
				# redirect browser - doing basically what apache does
				return self.reply(request, 301, b'', {'Location': urlpath + '/'})
			for index in ('index.html', 'index.htm'):
				if os.path.exists(os.path.join(path, index)):
					path = os.path.join(path, index)
					break
			else:
				return self.error(request, 404, 'Not Found')
		try:
			# binary, so that newline translation can't change the size of what is sent
			with open(path, 'rb') as f:
				body = f.read()
				mtime = os.fstat(f.fileno()).st_mtime
		except OSError:
			return self.error(request, 404, 'Not Found')
		return self.reply(request, 200, body, {'Content-Type': guess_type(path), 'Last-Modified': formatdate(mtime, usegmt=True)})


if __name__=="__main__":

	def about(query_string='', resp=None):
		return ("hi %s" % query_string, 'text/plain')

	async def main():
		# launch the server on the specified port
		await HttpServer({'/about': about}, os.getcwd(), port=8081).start()
		await asyncio.Event().wait()

	try:
		asyncio.run(main())
	except KeyboardInterrupt:
		print("Crtl+C pressed. Shutting down.")
