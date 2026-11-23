# The derived cache on its own: when an entry is trusted, how the file is written, what the stamps follow.
import os
import pickle
import tempfile
import unittest

import derived
from derived import DerivedCache
from settings import config


def job(name, **kw):
	j = dict(name=name, stat=(10, 20), parsed={'ACC': [{'doc_num': '1'}]}, groupkey=('Group',), groupfiles={('ACC',): '2026/ACC/%s-ACC.pdf' % name}, render_stamp='r1')
	j.update(kw)
	return j


class TestDerivedCache(unittest.TestCase):
	def setUp(self):
		self.dir = tempfile.TemporaryDirectory()
		self.addCleanup(self.dir.cleanup)
		self.path = os.path.join(self.dir.name, 'derived.pickle')

	def written(self, jobs, **kw):
		c = DerivedCache(self.path)
		c.dirty = True
		self.assertTrue(c.flush(jobs, **kw))
		return DerivedCache(self.path)

	def test_round_trip_and_what_makes_an_entry_good(self):
		c = self.written([job('job-1')], force=True)
		e = c.lookup('job-1', (10, 20))
		self.assertEqual(({'ACC': [{'doc_num': '1'}]}, ('Group',), {('ACC',): '2026/ACC/job-1-ACC.pdf'}, 'r1'),
			(e['parsed'], e['groupkey'], e['groupfiles'], e['render_stamp']))
		self.assertIsNone(c.lookup('job-1', (11, 20)))             # the file changed size
		self.assertIsNone(c.lookup('job-1', (10, 21)))             # or was replaced
		self.assertIsNone(c.lookup('job-2', (10, 20)))             # never cached
		c.entries['job-1']['parse_stamp'] = 'older parser'
		self.assertIsNone(c.lookup('job-1', (10, 20)))

	def test_only_the_jobs_still_loaded_are_written(self):
		self.written([job('job-1'), job('job-2')], force=True)
		c = self.written([job('job-2'), job('job-3')], force=True)  # job-1 left the history, job-3 arrived
		self.assertEqual({'job-2', 'job-3'}, set(c.entries))
		c = self.written([job('job-9', stat=None)], force=True)     # a job with no file to vouch for it is not cached
		self.assertEqual(set(), set(c.entries))

	def test_flush_waits_unless_forced_and_only_when_dirty(self):
		c = DerivedCache(self.path)
		self.assertFalse(c.flush([job('a')]))                       # nothing changed
		c.dirty = True
		self.assertTrue(c.flush([job('a')]))                        # the first write is not delayed
		c.dirty = True
		self.assertFalse(c.flush([job('a'), job('b')]))             # too soon
		self.assertTrue(c.dirty)
		self.assertTrue(c.flush([job('a'), job('b')], force=True))
		self.assertFalse(c.dirty)
		self.assertFalse(os.path.exists(self.path + '.tmp'))

	def test_an_unreadable_or_foreign_file_means_a_cold_start(self):
		for content in (b'', b'not a pickle', pickle.dumps({'format': 99, 'entries': {'x': 1}}), pickle.dumps([1, 2])):
			with open(self.path, 'wb') as f:
				f.write(content)
			self.assertEqual({}, DerivedCache(self.path).entries)

	def test_a_failed_write_is_survived(self):
		c = DerivedCache(os.path.join(self.dir.name, 'missing-dir', 'derived.pickle'))
		c.dirty = True
		self.assertFalse(c.flush([job('a')], force=True))
		self.assertTrue(c.dirty)                                    # try again next time

	def test_stale_counts_jobs_drawn_under_other_stationery(self):
		c = DerivedCache(self.path)
		jobs = [job('a', render_stamp=c.render_stamp), job('b', render_stamp='old'), job('c', render_stamp=None)]
		self.assertEqual(['b', 'c'], [j['name'] for j in c.stale(jobs)])


class TestStamps(unittest.TestCase):
	def test_render_stamp_follows_the_company_details_and_logos(self):
		before = derived.render_stamp()
		self.assertEqual(before, derived.render_stamp())
		old = config.get('Printing', 'terms')
		config.set('Printing', 'terms', old + ' and more')
		self.addCleanup(config.set, 'Printing', 'terms', old)
		self.assertNotEqual(before, derived.render_stamp())
		config.set('Printing', 'terms', old)
		with tempfile.NamedTemporaryFile(suffix='.jpg') as logo:
			config.set('Printing', 'logo2', logo.name)
			self.addCleanup(config.set, 'Printing', 'logo2', '')
			with_logo = derived.render_stamp()
			self.assertNotEqual(before, with_logo)
			logo.write(b'changed')
			logo.flush()
			self.assertNotEqual(with_logo, derived.render_stamp())

	def test_parse_stamp_is_steady(self):
		self.assertEqual(derived.parse_stamp(), derived.parse_stamp())
		self.assertNotEqual(derived.parse_stamp(), derived.render_stamp())


if __name__ == '__main__':
	unittest.main()
