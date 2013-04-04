#!/usr/bin/python

import asynchat, asyncore, socket, os
from datetime import datetime
from lpdserver import LpdServer
from httpserver import ToyHttpServer
from mailer import JobMailer
import sys
import pickle

dir = os.path.expanduser("~/printerface/")
jobdir = dir + 'pickle/'
rawdir = dir + 'raw/'
jobs = []
mailqueue = []

def saveJob(queue, local, remote, control, data):
	ts = datetime.utcnow()
	jobname = 'job-%s' % ts.strftime('%Y%m%d-%H%M%S%f')
	d = {'queue':queue, 'from':repr(local), 'to':repr(remote), 'control':control, 'data':data, 'ts': ts, 'name':jobname}
	# print "    %s" % repr(d)
	jobs.append(d)
	if len(jobs) > 100: jobs.pop(0)
	
	f = file(jobdir + jobname, "wb")
	pickle.dump(d, f)
	f.close()

	mailqueue.append(d)

	cleanJob(d)

def recover():
	xs = sorted([ x for x in os.listdir(jobdir) if x != 'raw'])
	if len(xs) > 100: xs = xs[-100:]

	print '[control] recovering from %s' % jobdir
	for x in xs:		
		f = file(jobdir + x, "rb")
		s = pickle.load(f)
		s['name'] = x;
		jobs.append(s)
		f.close()
	for j in jobs:
		cleanJob(j)

def cleanJob(j):
	fn = rawdir + j['name'] + '.txt'
	if not os.path.exists( fn ):
		f = file(fn, "wb")
		f.write(j['data'])
		f.close()

if __name__=="__main__":
	# launch the server on the specified port
	try:
		os.makedirs(jobdir)
		os.makedirs(rawdir)
	except:
		pass

	recover()

	s = LpdServer(saveJob, ip='', port=515)
	ToyHttpServer(port=8081)
	try:
		while True:
			asyncore.loop(timeout=1, count=10)
			print '[control] poll %s' % str(datetime.now())
			sys.stdout.flush()
			if len(mailqueue) > 0:
				print '[control] sending email'
				s = mailqueue.pop()
				JobMailer().sendJobEmail(s)

	except KeyboardInterrupt:
		print "Crtl+C pressed. Shutting down."

