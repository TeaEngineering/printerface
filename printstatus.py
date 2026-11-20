#!/usr/bin/env python3
# Read-only view of CUPS for the Printers page: one `lpstat -t` call, parsed, plus a plain-English verdict on
# whether automatic printing can be expected to work.
#
# lpstat only produces text meant for people, and in the locale of the server, so we ask for the C locale
# ("Wed Sep  9 15:02:14 2026", no timezone). It says nothing about whether a job came out of the printer:
# a job leaves the queue when CUPS has handed it to the device, and a queue stuck "Connecting to printer..."
# is the only sign of trouble. So this page can show a stuck queue, but never prove a page was printed.
import os
import re
import subprocess
import time
from collections import namedtuple
from datetime import datetime, timedelta

LPSTAT_TIMEOUT = 5
CACHE_SECONDS = 10
STALE_AFTER = timedelta(hours=1)  # a job waiting longer than this on a working printer is not "about to print"

Printer = namedtuple('Printer', 'name device state job since accepting accepting_since message reason reject_reason')
Job = namedtuple('Job', 'id printer user size submitted')
Status = namedtuple('Status', 'scheduler default printers jobs fetched')


class LpstatError(Exception):
	pass


def run_lpstat():
	"""Text of `lpstat -t` in the C locale, or LpstatError if it can't be had."""
	env = dict(os.environ, LC_ALL='C', LANG='C')
	try:
		p = subprocess.run(['lpstat', '-t'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
			timeout=LPSTAT_TIMEOUT, universal_newlines=True)
	except FileNotFoundError:
		raise LpstatError('lpstat is not installed on this machine')
	except subprocess.TimeoutExpired:
		raise LpstatError('lpstat did not answer within %d seconds' % LPSTAT_TIMEOUT)
	except OSError as e:
		raise LpstatError('lpstat could not be run: %s' % e)
	if p.returncode != 0:
		# cupsd stopped: "lpstat: Bad file descriptor" / "Unable to connect to server"
		raise LpstatError((p.stderr or p.stdout).strip() or 'lpstat failed (exit %d)' % p.returncode)
	return p.stdout


def mask_uri(uri):
	"""A device URI can carry a password (ipp://user:secret@host/...): never show that part."""
	return re.sub(r'^([a-z][a-z0-9+.-]*://)[^/@]*@', r'\1', uri.strip(), flags=re.I)


def parse_date(text):
	"""'Wed Sep  9 15:02:14 2026' (C locale) as a naive local datetime, else None."""
	text = ' '.join(text.split())
	# a trailing zone name ("BST") is dropped: strptime's %Z only knows UTC, GMT and the local zone's names, so
	# it would parse on one machine and not another
	text = re.sub(r' [A-Z]{2,5}$', '', text)
	for fmt in ('%a %b %d %H:%M:%S %Y', '%a %d %b %Y %I:%M:%S %p', '%a %d %b %Y %H:%M:%S'):
		try:
			return datetime.strptime(text, fmt)
		except ValueError:
			continue
	return None


_SINCE = r'(?P<since>.*?)(?:\s+-)?'
_ACCEPTING = re.compile(r'^(?P<name>\S+) (?P<ok>accepting|not accepting) requests since ' + _SINCE + r'$')
_DEVICE = re.compile(r'^device for (?P<name>[^:]+): (?P<uri>.*)$')
_PRINTER = re.compile(r'^printer (?P<name>\S+) (?:(?P<idle>is idle)|now printing (?P<job>\S+?)|(?P<disabled>disabled))\.?\s+'
	r'(?:enabled )?since ' + _SINCE + r'$')
_JOB = re.compile(r'^(?P<printer>\S+)-(?P<id>\d+)\s+(?P<user>\S+)\s+(?P<size>\d+)\s+(?P<date>\S.*)$')


def parse(text, fetched=None):
	"""Parse `lpstat -t` output. Lines we don't recognise are ignored rather than fatal."""
	scheduler = None
	default = None
	devices = {}
	accepting = {}
	states = {}
	order = []
	jobs = []
	last = None  # the printer record that following tab-indented lines belong to
	for line in text.splitlines():
		if not line.strip():
			continue
		if line[0] in ' \t':
			if last is not None and last in states:
				states[last]['text'] = line.strip()
			continue
		last = None
		if line.startswith('scheduler is '):
			scheduler = line[len('scheduler is '):].strip().rstrip('.')
		elif line.startswith('system default destination: '):
			default = line.split(': ', 1)[1].strip()
		elif line.startswith('no system default destination'):
			default = None
		elif _DEVICE.match(line):
			m = _DEVICE.match(line)
			devices[m.group('name')] = mask_uri(m.group('uri'))
		elif _ACCEPTING.match(line):
			m = _ACCEPTING.match(line)
			accepting[m.group('name')] = (m.group('ok') == 'accepting', parse_date(m.group('since')))
			if m.group('name') not in order:
				order.append(m.group('name'))
			last = ('acc', m.group('name'))
			states[last] = {}
		elif _PRINTER.match(line):
			m = _PRINTER.match(line)
			state = 'disabled' if m.group('disabled') else 'idle' if m.group('idle') else 'printing'
			states[m.group('name')] = {'state': state, 'job': m.group('job'), 'since': parse_date(m.group('since'))}
			if m.group('name') not in order:
				order.append(m.group('name'))
			last = m.group('name')
		elif _JOB.match(line):
			m = _JOB.match(line)
			jobs.append(Job(m.group('printer') + '-' + m.group('id'), m.group('printer'), m.group('user'),
				int(m.group('size')), parse_date(m.group('date'))))
	printers = []
	for name in order:
		st = states.get(name, {})
		acc = accepting.get(name, (None, None))
		# the indented line after "not accepting" is why; after "disabled" it is why; otherwise it is a status message
		why = states.get(('acc', name), {}).get('text') if acc[0] is False else None
		text_ = st.get('text')
		state = st.get('state', 'unknown')
		printers.append(Printer(name, devices.get(name), state, st.get('job'), st.get('since'), acc[0], acc[1],
			text_ if state != 'disabled' else None, text_ if state == 'disabled' else None, why))
	return Status(scheduler, default, printers, jobs, fetched or datetime.now())


_cache = {'when': 0, 'value': None}


def reset_cache():
	_cache['when'] = 0
	_cache['value'] = None


def status():
	"""The current Status (cached a few seconds so a refreshing page can't hammer cupsd), or LpstatError."""
	now = time.time()
	if _cache['value'] is None or now - _cache['when'] > CACHE_SECONDS:
		_cache['value'] = parse(run_lpstat())
		_cache['when'] = now
	return _cache['value']


def humanise(delta):
	secs = int(delta.total_seconds())
	if secs < 0:
		return 'in the future'
	if secs < 90:
		return 'just now' if secs < 10 else '%d seconds' % secs
	for unit, size in (('year', 365 * 86400), ('month', 30 * 86400), ('day', 86400), ('hour', 3600), ('minute', 60)):
		if secs >= size * (1.5 if unit in ('hour', 'minute') else 1):
			n = secs // size
			return '%d %s%s' % (n, unit, '' if n == 1 else 's')
	return '%d minutes' % (secs // 60)


Verdict = namedtuple('Verdict', 'level problems')  # level: ok | warning | error


def assess(st, printer_name, now=None):
	"""Can automatic printing to `printer_name` be expected to work? Plain-English problems, worst first."""
	now = now or st.fetched
	errors, warnings = [], []
	if st.scheduler != 'running':
		errors.append('The CUPS scheduler is not running, so nothing can print.')
	p = next((x for x in st.printers if x.name == printer_name), None)
	if p is None:
		errors.append('CUPS has no printer called %s, so automatic printing fails.' % printer_name)
	else:
		if p.state == 'disabled':
			errors.append('%s is disabled%s.' % (p.name, ': ' + p.reason if p.reason else ''))
		if p.accepting is False:
			errors.append('%s is not accepting jobs%s.' % (p.name, ': ' + p.reject_reason if p.reject_reason else ''))
		waiting = [j for j in st.jobs if j.printer == p.name]
		old = [j for j in waiting if j.submitted and now - j.submitted > STALE_AFTER]
		if old:
			oldest = min(j.submitted for j in old)
			warnings.append('%d job%s for %s %s been waiting for %s or more, so this printer may be stuck.' % (
				len(old), '' if len(old) == 1 else 's', p.name, 'has' if len(old) == 1 else 'have', humanise(now - oldest)))
	if errors:
		return Verdict('error', errors + warnings)
	if warnings:
		return Verdict('warning', warnings)
	return Verdict('ok', [])


import unittest

SAMPLE = """scheduler is running
no system default destination
device for OFFICE_MFP: lpd://192.0.2.100/MF8200C
device for DESK_LASER: socket://192.0.2.212
device for HALL_COPIER_192.0.2.10: socket://192.0.2.10
OFFICE_MFP accepting requests since Wed Sep  9 15:02:14 2026
DESK_LASER accepting requests since Wed Oct 25 12:01:17 2023
HALL_COPIER_192.0.2.10 accepting requests since Thu Nov 19 16:33:41 2026
printer OFFICE_MFP now printing OFFICE_MFP-41070.  enabled since Wed Sep  9 15:02:14 2026
\tConnecting to printer...
printer DESK_LASER is idle.  enabled since Wed Oct 25 12:01:17 2023
printer HALL_COPIER_192.0.2.10 is idle.  enabled since Thu Nov 19 16:33:41 2026
\tReady to print.
OFFICE_MFP-41070    printerface      91136   Wed Jun 29 13:27:57 2016
OFFICE_MFP-41071    printerface       5120   Wed Jun 29 13:28:27 2016
DESK_LASER-56672    printerface      64512   Tue May 30 09:14:10 2017
"""

# The two failure shapes below were written from CUPS 1.4's lpstat.c, not captured: no queue on our server has been
# disabled or stopped from accepting jobs.
BROKEN = """scheduler is running
system default destination: DESK_LASER
device for DESK_LASER: ipp://admin:s3cret@192.0.2.212/ipp/print
DESK_LASER not accepting requests since Thu Nov 19 10:00:00 2026 -
\tRejecting Jobs
printer DESK_LASER disabled since Thu Nov 19 10:00:00 2026 -
\tPaused
"""

NOW = datetime(2026, 11, 19, 17, 0, 0)


class TestParse(unittest.TestCase):
	def setUp(self):
		self.st = parse(SAMPLE, NOW)

	def test_scheduler_and_default(self):
		self.assertEqual(self.st.scheduler, 'running')
		self.assertIsNone(self.st.default)
		self.assertEqual(parse(BROKEN, NOW).default, 'DESK_LASER')

	def test_printers_in_order(self):
		self.assertEqual([p.name for p in self.st.printers], ['OFFICE_MFP', 'DESK_LASER', 'HALL_COPIER_192.0.2.10'])
		hall = self.st.printers[2]
		self.assertEqual((hall.state, hall.accepting, hall.message, hall.device), ('idle', True, 'Ready to print.', 'socket://192.0.2.10'))
		self.assertEqual(hall.since, datetime(2026, 11, 19, 16, 33, 41))

	def test_busy_printer_has_its_job_and_message(self):
		p = self.st.printers[0]
		self.assertEqual((p.state, p.job, p.message), ('printing', 'OFFICE_MFP-41070', 'Connecting to printer...'))

	def test_jobs(self):
		self.assertEqual([j.id for j in self.st.jobs], ['OFFICE_MFP-41070', 'OFFICE_MFP-41071', 'DESK_LASER-56672'])
		self.assertEqual(self.st.jobs[0].size, 91136)
		self.assertEqual(self.st.jobs[2].submitted, datetime(2017, 5, 30, 9, 14, 10))

	def test_stopped_printer_gives_reasons(self):
		p = parse(BROKEN, NOW).printers[0]
		self.assertEqual((p.state, p.accepting, p.reason), ('disabled', False, 'Paused'))

	def test_not_accepting_reason(self):
		text = BROKEN.replace('printer DESK_LASER disabled since Thu Nov 19 10:00:00 2026 -\n\tPaused\n',
			'printer DESK_LASER is idle.  enabled since Thu Nov 19 10:00:00 2026\n')
		p = parse(text, NOW).printers[0]
		self.assertEqual((p.state, p.accepting, p.reject_reason), ('idle', False, 'Rejecting Jobs'))

	def test_credentials_never_shown(self):
		p = parse(BROKEN, NOW).printers[0]
		self.assertEqual(p.device, 'ipp://192.0.2.212/ipp/print')
		self.assertNotIn('s3cret', repr(p))

	def test_junk_is_ignored(self):
		st = parse('\nwhat is this\n' + SAMPLE, NOW)
		self.assertEqual(len(st.printers), 3)

	def test_dates(self):
		self.assertEqual(parse_date('Wed Sep  9 15:02:14 2026'), datetime(2026, 9, 9, 15, 2, 14))
		self.assertEqual(parse_date('Wed 09 Sep 2026 03:02:14 PM BST'), datetime(2026, 9, 9, 15, 2, 14))
		self.assertIsNone(parse_date('yesterday'))


class TestAssess(unittest.TestCase):
	def test_stuck_queue_is_a_warning_for_that_printer_only(self):
		st = parse(SAMPLE, NOW)
		self.assertEqual(assess(st, 'HALL_COPIER_192.0.2.10').level, 'ok')
		v = assess(st, 'OFFICE_MFP')
		self.assertEqual(v.level, 'warning')
		self.assertIn('2 jobs', v.problems[0])

	def test_missing_printer(self):
		v = assess(parse(SAMPLE, NOW), 'NOPE')
		self.assertEqual(v.level, 'error')
		self.assertIn('no printer called NOPE', v.problems[0])

	def test_disabled_and_not_accepting(self):
		v = assess(parse(BROKEN, NOW), 'DESK_LASER')
		self.assertEqual(v.level, 'error')
		self.assertEqual(len(v.problems), 2)
		self.assertTrue(any('Paused' in x for x in v.problems) and any('Rejecting Jobs' in x for x in v.problems))

	def test_scheduler_down(self):
		self.assertEqual(assess(parse(SAMPLE.replace('is running', 'is not running'), NOW), 'DESK_LASER').level, 'error')

	def test_recent_jobs_are_fine(self):
		st = parse(SAMPLE.replace('Wed Jun 29 13:27:57 2016', 'Thu Nov 19 16:50:00 2026')
			.replace('Wed Jun 29 13:28:27 2016', 'Thu Nov 19 16:51:00 2026'), NOW)
		self.assertEqual(assess(st, 'OFFICE_MFP').level, 'ok')

	def test_humanise(self):
		self.assertEqual(humanise(timedelta(seconds=3)), 'just now')
		self.assertEqual(humanise(timedelta(minutes=5)), '5 minutes')
		self.assertEqual(humanise(timedelta(hours=3)), '3 hours')
		self.assertEqual(humanise(timedelta(days=1)), '1 day')
		self.assertEqual(humanise(timedelta(days=800)), '2 years')


class TestRun(unittest.TestCase):
	def tearDown(self):
		reset_cache()

	def test_missing_lpstat_is_an_error_not_a_crash(self):
		import unittest.mock as mock
		with mock.patch('subprocess.run', side_effect=FileNotFoundError()):
			with self.assertRaises(LpstatError):
				run_lpstat()

	def test_cupsd_down(self):
		import unittest.mock as mock
		r = subprocess.CompletedProcess([], 1, '', 'lpstat: Bad file descriptor\n')
		with mock.patch('subprocess.run', return_value=r):
			with self.assertRaisesRegex(LpstatError, 'Bad file descriptor'):
				run_lpstat()

	def test_cached_between_calls(self):
		import unittest.mock as mock
		with mock.patch(__name__ + '.run_lpstat', return_value=SAMPLE) as run:
			status()
			status()
			self.assertEqual(run.call_count, 1)
			reset_cache()
			status()
			self.assertEqual(run.call_count, 2)


if __name__ == '__main__':
	unittest.main()
