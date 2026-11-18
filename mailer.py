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
import os, threading
import queue
import traceback
import pickle

pickle_file = os.path.join(HOME, 'mailer.pickle')

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


