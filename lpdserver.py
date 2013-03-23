

import asynchat, asyncore, socket, exceptions

(AwaitingCommand, NewJob, NewJobControl, NewJobData, EndOfFile ) = range(0,5)

class LpdHandler(asynchat.async_chat):

	def __init__(self, sock, addr, controller):
		try:
			asynchat.async_chat.__init__(self, sock=sock)
		except exceptions.TypeError:
			# compat python 2.5.2  bugfix for http://bugs.python.org/issue1519
			asynchat.async_chat.__init__(self, conn=sock)
		self.ibuffer = []
		self.sm = AwaitingCommand
		self.set_terminator("\n")
		self.sock = sock
		self.controller = controller
		self.id = "[lpd-%d]" % addr[1]
		print '%s installed LpdHandler' % self.id
				
	def collect_incoming_data(self, data):
		self.ibuffer.append(data)

	def found_terminator(self):
		chunk = self.ibuffer.pop(0)
		if self.sm == AwaitingCommand: # Main command verb
			if chunk[0] == '\x02':
				self.queue = chunk[1:]
				print '%s Incoming job to queue \'%s\'' % (self.id, self.queue)
				self.push('\x00')
				self.sm = NewJob
			else:
				print '%s unknown message type %d' + (self.id, self.ibuffer[0])
		elif self.sm == NewJob: # Recieve Job
			if chunk[0] == '\x02':	# Subcommand - Control filename
				sz,name = chunk[1:].split(' ', 1)
				rdlength = int(sz)
				print '%s Incoming header: control file sz %d filename %s' % (self.id, rdlength,name)
				self.sm = NewJobControl
				self.set_terminator(rdlength+1) # include the trailing null
				self.push('\x00')				
			if chunk[0] == '\x03': # Subcommand - Data filename
				sz,name = chunk[1:].split(' ', 1)
				rdlength = int(sz)
				print '%s incoming header: data file sz %d filename %s' % (self.id, rdlength,name)
				self.sm = NewJobData
				# windows seems to set a stupidly large length here and kill the socket to 
				# indicate eof. Handle either
				self.set_terminator(rdlength+1) # include the trailing null
				# self.set_terminator(None) # terminated by close of socket
				self.push('\x00')
		elif self.sm == NewJobControl: # Recieve - Job Control file (null terminated)
			self.controldata = dict([ (x[0], x[1:]) for x in chunk[:-1].split('\n') if len(x) > 1])
			print '%s control file: %s' % (self.id, repr(self.controldata))
			self.push('\x00')
			self.sm = NewJob
			self.set_terminator("\n")
		elif self.sm == NewJobData: # Recieve - Job Data file (terminated by close)
			# Windows NT4 lpr sends a well formed size, hits this code
			print '%s end of data file' % self.id 
			# put the chunk back on the ibuffer for dispatch()
			self.ibuffer.insert(0, chunk)
			self.sm = EndOfFile
			self.push('\x00')
			self.close_when_done()
			self.dispatch()
		else:
			print '%s Unknown state, woken up by terminator, buffer was: %s' % (self.id, repr(self.ibuffer))
			self.close_when_done()
	def handle_close(self):
		
		if self.sm == NewJobData:
			print '%s data file: %s' % (self.id, repr(self.ibuffer))
			# calling push() after the client has closed the socket will re-invoke handle_close, so 
			# switch to terminal state to avoid inf recursion
			self.sm = EndOfFile
			self.dispatch()
			self.push('\x00')
			self.close_when_done()
		elif self.sm == EndOfFile:
			self.close()
		else:
			print '%s unexpected close of stream, sm=%d' % (self.id, self.sm)
			self.close()

	def dispatch(self):
		data = ''.join(self.ibuffer)
		self.controller(self.queue, self.sock.getpeername(), self.sock.getsockname(), self.controldata, data)
		print '%s dispatched' % (self.id)

class LpdServer(asyncore.dispatcher):
	def __init__ (self, lpd_controller, ip='127.0.0.1', port=515):
		asyncore.dispatcher.__init__ (self)
		self.create_socket (socket.AF_INET, socket.SOCK_STREAM)
		self.set_reuse_addr()
		self.bind ((ip, port))
		self.listen (100)
		self.lpd_controller = lpd_controller
		print "[lpd] listening on port %s" % port

	def handle_accept(self):
		try:
			pair = self.accept()
			if pair is not None:
				sock, addr = pair
				print '[lpd] Incoming connection from %s' % repr(addr)
				LpdHandler(sock, addr, self.lpd_controller)
		except socket.error:
			print '[lpd] warning: server accept() threw an exception'

def jobPrinter(queue, local, remote, control, data):
	print "    %s" % queue
	print "    %s" % repr(local)
	print "    %s" % repr(remote)
	print "    %s" % control
	print "    %s" % repr(data)

if __name__=="__main__":
	# launch the server on the specified port
	s = LpdServer(jobPrinter, ip='192.168.1.75', port=515)
	try:
		asyncore.loop(timeout=2)
	except KeyboardInterrupt:
		print "Crtl+C pressed. Shutting down."
