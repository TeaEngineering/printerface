
# Import smtplib for the actual sending function
import smtplib

# Import the email modules we'll need
from email.mime.text import MIMEText

import ConfigParser, os

config = ConfigParser.ConfigParser()
config.read(os.path.expanduser('~/printerface/email.cfg'))

class JobMailer(object):

	def sendJobEmail(self, s):

		q = s['data']
	
		# Create a text/plain message
		html = '<html><head></head><body><pre style="font-size:8px">%s</pre></body></html>' % q
	
		msg = MIMEText(html, 'html')

		mee = config.get('Email', 'from')
		you = config.get('Email', 'to')

		msg['Subject'] = 'Printerface: %s' % s['control']['U']
		msg['From'] = mee
		msg['To'] = you

		s = smtplib.SMTP('localhost')
		s.sendmail(mee, [you], msg.as_string())
		s.quit()

if __name__=="__main__":
	f = file("/root/printerface/jobs/job-20130323-181244%f",'rb')
	import pickle
	s = pickle.load(f)
	f.close()
	
	sendJobEmail(s)

