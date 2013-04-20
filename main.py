#!/usr/bin/python

import asynchat, asyncore, socket, os, re
from datetime import datetime
from lpdserver import LpdServer
from httpserver import ToyHttpServer
from mailer import JobMailer
from docparser import DocParser
from stationary import DocFormatter

import sys
import pickle
from StringIO import StringIO

dir = os.path.expanduser("~/repos/printerface/web/")
jobdir = dir + 'pickle/'
rawdir = dir + 'raw/'
plaindir = dir + 'plain/'
jobs = []
mailqueue = []

mainparser = DocParser()
formatter = DocFormatter()

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
	print(' recovering %s' % j['name'])
	fn = rawdir + j['name'] + '.txt'
	control_char_re = re.compile('[^\w\s%s_\'=/]' % re.escape('.*+()-\\;:,#?%$^&!<>|`"'))
	raw = j['data']
	plain = control_char_re.sub(' ', j['data'])
	j['plain'] = plain
	summary = re.compile('[^\w\s]').sub('', j['data'])
	summary = re.compile('\s+').sub(' ', summary)
	summary = summary.strip()[0:70]

	writeFile(rawdir + j['name'] + '.txt', raw)
	writeFile(plaindir + j['name'] + '.txt', plain)

	j['summary'] = summary
	j['doctype'] = j.get('control', {}).get('J').strip()
	j['templ'] = identify(j)

	(j['colouring'],j['parsed']) = mainparser.parse(j)
	if not j['colouring']: del j['colouring']

	# if colouring succeded, might be able to generate docs
	if j.get('colouring'):
		(j['files']) = formatter.format(j)

		for f in [j['files']]:
			from subprocess import call
			proc = ['convert','-size','150x150','%s[0]' % f, '%s.png' % f]
			print(proc)
			call(proc)
	
	# all done

def identify(j):
	types = {'Sttments': 'statement', 'Delvnote':'delnote', 'Cr-note':'crednote', 'Invoice':'invoice', 'P order':'purchase'}
	return types.get(j['doctype'])

def recentjob(query_string=''):
	f = StringIO()
	f.write("hi %s\n" % query_string)
	for j in jobs:
                f.write("      %10s    %10s \n" %(j['name'], j['ts']))
	return (f,'text/plain')

def index(query_string=''):
	xstr = lambda s: s or ''
	f = StringIO()
	f.write('<h3>Recent Jobs</h3>R: raw, T: plain text, B: boxes, J:json, P:pdf <pre>')
	f.write('Links     Time                templ     doctype    host       preview<br>')
	for j in jobs:
		h = xstr(j['control'].get('H'))
		if j['templ']:
			f.write('R <a href="/plain/%s.txt">T</a>   <a href="/data?name=%s">J</a> <a href="/pdf/%s.pdf">P</a> %19s %-9s %-10s %-10s %s <br>' %(
				j['name'], j['name'],j['name'],
				str(j['ts'])[0:19], \
			 xstr(j['templ']),j['doctype'],h,j['summary']))
		else:
			f.write('R <a href="/plain/%s.txt">T</a>       %19s %-9s %-10s %-10s %s <br>' %(j['name'], str(j['ts'])[0:19], \
			xstr(j['templ']),j['doctype'], h,j['summary']))
	f.write('</pre>')
	return (f,'text/html')

def data(query_string=''):
	job = None
	for j in jobs: 
		if j['name'] == query_string['name'][0]: job = j
	f = StringIO()
        f.write('<html><head></head><body>')

	f.write('<h3>Job Data</h3>')
	if not job:
		f.write('unknown job %s' % query_string)
		return (f,'text/html')
	colouring = job.get('colouring', [])
	f.write(' name: %s<br>' % job.get('name'))
	f.write(' type: %s<br>' % job.get('templ'))
	f.write(' data = <pre style="font-size:11px">')
	import pprint
	pp = pprint.PrettyPrinter(indent=4, stream=f)
	pp.pprint(job.get('parsed'))
	f.write('</pre>')

	f.write('<h3>Annotated Document</h3>')
	lines = job['plain'].splitlines()
	(rows, cols) = (len(lines), max([len(line) for line in lines]))
	f.write('plain text dimensions: lines %d, width %d<br>' % (rows, cols))
	cols = max([cols] + [c['c']+c['w'] for c in colouring])
	rows = max([rows] + [c['r']+c['h'] for c in colouring])

	high = [[None for col in range(cols)] for row in range(rows)]

	for c in colouring:
		for row in range(c['r'], c['r']+c['h']):
			for col in range(c['c'], c['c']+c['w']):
				high[row][col] = c

	f.write('<pre style="font-size:10px">')
	chunks10 = 16 
	f.write('     ' +  ''.join(["%-10d" % (d*10) for d in range(chunks10)]))
	f.write('\n     ' + ('0123456789' * chunks10))

	def htmlcol(rgb):
		return ''.join([('%02x' % int(c*256)) for c in rgb])
	for (row,line) in enumerate(lines):
		f.write('\n%-4d ' % row)
		pad = ' '*(max(0,len(high[row])-len(line)))
		for col,char in enumerate(line + pad):
			if high[row][col]:
				f.write('<span title="%s" style="background-color: #%s">' % (high[row][col]['t'],htmlcol(high[row][col]['rgb'])))
				f.write(char)
				f.write('</span>')
			else: f.write(char)
	f.write('</pre>')
	f.write('<h3>PDF Output</h3>')
	
	if job.get('files'):
	# for pdffile in job.get('files', []):
	#	f.write(pdffile)

		f.write('<a href="/pdf/%s.pdf"> <img src="/pdf/%s.pdf.png" width="400px"><br> PDF File</a>' % (job['name'], job['name']))

	if query_string.get('raw'): f.write(job)
	f.write('</pre></body></html>')
	return (f,'text/html')

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
	ToyHttpServer(port=8081, pathhandlers={'/json/recent': recentjob, '/index':index, '/data':data}, webroot=dir)
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

