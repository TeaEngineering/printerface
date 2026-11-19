#
# Asynchronous mail sender to Gmail, using a seperate thread.
# Keeps the last 10 results around if you want to check results

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
import os, re, threading
import queue
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

	def __init__(self, queuesz=10):
		self.queue = queue.Queue(queuesz)
		self.results = []
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

		self.thread = threading.Thread(target=self.run)
		self.thread.daemon = True
		self.thread.start()

	def append(self, job):
		job['added'] = datetime.datetime.now()
		job['completed']=None
		job['status']=None
		self.queue.put( job )

	def run(self):
		print("mailq: run is called")
		while True:
			try:
				work = self.queue.get(block=True, timeout=60)
				print('mailq: Got work ' + repr(work))

				try:
					filename = os.path.basename(work['attachment'])
					with open(os.path.expanduser(work['attachment']), 'rb') as fileobj:

						x = self.sendJobAttachment(work['body'], fileobj, filename, work['subject'], work['to'])

					work['completed'] = datetime.datetime.now()
					work['error'] = None

				except Exception as e:
					print('mailq: failed to send email: ' + repr(e))
					
					work['completed'] = datetime.datetime.now()
					work['error'] = repr(e)

				print('mailq: finished ' + repr(work))
				self.results.insert(0, work)
				if len(self.results) > self.resultLimit:
					self.results.pop()

				self.pickleResults()

			except queue.Empty:
				print('mailq: idling for jobs')

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

if __name__=="__main__":
	
	import time
	mailq = JobMailer(100)

	for i in range(60):
		time.sleep(1)

		if i == 5:
			mailq.append(dict(
				to=['chris@shucksmith.co.uk'], body='body text here', subject='Statement for XX',
				attachment="~/repos/printerface/web/pdf/job-20130404-145700%f-accounts.pdf"))

		print(mailq.results)

	print('done')


