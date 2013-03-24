#!/usr/bin/python

import asynchat, asyncore, socket, os
from datetime import datetime
from lpdserver import LpdServer
from httpserver import ToyHttpServer
from mailer import JobMailer

import pickle

jobdir = os.path.expanduser("~/printerface/jobs/")
jobs = []
mailqueue = []

def saveJob(queue, local, remote, control, data):
	ts = datetime.utcnow()
	d = {'queue':queue, 'from':repr(local), 'to':repr(remote), 'control':control, 'data':data, 'ts': ts}
	jobname = 'job-%s' % ts.strftime('%Y%m%d-%H%M%S%f')
	print "    %s" % repr(d)
	jobs.append(d)
	if len(jobs) > 100: jobs.pop(0)
	
	f = file(jobdir + jobname, "wb")
	pickle.dump(d, f)
	f.close()

	mailqueue.append(d)

def recover():
	xs = sorted(os.listdir(jobdir))
	if len(xs) > 100: xs = xs[-100:]

	print '[control] recovering from %s' % jobdir
	for x in xs:
		f = file(jobdir + x, "rb")
		jobs.append(pickle.load(f))
		f.close()

#	print repr(jobs)

def mailjob():
	pass

if __name__=="__main__":
	# launch the server on the specified port
	try:
		os.makedirs(jobdir)
	except:
		pass

	recover()

	s = LpdServer(saveJob, ip='', port=515)
	ToyHttpServer(port=8081)
	try:
		while True:
			asyncore.loop(timeout=2, count=1)
			print '[control] poll'
			if len(mailqueue) > 0:
				print '[control] sending email'
				s = mailqueue.pop()
				JobMailer().sendJobEmail(s)

	except KeyboardInterrupt:
		print "Crtl+C pressed. Shutting down."

