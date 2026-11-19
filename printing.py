#!/usr/bin/env python3
import datetime
import os
import pickle
import re
import subprocess
import traceback
import unittest
import unittest.mock as mock

import mailer
import printstatus
from settings import config, HOME
from textutil import PICKLE_PROTOCOL

PRINT_TIMEOUT = 30
pickle_file = os.path.join(HOME, 'printer.pickle')


class PrintError(Exception):
	pass


class PrintLog(object):
	"""What was sent to CUPS, newest first, one record per document: the job and key it came from, the printer, and
	the CUPS request id (the name lpstat knows the job by) or the error. Kept in a side pickle, like the sent
	emails, so the job pickles are never rewritten. The newest `limit` records are kept (the same setting as the
	email history) and the file is only written, by flush(), when something changed."""

	def __init__(self, path=None, limit=None):
		self.path = path
		self.limit = limit if limit is not None else config.getint('Gmail', 'result_count')
		self.records = []
		self.dirty = False
		if path:
			try:
				with open(path, 'rb') as f:
					self.records = pickle.load(f)
			except FileNotFoundError:
				pass
			except Exception:
				traceback.print_exc()
			del self.records[self.limit:]

	def add(self, record):
		self.records.insert(0, record)
		del self.records[self.limit:]
		self.dirty = True

	def for_job(self, job_name):
		"""The records made from this job, newest first."""
		return [r for r in self.records if r.get('job') == job_name]

	def flush(self):
		"""Write the history if it changed. Never raises: a full disk mustn't stop the server."""
		if not self.dirty or not self.path:
			return
		try:
			tmp = self.path + '.tmp'
			with open(tmp, 'wb') as f:
				pickle.dump(self.records, f, protocol=PICKLE_PROTOCOL)
			os.replace(tmp, self.path)
			self.dirty = False
		except Exception:
			traceback.print_exc()


printlog = PrintLog(pickle_file)


def getPrinters():
	"""Names of the CUPS queues, as the Printers page sees them (same lpstat call, so the two always agree).
	Empty if CUPS can't be asked, so the print menu is empty rather than offering a queue that doesn't exist."""
	try:
		return [p.name for p in printstatus.status().printers]
	except printstatus.LpstatError as e:
		print('[print] %s' % e)
		return []

def printFile(file, printer):
	"""Send a PDF to a CUPS queue with lp, record the outcome in printlog and return the record. lp reports the
	job's CUPS request id (KONICA_bizhub_192.168.12.10-12345), which is how the job shows up in lpstat.
	Raises PrintError, after recording it, if the job was not accepted."""
	cmd = ['lp', '-d', printer, file]
	ref = mailer.job_ref(file)
	record = {'job': ref[0] if ref else None, 'key': ref[1] if ref else None, 'file': file, 'printer': printer,
		'request_id': None, 'added': datetime.datetime.now(), 'error': None}
	try:
		p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=PRINT_TIMEOUT,
			env=dict(os.environ, LC_ALL='C', LANG='C'), universal_newlines=True)
		m = re.search(r'request id is (\S+)', p.stdout)
		record['request_id'] = m.group(1) if m else None
		if p.returncode != 0:
			record['error'] = (p.stderr or p.stdout).strip() or 'lp failed (exit %d)' % p.returncode
	except FileNotFoundError:
		record['error'] = 'lp is not installed on this machine'
	except subprocess.TimeoutExpired:
		record['error'] = 'lp did not finish within %d seconds' % PRINT_TIMEOUT
	except OSError as e:
		record['error'] = 'lp could not be run: %s' % e
	print("[print] printer=%s file=%s request=%s error=%s" % (printer, file, record['request_id'], record['error']))
	printlog.add(record)
	if record['error']:
		raise PrintError(record['error'])
	return record


class TestPrintFile(unittest.TestCase):
	PDF = '/p/2026/ACC001/job-20261119-101010-ACC001.pdf'

	def setUp(self):
		self.log = PrintLog(None, limit=3)
		patch = mock.patch.object(__import__(__name__), 'printlog', self.log)
		patch.start()
		self.addCleanup(patch.stop)

	def lp(self, stdout='', stderr='', code=0):
		return mock.patch('subprocess.run', return_value=subprocess.CompletedProcess([], code, stdout, stderr))

	def test_records_the_request_id_against_job_and_key(self):
		with self.lp('request id is KONICA_bizhub_192.168.12.10-12345 (1 file(s))\n') as run:
			rec = printFile(self.PDF, 'KONICA_bizhub_192.168.12.10')
		self.assertEqual(['lp', '-d', 'KONICA_bizhub_192.168.12.10', self.PDF], run.call_args[0][0])
		self.assertEqual('KONICA_bizhub_192.168.12.10-12345', rec['request_id'])
		self.assertEqual(('job-20261119-101010', 'ACC001', None), (rec['job'], rec['key'], rec['error']))
		self.assertEqual([rec], self.log.for_job('job-20261119-101010'))
		self.assertEqual([], self.log.for_job('job-20000101-000000'))
		self.assertTrue(self.log.dirty)

	def test_a_refused_job_is_recorded_and_raised(self):
		with self.lp(stderr='lp: The printer or class does not exist.\n', code=1):
			with self.assertRaisesRegex(PrintError, 'does not exist'):
				printFile(self.PDF, 'default')
		self.assertEqual('lp: The printer or class does not exist.', self.log.records[0]['error'])
		self.assertIsNone(self.log.records[0]['request_id'])

	def test_no_lp_and_timeouts(self):
		with mock.patch('subprocess.run', side_effect=FileNotFoundError()):
			with self.assertRaisesRegex(PrintError, 'not installed'):
				printFile(self.PDF, 'x')
		with mock.patch('subprocess.run', side_effect=subprocess.TimeoutExpired('lp', 30)):
			with self.assertRaisesRegex(PrintError, 'did not finish'):
				printFile(self.PDF, 'x')
		self.assertEqual(2, len(self.log.records))

	def test_a_file_that_is_not_ours_has_no_job(self):
		with self.lp('request id is Q-1 (1 file(s))'):
			rec = printFile('/tmp/report.pdf', 'Q')
		self.assertEqual((None, None), (rec['job'], rec['key']))

	def test_keeps_only_the_newest(self):
		with self.lp('request id is Q-1 (1 file(s))'):
			for _ in range(5):
				printFile(self.PDF, 'Q')
		self.assertEqual(3, len(self.log.records))


class TestPrintLog(unittest.TestCase):
	def test_flush_only_when_dirty_and_survives_a_restart(self):
		import tempfile
		with tempfile.TemporaryDirectory() as d:
			path = os.path.join(d, 'printer.pickle')
			log = PrintLog(path, limit=2)
			log.flush()
			self.assertFalse(os.path.exists(path))           # nothing to write yet
			for n in range(3):
				log.add({'job': 'job-1', 'n': n})
			self.assertTrue(log.dirty)
			log.flush()
			self.assertFalse(log.dirty)
			self.assertEqual([2, 1], [r['n'] for r in PrintLog(path, limit=2).records])
			self.assertEqual([2], [r['n'] for r in PrintLog(path, limit=1).records])     # a smaller limit trims on load
			os.remove(path)
			log.flush()
			self.assertFalse(os.path.exists(path))           # clean: not rewritten

	def test_a_corrupt_file_starts_empty(self):
		import tempfile
		with tempfile.TemporaryDirectory() as d:
			path = os.path.join(d, 'printer.pickle')
			open(path, 'wb').write(b'garbage')
			with mock.patch('traceback.print_exc'):
				self.assertEqual([], PrintLog(path, limit=2).records)


if __name__=="__main__":
	print ('Installed printers: %s' % repr(getPrinters()))
