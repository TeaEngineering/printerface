#
# Mail sender to Gmail: a queue worked by the event loop, with the blocking smtplib calls in a worker thread.
# Keeps the last result_count results around if you want to check results

# Import smtplib for the actual sending function
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from settings import config, HOME
from textutil import load_user_pickles, PICKLE_PROTOCOL

# http://stackoverflow.com/questions/3362600/how-to-send-email-attachments-with-python
import datetime 
import asyncio
import os, re
import traceback
import pickle

pickle_file = os.path.join(HOME, 'mailer.pickle')

# An emailed PDF is stored as <pdfdir>/<year>/<account>/<job>-<key>.pdf (or <pdfdir>/raw/<yyyymm>/<job>-<key>.pdf), so
# the attachment path of a sent item says which job and which of its documents it came from. <key> is the name
# the job page knows the document by (an account, 'accounts', 'plain', ...) and <job> is job-YYYYMMDD-HHMMSS.
_job_ref = re.compile(r'(job-\d{8}-\d{6})-(.+)\.pdf$')

def job_ref(attachment):
	"""(job name, key) for the attachment path of a sent item, or None if it isn't one of ours."""
	m = _job_ref.search(attachment or '')
	return (m.group(1), m.group(2)) if m else None

def sent_from_job(results, job_name):
	"""The sent items made from this job, newest first, each with its job key. results is newest first."""
	prefix = job_name + '-'
	out = []
	for r in list(results):
		if prefix in (r.get('attachment') or ''):
			ref = job_ref(r['attachment'])
			if ref and ref[0] == job_name:
				out.append((r, ref[1]))
	return out

class JobMailer(object):
	"""Sends queued emails one at a time, in the order they were queued, and keeps the outcome of the last
	`result_count` of them (newest first) in mailer.pickle.

	The sending itself, smtplib, blocks, so it runs in a worker thread (asyncio.to_thread) while the event loop
	carries on serving; everything else, the queue and the results list, is only touched on the loop. `append`
	is called from page handlers and `start` / `close` from main.serve."""

	def __init__(self, queuesz=10):
		self.queue = asyncio.Queue(queuesz)
		self.results = []
		self.task = None
		self.resultLimit = config.getint('Gmail', 'result_count')

		try:
			with open(pickle_file, 'rb') as f:
				[self.results] = load_user_pickles(f)
		except FileNotFoundError:
			pass
		except:
			traceback.print_exc()

		while len(self.results) > self.resultLimit:
				self.results.pop()

	def start(self):
		"""Begin sending. Needs the running event loop."""
		self.task = asyncio.get_running_loop().create_task(self.run())

	async def close(self, timeout=30):
		"""Stop after sending what is already queued, for up to `timeout` seconds."""
		if self.task:
			try:
				await asyncio.wait_for(self.queue.join(), timeout)
			except asyncio.TimeoutError:
				print('mailq: %d emails still queued at shutdown' % self.queue.qsize())
			self.task.cancel()
			self.task = None

	def append(self, job):
		"""Queue an email. Raises asyncio.QueueFull if too many are waiting."""
		job['added'] = datetime.datetime.now()
		job['completed']=None
		job['status']=None
		self.queue.put_nowait( job )

	def send(self, work):
		"""Send one queued email (blocking: runs in a worker thread) and record the outcome on it."""
		try:
			filename = os.path.basename(work['attachment'])
			with open(os.path.expanduser(work['attachment']), 'rb') as fileobj:
				self.sendJobAttachment(work['body'], fileobj, filename, work['subject'], work['to'])
			work['completed'] = datetime.datetime.now()
			work['error'] = None
		except Exception as e:
			print('mailq: failed to send email: ' + repr(e))
			work['completed'] = datetime.datetime.now()
			work['error'] = repr(e)

	async def run(self):
		print("mailq: run is called")
		while True:
			work = await self.queue.get()
			try:
				print('mailq: Got work ' + repr(work))
				await asyncio.to_thread(self.send, work)
				print('mailq: finished ' + repr(work))
				self.results.insert(0, work)
				if len(self.results) > self.resultLimit:
					self.results.pop()
				self.pickleResults()
			except asyncio.CancelledError:
				raise
			except Exception:
				traceback.print_exc()
			finally:
				self.queue.task_done()

	def pickleResults(self):
		try:
			with open(pickle_file, 'wb') as f:
				p = pickle.Pickler(f, protocol=PICKLE_PROTOCOL)
				p.dump(self.results)			
		except Exception as e:
			traceback.print_exc()

	def sendJobAttachment(self, text, file, filename, subject="sending with gmail", email_to=[]):

		if len(email_to) == 0:
			raise Exception("No addresses in email_to")

		gmail_user = config.get('Gmail', 'login_user')
		gmail_pwd  = config.get('Gmail', 'login_password')
		
		msg = MIMEMultipart()
		msg['Subject'] = subject
		msg['From'] = config.get('Gmail', 'email_from')
		msg['To'] = ', '.join(email_to)

		msg.attach( MIMEText(text) )

		part = MIMEBase('application', "octet-stream")
		part.set_payload(file.read())
		encoders.encode_base64(part)

		part.add_header('Content-Disposition', 'attachment; filename="%s"' % filename)

		msg.attach(part)

		s = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30)
		s.ehlo()
		s.login(gmail_user, gmail_pwd)
		err_dict = s.sendmail( config.get('Gmail', 'email_from'), email_to , msg.as_string())
		s.set_debuglevel(2)
		s.close()
		
import unittest

class TestSentItemLinks(unittest.TestCase):
	def test_job_ref(self):
		self.assertEqual(('job-20261111-111416', 'HAR108'), job_ref('/home/printerface/printerface/data/pdf/2026/HAR108/job-20261111-111416-HAR108.pdf'))
		self.assertEqual(('job-20150715-101010', 'plain'), job_ref('/x/data/pdf/raw/201507/job-20150715-101010-plain.pdf'))
		self.assertEqual(('job-20261020-112058', 'AYU100-admin'), job_ref('/x/2026/AYU100/job-20261020-112058-AYU100-admin.pdf'))
		self.assertEqual(('job-20261020-112058', 'MULTI-21'), job_ref('/x/2026/MULTI-21/job-20261020-112058-MULTI-21.pdf'))
		self.assertEqual(('job-20261020-112058', 'accounts'), job_ref('C:\\\\x\\\\2026\\\\accounts\\\\job-20261020-112058-accounts.pdf'))
		for bad in ('', None, '/x/report.pdf', '/x/job-1-2-3.pdf', '/x/job-20261020-112058.pdf', '/x/job-20261020-112058-A.txt'):
			self.assertIsNone(job_ref(bad), bad)

	def test_sent_from_job(self):
		mk = lambda att, n: {'attachment': att, 'subject': n}
		results = [mk('/p/2026/B/job-20261111-111416-B.pdf', 'newest'), mk('/p/2026/A/job-20261111-111416-A.pdf', 'a'),
			mk('/p/2026/A/job-20261111-111417-A.pdf', 'other job'), mk('', 'no attachment'), {'subject': 'no key'}]
		found = sent_from_job(results, 'job-20261111-111416')
		self.assertEqual([('newest', 'B'), ('a', 'A')], [(r['subject'], key) for r, key in found])
		self.assertEqual([], sent_from_job(results, 'job-20000101-000000'))

class TestJobMailer(unittest.TestCase):
	def setUp(self):
		import tempfile
		global pickle_file
		self.dir = tempfile.TemporaryDirectory()
		self.addCleanup(self.dir.cleanup)
		old, pickle_file = pickle_file, os.path.join(self.dir.name, 'mailer.pickle')
		self.addCleanup(lambda: globals().update(pickle_file=old))

	def mailer(self, size=10, limit=3, sender=None):
		m = JobMailer(size)
		m.resultLimit = limit
		self.sent = []
		def fake(text, fileobj, filename, subject, email_to):
			if sender:
				sender(subject)
			self.sent.append((subject, filename, fileobj.read(), list(email_to)))
		m.sendJobAttachment = fake
		return m

	def attachment(self, name='a.pdf', data=b'%PDF'):
		path = os.path.join(self.dir.name, name)
		with open(path, 'wb') as f:
			f.write(data)
		return path

	def job(self, subject, **kw):
		return dict(to=['x@example.com'], body='b', subject=subject, attachment=kw.get('attachment') or self.attachment())

	def test_sends_in_order_records_newest_first_and_persists(self):
		async def go():
			m = self.mailer()
			m.start()
			for n in 'abc':
				m.append(self.job(n))
			await m.close()
			return m
		m = asyncio.run(go())
		self.assertEqual(['a', 'b', 'c'], [x[0] for x in self.sent])
		self.assertEqual(('a.pdf', b'%PDF', ['x@example.com']), self.sent[0][1:])
		self.assertEqual(['c', 'b', 'a'], [r['subject'] for r in m.results])
		self.assertTrue(all(r['error'] is None and r['completed'] for r in m.results))
		with open(pickle_file, 'rb') as f:
			self.assertEqual(['c', 'b', 'a'], [r['subject'] for r in pickle.load(f)])

	def test_a_failure_is_recorded_and_the_next_still_goes(self):
		def sender(subject):
			if subject == 'bad':
				raise RuntimeError('smtp down')
		async def go():
			m = self.mailer(sender=sender)
			m.start()
			m.append(self.job('bad'))
			m.append(self.job('good'))
			m.append(dict(self.job('gone'), attachment=os.path.join(self.dir.name, 'missing.pdf')))
			await m.close()
			return m
		m = asyncio.run(go())
		by = {r['subject']: r['error'] for r in m.results}
		self.assertIn('smtp down', by['bad'])
		self.assertIsNone(by['good'])
		self.assertIn('FileNotFoundError', by['gone'])

	def test_keeps_only_the_newest_results(self):
		async def go():
			m = self.mailer(limit=2)
			m.start()
			for n in '1234':
				m.append(self.job(n))
			await m.close()
			return m
		self.assertEqual(['4', '3'], [r['subject'] for r in asyncio.run(go()).results])

	def test_sending_does_not_block_the_event_loop(self):
		import threading
		gate = threading.Event()
		async def go():
			m = self.mailer(sender=lambda subject: gate.wait(5))
			m.start()
			m.append(self.job('slow'))
			await asyncio.sleep(0.1)           # the worker thread is now stuck inside "smtplib"
			ticks = 0
			for _ in range(5):
				await asyncio.sleep(0.01)
				ticks += 1
			gate.set()
			await m.close()
			return ticks, m
		ticks, m = asyncio.run(go())
		self.assertEqual(5, ticks)
		self.assertEqual(['slow'], [r['subject'] for r in m.results])

	def test_too_many_queued_is_an_error_not_a_stall(self):
		async def go():
			m = self.mailer(size=2)
			m.append(self.job('1'))
			m.append(self.job('2'))
			with self.assertRaises(asyncio.QueueFull):
				m.append(self.job('3'))
		asyncio.run(go())

	def test_results_survive_a_restart_and_a_smaller_limit_trims(self):
		async def go():
			m = self.mailer(limit=5)
			m.start()
			for n in '123':
				m.append(self.job(n))
			await m.close()
		asyncio.run(go())
		async def again():
			return JobMailer(10)
		m = asyncio.run(again())
		self.assertEqual(['3', '2', '1'], [r['subject'] for r in m.results])


if __name__=="__main__":

	async def demo():
		mailq = JobMailer(100)
		mailq.start()
		mailq.append(dict(
			to=['chris@shucksmith.co.uk'], body='body text here', subject='Statement for XX',
			attachment="~/repos/printerface/web/pdf/job-20130404-145700%f-accounts.pdf"))
		await mailq.close()
		print(mailq.results)

	asyncio.run(demo())
