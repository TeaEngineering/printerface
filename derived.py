"""
A cache of what is slow to work out from a stored job: the parsed pages, and the names of the PDFs made from them.
Reading the job pickles is quick (0.1 s for a thousand); parsing them and drawing the PDFs is what makes a start
slow, so the next start can take those from here.

The cache is only ever an optimisation. The job pickles stay the record, and anything wrong with an entry (a
different job file, newer parser code, a missing PDF) means that job is worked out again. One file, written
atomically; one entry per job file name, so it follows the history: a job that leaves the loaded history is
dropped from the file the next time it is written.

An entry is only trusted if
  * the job file is the one it was made from (size and modification time),
  * it was parsed by the same parser (`parse_stamp`: docparser.py and textutil.py),
and the PDFs it names are still on disk. How the PDFs were drawn (`render_stamp`: stationary.py, the [Printing]
company details and the logos) is recorded with it, but a change does not redraw them by itself: the Stationery
settings page counts the jobs drawn under older stationery and has the button that redraws them.
"""

import hashlib
import os
import pickle
import time
import traceback

from settings import BASE_DIR, HOME, config

PATH = os.path.join(HOME, 'derived.pickle')

# bumped if the layout of an entry changes
FORMAT = 1

# the file is rewritten at most this often (seconds) while something is changing
FLUSH_EVERY = 180


def _digest(parts):
	h = hashlib.sha256()
	for p in parts:
		h.update(p if isinstance(p, bytes) else repr(p).encode('utf-8'))
		h.update(b'\0')
	return h.hexdigest()[:16]


def _source(name):
	with open(os.path.join(BASE_DIR, name), 'rb') as f:
		return f.read()


def parse_stamp():
	return _digest([FORMAT, _source('docparser.py'), _source('textutil.py')])


def render_stamp():
	parts = [FORMAT, _source('stationary.py'), sorted(config.items('Printing'))]
	for key in ('logo', 'logo2'):
		path = os.path.expanduser(config.get('Printing', key, fallback=''))
		try:
			st = os.stat(path) if path else None
		except OSError:
			st = None
		parts.append((path, st and (st.st_size, st.st_mtime_ns)))
	return _digest(parts)


class DerivedCache(object):
	def __init__(self, path=PATH):
		self.path = path
		self.entries = {}
		self.dirty = False
		self.last_flush = 0
		self.parse_stamp = parse_stamp()
		self.render_stamp = render_stamp()
		try:
			with open(path, 'rb') as f:
				data = pickle.load(f)
			if data.get('format') == FORMAT:
				self.entries = data['entries']
		except FileNotFoundError:
			pass
		except Exception:
			print('[derived] ignoring an unreadable cache %s' % path)
			traceback.print_exc()

	def lookup(self, name, stat):
		"""The entry for this job file if it is still good, else None."""
		e = self.entries.get(name)
		if e and e['stat'] == stat and e['parse_stamp'] == self.parse_stamp:
			return e
		return None

	def snapshot(self, jobs):
		"""The entries for the jobs as they are now: what a flush writes."""
		out = {}
		for j in jobs:
			if j.get('stat') and 'groupfiles' in j:
				out[j['name']] = dict(stat=j['stat'], parse_stamp=self.parse_stamp, render_stamp=j.get('render_stamp'),
					parsed=j['parsed'], groupkey=j['groupkey'], groupfiles=j['groupfiles'])
		return out

	def flush(self, jobs, force=False):
		"""Write the cache if it changed, and not more than every FLUSH_EVERY seconds unless forced. Never raises: a
		full disk mustn't stop the server."""
		if not self.dirty or (not force and time.time() - self.last_flush < FLUSH_EVERY):
			return False
		try:
			entries = self.snapshot(jobs)
			tmp = self.path + '.tmp'
			with open(tmp, 'wb') as f:
				pickle.dump(dict(format=FORMAT, entries=entries), f, protocol=pickle.HIGHEST_PROTOCOL)
			os.replace(tmp, self.path)
			self.entries = entries
			self.dirty = False
			self.last_flush = time.time()
			return True
		except Exception:
			traceback.print_exc()
			return False

	def stale(self, jobs):
		"""The jobs whose PDFs were drawn under different stationery from today's."""
		return [j for j in jobs if j.get('render_stamp') != self.render_stamp]
