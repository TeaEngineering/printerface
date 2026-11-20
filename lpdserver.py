# Line Printer Daemon implementation (RFC 1179 receive side), using asyncio
# Chris Shucksmith 2013

import asyncio
import os
import sys
import traceback

# LPD is a byte protocol and print data is 8-bit. Decode everything as latin-1 so that one byte is
# always one character (columns in the fixed-width documents must not shift) and so it round-trips.
ENCODING = 'latin-1'

# a client that goes quiet in the middle of a job is dropped after this many seconds
IDLE_TIMEOUT = 120

ACK = b'\x00'


class LpdHandler(object):
	"""One connection. The conversation is: a receive-job command naming the queue, then a control file and a
	data file, each announced by a subcommand giving its size and acknowledged with a zero byte, and each
	followed by a zero byte of its own. Many senders close the connection after the data file."""

	def __init__(self, reader, writer, controller):
		self.reader = reader
		self.writer = writer
		self.controller = controller
		peer = writer.get_extra_info('peername') or ('?', 0)
		self.id = "[lpd-%d]" % peer[1]

	async def _read(self, coro):
		return await asyncio.wait_for(coro, IDLE_TIMEOUT)

	async def _line(self):
		"""The next command line without its newline, or None if the client has gone."""
		try:
			return (await self._read(self.reader.readuntil(b'\n')))[:-1]
		except asyncio.IncompleteReadError:
			return None

	async def _ack(self):
		self.writer.write(ACK)
		await self.writer.drain()

	async def run(self):
		print('%s installed LpdHandler' % self.id)
		try:
			await self._conversation()
		except (asyncio.TimeoutError, ConnectionError):
			print('%s connection lost' % self.id)
		except Exception:
			traceback.print_exc(file=sys.stdout)
		finally:
			print('%s handle_close' % self.id)
			try:
				self.writer.close()
				await self.writer.wait_closed()
			except Exception:
				pass

	async def _conversation(self):
		# main command verb: 02 <queue> LF
		while True:
			chunk = await self._line()
			if chunk is None:
				return
			if chunk[:1] == b'\x02':
				self.queue = chunk[1:].decode(ENCODING)
				print('%s Incoming job to queue \'%s\'' % (self.id, self.queue))
				await self._ack()
				break
			print('%s unknown message type %r' % (self.id, chunk[:1]))

		self.control = {}
		while True:
			chunk = await self._line()
			if chunk is None:
				print('%s unexpected close of stream' % self.id)
				return
			cmd = chunk[:1]
			if cmd == b'\x02':			# subcommand: control file, 02 <size> <name> LF
				size, name = chunk[1:].decode(ENCODING).split(' ', 1)
				length = int(size)
				print('%s Incoming header: control file sz %d filename %s' % (self.id, length, name))
				await self._ack()
				try:
					body = await self._read(self.reader.readexactly(length + 1))	# include the trailing null
				except asyncio.IncompleteReadError:
					print('%s unexpected close of stream' % self.id)
					return
				self.control = dict([(x[0], x[1:]) for x in body[:-1].decode(ENCODING).split('\n') if len(x) > 1])
				print('%s control file: %s' % (self.id, repr(self.control)))
				await self._ack()
			elif cmd == b'\x03':		# subcommand: data file, 03 <size> <name> LF
				size, name = chunk[1:].decode(ENCODING).split(' ', 1)
				length = int(size)
				print('%s incoming header: data file sz %d filename %s' % (self.id, length, name))
				await self._ack()
				# Windows sends a stupidly large size and closes the connection to mark the end of the data;
				# either way we dispatch what arrived. A well formed file keeps its trailing null, as it always has.
				data, complete = await self._data_file(length + 1)
				if complete:
					print('%s end of data file' % self.id)
					await self._ack()
					self.dispatch(data)
				else:
					# the sender has closed: the job must still be kept even if it can no longer hear the ack
					print('%s data file: %s' % (self.id, repr(data)[:100]))
					self.dispatch(data)
					try:
						await self._ack()
					except ConnectionError:
						pass
				return
			else:
				print('%s recieve job unknown subcommand: %r' % (self.id, cmd))

	async def _data_file(self, size):
		"""(bytes, complete): the data file, or what arrived of it before the sender closed or reset the connection."""
		chunks, got = [], 0
		while got < size:
			try:
				chunk = await self._read(self.reader.read(min(65536, size - got)))
			except ConnectionError:
				break
			if not chunk:
				break
			chunks.append(chunk)
			got += len(chunk)
		return b''.join(chunks), got >= size

	def dispatch(self, data):
		# log exceptions during dispatch so that we still get to close the connection
		try:
			print('%s dispatching' % self.id)
			self.controller(self.queue, self.writer.get_extra_info('peername'), self.writer.get_extra_info('sockname'),
				self.control, data.decode(ENCODING))
		except Exception as e:
			print('LPD dispatch of print job threw exception: %s' % sys.exc_info()[0])
			print(e)
			sys.stdout.flush()
		print('%s dispatch complete' % self.id)


class LpdServer(object):
	"""Listens for LPD connections and hands each received job to lpd_controller(queue, peer, local, control, data),
	called on the event loop, so it shares the loop's single thread with everything else. Use as
	`await server.start()`; `server.port` is the port actually bound (pass port=0 to be given one)."""

	def __init__(self, lpd_controller, ip='127.0.0.1', port=515):
		self.lpd_controller = lpd_controller
		self.ip = ip
		self.port = port
		self.server = None

	async def start(self):
		self.server = await asyncio.start_server(self._accept, self.ip or None, self.port, backlog=100)
		self.port = self.server.sockets[0].getsockname()[1]
		print('[lpd] listening on port %s' % self.port)
		return self

	async def _accept(self, reader, writer):
		print('[lpd] Incoming connection from %s' % repr(writer.get_extra_info('peername')))
		await LpdHandler(reader, writer, self.lpd_controller).run()

	async def close(self):
		if self.server:
			self.server.close()
			await self.server.wait_closed()


def jobPrinter(queue, local, remote, control, data):
	print('    %s' % queue)
	print('    %s' % repr(local))
	print('    %s' % repr(remote))
	print('    %s' % control)
	print('    %s' % repr(data))

def defaultPort():
	# on windows use 515. This is a restricted service port on linux so use 1515
	return 515 if os.name == 'nt' else 1515

if __name__=="__main__":
	# launch the server on the specified port
	# rather than run as root, use iptables nat to redirect to a common service port:
	# iptables -t nat -A PREROUTING -p tcp --dport 80 -j REDIRECT --to-port 8080
	# iptables -t nat -I OUTPUT -p tcp -d 127.0.0.1 --dport 80 -j REDIRECT --to-ports 8080
	async def main():
		await LpdServer(jobPrinter, ip='localhost', port=defaultPort()).start()
		await asyncio.Event().wait()
	try:
		asyncio.run(main())
	except KeyboardInterrupt:
		print('Crtl+C pressed. Shutting down.')
