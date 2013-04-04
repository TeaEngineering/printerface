"""
HTTP server based on the asyncore / asynchat framework

The hierchy of the built-in SimpleHTTPServer is mixed up with SocketServer
blocking/threading semantics, this class strips it back to work only with
asynchat.

"""

import asynchat, asyncore, socket, select, urllib
import posixpath, sys, cgi, cStringIO, os, traceback, shutil
import mimetools, time
import cgi
import mimetypes
try:
	from cStringIO import StringIO
except ImportError:
	from StringIO import StringIO

"""HTTP server base class.

Note: the class in this module doesn't implement any HTTP request; see
SimpleHTTPServer for simple implementations of GET, HEAD and POST
(including CGI scripts).  It does, however, optionally implement HTTP/1.1
persistent connections, as of version 0.3.

Contents:

- BaseHTTPRequestHandler: HTTP request handler base class
"""
__version__ = "0.3"

class CaseInsensitiveDict(dict):
	"""Dictionary with case-insensitive keys
	Replacement for the deprecated mimetools.Message class
	"""
	def __init__(self, infile, *args):
		self._ci_dict = {}
		lines = infile.readlines()
		for line in lines:
			k,v=line.split(":",1)
			self._ci_dict[k.lower()] = self[k] = v.strip()
		self.headers = self.keys()
	
	def getheader(self,key,default=""):
		return self._ci_dict.get(key.lower(),default)
	
	def get(self,key,default=""):
		return self._ci_dict.get(key.lower(),default)
	
	def __getitem__(self,key):
		return self._ci_dict[key.lower()]
	
	def __contains__(self,key):
		return key.lower() in self._ci_dict

# Default error message template
DEFAULT_ERROR_MESSAGE = """\
<head>
<title>Error response</title>
</head>
<body>
<h1>Error response</h1>
<p>Error code %(code)d.
<p>Message: %(message)s.
<p>Error code explanation: %(code)s = %(explain)s.
</body>
"""

DEFAULT_ERROR_CONTENT_TYPE = "text/html"

def _quote_html(html):
	return html.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

class BaseHTTPRequestHandler(asynchat.async_chat):

	# The Python system version, truncated to its first component.
	sys_version = "Python/" + sys.version.split()[0]

	# The server software version.  You may want to override this.
	# The format is multiple whitespace-separated strings,
	# where each string is of the form name[/version].
	server_version = "BaseHTTP/" + __version__

	# The default request version.  This only affects responses up until
	# the point where the request line is parsed, so it mainly decides what
	# the client gets back when sending a malformed request line.
	# Most web servers default to HTTP 0.9, i.e. don't send a status line.
	default_request_version = "HTTP/0.9"

	def parse_request(self, requestline):
		"""Parse a request (internal).
		the results are in self.command, self.path, self.request_version,
		self.headers and self.close_connection.

		Return True for success, False for failure; on failure a call to 
		send_error is made before returning.

		"""
		self.command = None  # set in case of error on the first line
		self.request_version = version = self.default_request_version
		self.close_connection = 1
		
		requestline = requestline.rstrip('\r\n')
		self.requestline = requestline
		words = requestline.split()
		if len(words) == 3:
			command, path, version = words
			if version[:5] != 'HTTP/':
				self.send_error(400, "Bad request version (%r)" % version)
				return False
			try:
				base_version_number = version.split('/', 1)[1]
				version_number = base_version_number.split(".")
				# RFC 2145 section 3.1 says there can be only one "." and
				#   - major and minor numbers MUST be treated as
				#	  separate integers;
				#   - HTTP/2.4 is a lower version than HTTP/2.13, which in
				#	  turn is lower than HTTP/12.3;
				#   - Leading zeros MUST be ignored by recipients.
				if len(version_number) != 2:
					raise ValueError
				version_number = int(version_number[0]), int(version_number[1])
			except (ValueError, IndexError):
				self.send_error(400, "Bad request version (%r)" % version)
				return False
			if version_number >= (1, 1) and self.protocol_version >= "HTTP/1.1":
				self.close_connection = 0
			if version_number >= (2, 0):
				self.send_error(505,
						  "Invalid HTTP Version (%s)" % base_version_number)
				return False
		elif len(words) == 2:
			command, path = words
			self.close_connection = 1
			if command != 'GET':
				self.send_error(400,
								"Bad HTTP/0.9 request type (%r)" % command)
				return False
		elif not words:
			return False
		else:
			self.send_error(400, "Bad request syntax (%r)" % requestline)
			return False
		self.command, self.path, self.request_version = command, path, version

		# Examine the headers and look for a Connection directive
		self.headers = CaseInsensitiveDict(self.rfile, 0)

		conntype = self.headers.get('Connection', "")
		if conntype.lower() == 'close':
			self.close_connection = 1
		elif (conntype.lower() == 'keep-alive' and
			  self.protocol_version >= "HTTP/1.1"):
			self.close_connection = 0
		return True


	def handle_one_request(self):
		"""Handle a single HTTP request.

		You normally don't need to override this method; see the class
		__doc__ string for information on how to handle specific HTTP
		commands such as GET and POST.

		"""
		try:
			raw_requestline = self.rfile.readline(65537)
			if len(raw_requestline) > 65536:
				self.send_error(414)
				return
			if not raw_requestline:
				self.close_connection = 1
				return
			if not self.parse_request(requestline):
				# An error code has been sent, just exit
				return
			mname = 'do_' + self.command
			if not hasattr(self, mname):
				self.send_error(501, "Unsupported method (%r)" % self.command)
				return
			method = getattr(self, mname)
			method()			
		except socket.timeout, e:
			#a read or a write timed out.  Discard this connection
			self.log_error("Request timed out: %r", e)
			self.close_connection = 1
			return

	def handle(self):
		"""Handle multiple requests if necessary."""
		self.close_connection = 1

		self.handle_one_request()
		while not self.close_connection:
			self.handle_one_request()

	def send_error(self, code, message=None):
		"""Send and log an error reply.

		Arguments are the error code, and a detailed message.
		The detailed message defaults to the short entry matching the
		response code.

		This sends an error response (so it must be called before any
		output has been generated), logs the error, and finally sends
		a piece of HTML explaining the error to the user.

		"""

		try:
			short, long = self.responses[code]
		except KeyError:
			short, long = '???', '???'
		if message is None:
			message = short
		explain = long
		self.log_error("code %d, message %s", code, message)
		# using _quote_html to prevent Cross Site Scripting attacks (see bug #1100201)
		content = (self.error_message_format %
				   {'code': code, 'message': _quote_html(message), 'explain': explain})
		self.send_response(code, message)
		self.send_header("Content-Type", self.error_content_type)
		self.send_header('Connection', 'close')
		self.end_headers()
		if self.command != 'HEAD' and code >= 200 and code not in (204, 304):
			self.push(content)

	error_message_format = DEFAULT_ERROR_MESSAGE
	error_content_type = DEFAULT_ERROR_CONTENT_TYPE

	def send_response(self, code, message=None):
		"""Send the response header and log the response code.

		Also send two standard headers with the server software
		version and the current date.

		"""
		self.log_request(code)
		if message is None:
			if code in self.responses:
				message = self.responses[code][0]
			else:
				message = ''
		if self.request_version != 'HTTP/0.9':
			self.push("%s %d %s\r\n" % (self.protocol_version, code, message))
			# print (self.protocol_version, code, message)
		self.send_header('Server', self.version_string())
		self.send_header('Date', self.date_time_string())

	def send_header(self, keyword, value):
		"""Send a MIME header."""
		if self.request_version != 'HTTP/0.9':
			self.push("%s: %s\r\n" % (keyword, value))

		if keyword.lower() == 'connection':
			if value.lower() == 'close':
				self.close_connection = 1
			elif value.lower() == 'keep-alive':
				self.close_connection = 0

	def end_headers(self):
		"""Send the blank line ending the MIME headers."""
		if self.request_version != 'HTTP/0.9':
			self.push("\r\n")

	def log_request(self, code='-', size='-'):
		"""Log requests, called by send_response(). """
		self.log_message('"%s" %s %s', self.requestline, str(code), str(size))

	def log_error(self, format, *args):
		"""Log an error.

		This is called when a request cannot be fulfilled.  By
		default it passes the message on to log_message().

		Arguments are the same as for log_message().

		XXX This should go to the separate error log.

		"""

		self.log_message(format, *args)

	def log_message(self, format, *args):
		"""Log an arbitrary message.

		This is used by all other logging functions.  Override
		it if you have specific logging wishes.

		The first argument, FORMAT, is a format string for the
		message to be logged.  If the format string contains
		any % escapes requiring parameters, they should be
		specified as subsequent arguments (it's just like
		printf!).

		The client host and current date/time are prefixed to
		every message.

		"""

		sys.stderr.write("%s - - [%s] %s\n" %
						 (self.address_string(),
						  self.log_date_time_string(),
						  format%args))

	def version_string(self):
		"""Return the server software version string."""
		return self.server_version + ' ' + self.sys_version

	def date_time_string(self, timestamp=None):
		"""Return the current date and time formatted for a message header."""
		if timestamp is None:
			timestamp = time.time()
		year, month, day, hh, mm, ss, wd, y, z = time.gmtime(timestamp)
		s = "%s, %02d %3s %4d %02d:%02d:%02d GMT" % (
				self.weekdayname[wd],
				day, self.monthname[month], year,
				hh, mm, ss)
		return s

	def log_date_time_string(self):
		"""Return the current time formatted for logging."""
		now = time.time()
		year, month, day, hh, mm, ss, x, y, z = time.localtime(now)
		s = "%02d/%3s/%04d %02d:%02d:%02d" % (
				day, self.monthname[month], year, hh, mm, ss)
		return s

	weekdayname = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

	monthname = [None,
				 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
				 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

	def address_string(self):
		"""Return the client address formatted for logging.

		This version looks up the full hostname using gethostbyaddr(),
		and tries to find a name that contains at least one dot.

		"""

		host, port = self.client_address[:2]
		return socket.getfqdn(host)

	# Essentially static class variables

	# The version of the HTTP protocol we support.
	# Set this to HTTP/1.1 to enable automatic keepalive
	protocol_version = "HTTP/1.1"

	# Table mapping response codes to messages; entries have the
	# form {code: (shortmessage, longmessage)}.
	# See RFC 2616.
	responses = {
		100: ('Continue', 'Request received, please continue'),
		101: ('Switching Protocols',
			  'Switching to new protocol; obey Upgrade header'),

		200: ('OK', 'Request fulfilled, document follows'),
		201: ('Created', 'Document created, URL follows'),
		202: ('Accepted',
			  'Request accepted, processing continues off-line'),
		203: ('Non-Authoritative Information', 'Request fulfilled from cache'),
		204: ('No Content', 'Request fulfilled, nothing follows'),
		205: ('Reset Content', 'Clear input form for further input.'),
		206: ('Partial Content', 'Partial content follows.'),

		300: ('Multiple Choices',
			  'Object has several resources -- see URI list'),
		301: ('Moved Permanently', 'Object moved permanently -- see URI list'),
		302: ('Found', 'Object moved temporarily -- see URI list'),
		303: ('See Other', 'Object moved -- see Method and URL list'),
		304: ('Not Modified',
			  'Document has not changed since given time'),
		305: ('Use Proxy',
			  'You must use proxy specified in Location to access this '
			  'resource.'),
		307: ('Temporary Redirect',
			  'Object moved temporarily -- see URI list'),

		400: ('Bad Request',
			  'Bad request syntax or unsupported method'),
		401: ('Unauthorized',
			  'No permission -- see authorization schemes'),
		402: ('Payment Required',
			  'No payment -- see charging schemes'),
		403: ('Forbidden',
			  'Request forbidden -- authorization will not help'),
		404: ('Not Found', 'Nothing matches the given URI'),
		405: ('Method Not Allowed',
			  'Specified method is invalid for this resource.'),
		406: ('Not Acceptable', 'URI not available in preferred format.'),
		407: ('Proxy Authentication Required', 'You must authenticate with '
			  'this proxy before proceeding.'),
		408: ('Request Timeout', 'Request timed out; try again later.'),
		409: ('Conflict', 'Request conflict.'),
		410: ('Gone',
			  'URI no longer exists and has been permanently removed.'),
		411: ('Length Required', 'Client must specify Content-Length.'),
		412: ('Precondition Failed', 'Precondition in headers is false.'),
		413: ('Request Entity Too Large', 'Entity is too large.'),
		414: ('Request-URI Too Long', 'URI is too long.'),
		415: ('Unsupported Media Type', 'Entity body in unsupported format.'),
		416: ('Requested Range Not Satisfiable',
			  'Cannot satisfy request range.'),
		417: ('Expectation Failed',
			  'Expect condition could not be satisfied.'),

		500: ('Internal Server Error', 'Server got itself in trouble'),
		501: ('Not Implemented',
			  'Server does not support this operation'),
		502: ('Bad Gateway', 'Invalid responses from another server/proxy.'),
		503: ('Service Unavailable',
			  'The server cannot process the request due to a high load'),
		504: ('Gateway Timeout',
			  'The gateway server did not receive a timely response'),
		505: ('HTTP Version Not Supported', 'Cannot fulfill request.'),
		}


"""Simple HTTP Server.

This module builds on BaseHTTPServer by implementing the standard GET
and HEAD requests in a fairly straightforward manner.

"""
class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):

	"""Simple HTTP request handler with GET and HEAD commands.

	This serves files from the current directory and any of its
	subdirectories.  The MIME type for files is determined by
	calling the .guess_type() method.

	The GET and HEAD requests are identical except that the HEAD
	request omits the actual contents of the file.

	"""

	server_version = "SimpleHTTP/" + __version__

	def do_GET(self):
		"""Serve a GET request."""
		f = self.send_head()
		if f:
			self.push(f.read())
			f.close()

	def do_HEAD(self):
		"""Serve a HEAD request."""
		f = self.send_head()
		if f:
			f.close()

	def send_head(self):
		"""Common code for GET and HEAD commands.

		This sends the response code and MIME headers.

		Return value is either a file object (which has to be copied
		to the outputfile by the caller unless the command was HEAD,
		and must be closed by the caller under all circumstances), or
		None, in which case the caller has nothing further to do.

		"""
		path = self.translate_path(self.path)
		f = None
		if os.path.isdir(path):
			if not self.path.endswith('/'):
				# redirect browser - doing basically what apache does
				self.send_response(301)
				self.send_header("Location", self.path + "/")
				self.end_headers()
				return None
			for index in "index.html", "index.htm":
				index = os.path.join(path, index)
				if os.path.exists(index):
					path = index
					break
			else:
				return self.list_directory(path)
		ctype = self.guess_type(path)
		try:
			# Always read in binary mode. Opening files in text mode may cause
			# newline translations, making the actual size of the content
			# transmitted *less* than the content-length!
			f = open(path, 'rb')
		except IOError:
			self.send_error(404, "File not found")
			return None
		self.send_response(200)
		self.send_header("Content-type", ctype)
		fs = os.fstat(f.fileno())
		self.send_header("Content-Length", str(fs[6]))
		self.send_header("Last-Modified", self.date_time_string(fs.st_mtime))
		self.end_headers()
		return f

	def list_directory(self, path):
		"""Helper to produce a directory listing (absent index.html).

		Return value is either a file object, or None (indicating an
		error).  In either case, the headers are sent, making the
		interface the same as for send_head().

		"""
		try:
			list = os.listdir(path)
		except os.error:
			self.send_error(404, "No permission to list directory")
			return None
		list.sort(key=lambda a: a.lower())
		f = StringIO()
		displaypath = cgi.escape(urllib.unquote(self.path))
		f.write('<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 3.2 Final//EN">')
		f.write("<html>\n<title>Directory listing for %s</title>\n" % displaypath)
		f.write("<body>\n<h2>Directory listing for %s</h2>\n" % displaypath)
		f.write("<hr>\n<ul>\n")
		for name in list:
			fullname = os.path.join(path, name)
			displayname = linkname = name
			# Append / for directories or @ for symbolic links
			if os.path.isdir(fullname):
				displayname = name + "/"
				linkname = name + "/"
			if os.path.islink(fullname):
				displayname = name + "@"
				# Note: a link to a directory displays with @ and links with /
			f.write('<li><a href="%s">%s</a>\n'
					% (urllib.quote(linkname), cgi.escape(displayname)))
		f.write("</ul>\n<hr>\n</body>\n</html>\n")
		length = f.tell()
		f.seek(0)
		self.send_response(200)
		encoding = sys.getfilesystemencoding()
		self.send_header("Content-type", "text/html; charset=%s" % encoding)
		self.send_header("Content-Length", str(length))
		self.end_headers()
		return f

	def translate_path(self, path):
		"""Translate a /-separated PATH to the local filename syntax.

		Components that mean special things to the local file system
		(e.g. drive or directory names) are ignored.  (XXX They should
		probably be diagnosed.)

		"""
		# abandon query parameters
		path = path.split('?',1)[0]
		path = path.split('#',1)[0]
		path = posixpath.normpath(urllib.unquote(path))
		words = path.split('/')
		words = filter(None, words)
		path = os.getcwd()
		for word in words:
			drive, word = os.path.splitdrive(word)
			head, word = os.path.split(word)
			if word in (os.curdir, os.pardir): continue
			path = os.path.join(path, word)
		return path

	def guess_type(self, path):
		"""Guess the type of a file.

		Argument is a PATH (a filename).

		Return value is a string of the form type/subtype,
		usable for a MIME Content-type header.

		The default implementation looks the file's extension
		up in the table self.extensions_map, using application/octet-stream
		as a default; however it would be permissible (if
		slow) to look inside the data to make a better guess.

		"""

		base, ext = posixpath.splitext(path)
		if ext in self.extensions_map:
			return self.extensions_map[ext]
		ext = ext.lower()
		if ext in self.extensions_map:
			return self.extensions_map[ext]
		else:
			return self.extensions_map['']

	if not mimetypes.inited:
		mimetypes.init() # try to read system mime.types
	extensions_map = mimetypes.types_map.copy()
	extensions_map.update({
		'': 'application/octet-stream', # Default
		'.py': 'text/plain',
		'.c': 'text/plain',
		'.h': 'text/plain',
		})
	
class RequestHandler(SimpleHTTPRequestHandler):

	def __init__(self,conn,addr):
		asynchat.async_chat.__init__(self,conn)
		
		self.client_address = addr
		self.id = "[httpd-%d]" % addr[1]
		
		# set the terminator : when it is received, this means that the
		# http request is complete ; control will be passed to
		# self.found_terminator
		self.reset_terminator();
			
	def reset_terminator(self):
		self.set_terminator ('\r\n\r\n')
		self.found_terminator = self.handle_request_line
		self.rfile = cStringIO.StringIO()
				
	def collect_incoming_data(self,data):
		self.rfile.write(data)

	def do_POST(self):
		"""Begins serving a POST request. The request data must be readable
		on a file-like object called self.rfile"""
		ctype, pdict = cgi.parse_header(self.headers.getheader('content-type'))
		self.body = cgi.FieldStorage(fp=self.rfile,
			headers=self.headers, environ = {'REQUEST_METHOD':'POST'},
			keep_blank_values = 1)
		self.handle_data()

	def handle_request_line(self):
		"""Called when the http request line and headers have been received"""
		# prepare attributes needed in parse_request()
		self.rfile.seek(0)
		requestline = self.rfile.readline()
		self.parse_request( requestline )

		# if browser indicates POST data follows, read it before generating the response
		bytesToRead = int(self.headers.getheader('content-length', '0'))
		if bytesToRead > 0:
			self.set_terminator(bytesToRead)
			self.rfile = cStringIO.StringIO()
			# control will be passed to a new found_terminator
			self.found_terminator = self.dispatch_handler
		
		else:
			# no content from brower - generate response now
			self.dispatch_handler()

	def dispatch_handler(self):
		mname = 'do_' + self.command
		if not hasattr(self, mname):
			self.send_error(501, "Unsupported method (%r)" % self.command)
			return
		getattr(self, mname)()

		if self.close_connection:
			"""Send data, then close"""
			self.log_message("close_connection set, closing connection")
			self.close_when_done()
		
		self.reset_terminator()

	def handle_error(self):
		traceback.print_exc(sys.stderr)
		self.close()

	def log_message(self, format, *args):
		sys.stdout.write("%s %s %s %s\n" %
						(self.id,self.log_date_time_string(), self.address_string(),						
						format%args))

class ToyHttpServer(asyncore.dispatcher):
	def __init__ (self, ip='', port=8081, handler=RequestHandler):
		self.handler = handler
		asyncore.dispatcher.__init__ (self)
		self.create_socket(socket.AF_INET, socket.SOCK_STREAM)

		self.set_reuse_addr()
		self.bind ((ip, port))
		self.listen (100)

		print "[httpd] ToyHTTPServer running on port %s" %port

	def handle_accept (self):
		try:
			pair = self.accept()
			if pair is not None:
				sock, addr = pair
				self.handler(sock,addr)
		except socket.error:
			self.log_info ('[https] warning: server accept() threw an exception', 'warning')
			return

if __name__=="__main__":
	# launch the server on the specified port
	s = ToyHttpServer(port=8081)	
#	try:
#		asyncore.loop(timeout=2)
#	except KeyboardInterrupt:
#		print "Crtl+C pressed. Shutting down."
	try:
		while True:
			asyncore.loop(timeout=2, count=10)
			print '[control] poll'
	except KeyboardInterrupt:
		print "Crtl+C pressed. Shutting down."

# def move():
#	 """ sample function to be called via a URL"""
#	 return 'hi'

# class CustomHandler(SimpleHTTPServer.SimpleHTTPRequestHandler):
#	 def do_GET(self):
#		 #Sample values in self for URL: http://localhost:8080/jsxmlrpc-0.3/
#		 #self.path  '/jsxmlrpc-0.3/'
#		 #self.raw_requestline   'GET /jsxmlrpc-0.3/ HTTP/1.1rn'
#		 #self.client_address	('127.0.0.1', 3727)
#		 if self.path=='/move':
#			 #This URL will trigger our sample function and send what it returns back to the browser
#			 self.send_response(200)
#			 self.send_header('Content-type','text/html')
#			 self.end_headers()
#			 self.push(move()) #call sample function here
#			 return
#		 else:
#			 #serve files, and directory listings by following self.path from
#			 #current working directory
#			 SimpleHTTPServer.SimpleHTTPRequestHandler.do_GET(self)
#httpd = SocketServer.ThreadingTCPServer(('localhost', PORT),CustomHandler)
#print "serving at port", PORT
#httpd.serve_forever()


