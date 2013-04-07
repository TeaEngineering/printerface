#!/usr/bin/python

import asynchat, asyncore, socket, os, re
from datetime import datetime
from lpdserver import LpdServer
from httpserver import ToyHttpServer
from mailer import JobMailer
import sys
import pickle
from StringIO import StringIO

dir = os.path.expanduser("~/printerface/")
jobdir = dir + 'pickle/'
rawdir = dir + 'raw/'
plaindir = dir + 'plain/'
jobs = []
mailqueue = []

def saveJob(queue, local, remote, control, data):
	ts = datetime.utcnow()
	jobname = 'job-%s' % ts.strftime('%Y%m%d-%H%M%S')
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

def writeFile(fn, string):
	f = file(fn, "wb")
	f.write(string)
	f.close()

def cleanJob(j):
	fn = rawdir + j['name'] + '.txt'
	control_char_re = re.compile('[^\w\s%s_\'=/]' % re.escape('.*+()-\\;:,#?%$^&!<>|`"'))
	raw = j['data']
	plain = control_char_re.sub(' ', j['data'])

	writeFile(rawdir + j['name'] + '.txt', raw)
	writeFile(plaindir + j['name'] + '.txt', plain)

def recentjob(query_string=''):
	f = StringIO()
	f.write("hi %s\n" % query_string)
	for j in jobs:
                f.write("      %10s    %10s \n" %(j['name'], j['ts']))
	return (f,'text/plain')

if __name__=="__main__":
	# launch the server on the specified port
	try:
		os.makedirs(jobdir)
		os.makedirs(rawdir)
		os.makedirs(plaindir)
	except:
		pass

	try:
		os.makedirs(plaindir)
	except:
		pass

	recover()

	s = LpdServer(saveJob, ip='', port=515)
	ToyHttpServer(port=8081, pathhandlers={'/json/recent': recentjob})
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

