#!/usr/bin/python

from __future__ import with_statement

from mako.template import Template
from mako.lookup import TemplateLookup
from mako import exceptions

import asynchat, asyncore, socket, os, re
from datetime import datetime
from lpdserver import LpdServer
from httpserver import ToyHttpServer
from mailer import JobMailer
from docparser import DocParser
from stationary import DocFormatter
from printing import getPrinters, printFile

import sys, pickle, ConfigParser
from StringIO import StringIO

config = ConfigParser.ConfigParser()
config.read('defaults.cfg')
config.read(os.path.expanduser('~/printerface/email.cfg'))


dir = os.path.expanduser("~/repos/printerface/web/")
jobdir = dir + 'pickle/'
rawdir = dir + 'raw/'
plaindir = dir + 'plain/'
pdfdir = dir + 'pdf/'
jobs = []
mailqueue = []

mainparser = DocParser()
formatter = DocFormatter(pdfdir)
template_lookup = TemplateLookup(directories=[dir],  output_encoding='utf-8', encoding_errors='replace', format_exceptions=True)

summary_regexps = [ re.compile(x) for x in config.get('Main', 'summary_trim').strip().split(',') ]
	
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
	for r in summary_regexps:
		summary = r.sub(' ', summary)
	summary = re.compile('\s+').sub(' ', summary)
	summary = summary.strip()[0:120]

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
	types = {'Sttments': 'statement', 'Delvnote':'delnote', 'Cr-note':'crednote', 'Invoice':'invoice', 'P order':'purchase', 'Rem Advs':'remittance'}
	return types.get(j['doctype'])

def index(query_string=''):
	return ( template_lookup.get_template("/index-templ.html").render() ,'text/html')

def recent(query_string=''):
	return ( template_lookup.get_template("/recent-templ.html").render(jobs=reversed(jobs)), 'text/html')
	
def printers(query_string=''):
	return ( template_lookup.get_template("/printers.html").render(printers=getPrinters()), 'text/html')

def printfn(query_string=''):
	job = getJob(query_string)
	for f in [job['files']]:
		printFile(f, ''.join(query_string['printer']) )

	return doMessage(title='Printing', message='Document %s sent to printer %s<br>' % (query_string['name'], query_string['printer']))

def pdf(query_string=dict()):
	job = getJob(query_string)
	return ( template_lookup.get_template("/pdf.html").render(printers=getPrinters(), job=job), 'text/html')

def plain(query_string=dict()):
	job = getJob(query_string)

	return ( template_lookup.get_template("/plain.html").render(printers=getPrinters(), job=job), 'text/html')

def getJob(query_string, returnLast=False):
	for j in jobs: 
		job = j
		if j['name'] == query_string.get('name', [''])[0]: return j
	if returnLast: return job

def doMessage(message='?', title='Printerface'):
	return ( template_lookup.get_template("/message.html").render(title=title, message=message), 'text/html')

def document(query_string=dict()):
	job = getJob(query_string, returnLast=True)

	if not job:
		return doMessage(message=('Unknown job %s' % query_string) )

	import pprint
	pformatted = pprint.pformat(job.get('parsed'), indent=4)

	colouring = job.get('colouring', [])

	lines = job['plain'].splitlines()
	(rows, cols) = (len(lines), max([len(line) for line in lines]))

	cols = max([cols] + [c['c']+c['w'] for c in colouring])
	rows = max([rows] + [c['r']+c['h'] for c in colouring])

	high = [[None for col in range(cols)] for row in range(rows)]

	for c in colouring:
		for row in range(c['r'], c['r']+c['h']):
			for col in range(c['c'], c['c']+c['w']):
				high[row][col] = c

	chunks10 = 12
	f = StringIO()
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
	
	return ( template_lookup.get_template("/detail.html").render( job=job,
			rows=rows, cols=cols, coloured_plaintext=f.getvalue(), pformatted=pformatted), 'text/html')

if __name__=="__main__":
	# launch the server on the specified port
	for x in [jobdir, rawdir, plaindir, pdfdir]:
		try:
			os.makedirs(x)
		except:
			pass

	recover()

	s = LpdServer(saveJob, ip='', port=515)
	ToyHttpServer(port=8081, pathhandlers={
		'/recent': recent, '/index':index, '/doc':document, '/printers':printers, '/pdf':pdf,
		'/print' : printfn, '/plaintext':plain
		}, webroot=dir)
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

