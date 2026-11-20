#!/usr/bin/env python3.11
"""Replay stored print jobs through the LPD server as a real RFC 1179 client would send them and check that
the payload and control file arrive unchanged.

    tools/replay_corpus.py CORPUS [--since job-YYYYMMDD]

CORPUS is laid out like ~/printerface (data/pickle/YYYYMM/job-*). Nothing is written to disk; the server
side is a recording callback rather than main.saveJob.
"""
import argparse
import asyncio
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lpdserver import LpdServer
from textutil import load_job_pickle

ap = argparse.ArgumentParser()
ap.add_argument('corpus')
ap.add_argument('--since', default='job-')
args = ap.parse_args()

received = []
loop = asyncio.new_event_loop()
threading.Thread(target=lambda: (asyncio.set_event_loop(loop), loop.run_forever()), daemon=True).start()
server = asyncio.run_coroutine_threadsafe(
	LpdServer(lambda queue, local, remote, control, data: received.append((queue, control, data)), ip='127.0.0.1', port=0).start(),
	loop).result(10)
port = server.port

import socket
def send(queue, control, data, eof_by_close=False):
	s = socket.create_connection(('127.0.0.1', port), timeout=10)
	def ack():
		assert s.recv(1) == b'\x00', 'no ack'
	try:
		s.sendall(b'\x02' + queue.encode('latin-1') + b'\n'); ack()
		c = control.encode('latin-1')
		s.sendall(b'\x02%d cfA001host\n' % len(c)); ack()
		s.sendall(c + b'\x00'); ack()
		if eof_by_close:
			# windows lpr declares a stupidly large size and signals the end of the file by closing the socket
			s.sendall(b'\x03%d dfA001host\n' % 0x7fffffff); ack()
			s.sendall(data)
			s.shutdown(socket.SHUT_WR)
			s.recv(1)
		else:
			s.sendall(b'\x03%d dfA001host\n' % len(data)); ack()
			s.sendall(data + b'\x00'); ack()
	finally:
		s.close()

root = os.path.join(args.corpus, 'data', 'pickle')
sent = bad = 0
nul_terminated = 0
sizes = 0
for yyyymm in sorted(os.listdir(root)):
	for name in sorted(os.listdir(os.path.join(root, yyyymm))):
		if not name.startswith('job-') or name < args.since:
			continue
		with open(os.path.join(root, yyyymm, name), 'rb') as f:
			j = load_job_pickle(f)
		# the stored payload still carries the protocol's trailing NUL, which the server adds back
		data = j['data']
		by_close = not data.endswith('\x00')
		if not by_close:
			nul_terminated += 1
			data = data[:-1]
		raw = data.encode('latin-1')
		control = ''.join('%s%s\n' % kv for kv in j['control'].items())
		before = len(received)
		send(j.get('queue', 'RAW'), control, raw, eof_by_close=by_close)
		for _ in range(500):
			if len(received) > before:
				break
			threading.Event().wait(0.01)
		sent += 1
		sizes += len(raw)
		if len(received) == before:
			bad += 1; print('NOT RECEIVED', name)
			continue
		queue, rcontrol, rdata = received[-1]
		if rdata != j['data'] or rcontrol != j['control'] or queue != j.get('queue', 'RAW'):
			bad += 1; print('MISMATCH', name, len(rdata), len(j['data']), rcontrol == j['control'])

print('replayed=%d (%.1f MiB): sized transfers=%d, eof-by-close transfers=%d, mismatches=%d' % (sent, sizes / 1048576.0, nul_terminated, sent - nul_terminated, bad))
sys.exit(1 if bad else 0)
