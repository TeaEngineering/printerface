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
pdfdir = dir + 'pdf/'
jobs = []
mailqueue = []

mainparser = DocParser()
formatter = DocFormatter(pdfdir)

with open(dir + 'bootstrap.html') as templ:
	bootstrapTemplate = templ.read().split('BOOTSTRAP', 1)

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
			proc = ['convert','-size 150x150','%s[0]' % f, '%s.png' % f]
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

class Bootstrap(object):
	def __init__(self,recent=False,printers=False,doc=False,settings=False):
		self.t = printers
	def __enter__(self):
		self.f = StringIO()
		self.f.write(bootstrapTemplate[0])
		return self.f

	def __exit__(self, type, value, tb):
		self.f.write(bootstrapTemplate[1])
		return False

def index(query_string=''):
	with Bootstrap() as f:
		f.write('''

      <div class="hero-unit" style="margin-top: 30px;">
        <h1>Printerface!</h1>
        <p>Printerface collects documents sent to the LPR print queue at 192.168.4.1 and stores them. Some documents are recognised and re-formatted to PDF files. 
        </p>
        <p><a href="#" class="btn btn-primary btn-large">Learn more &raquo;</a></p>
      </div>

      <div class="row">
        <div class="span4">
          <h2>Queue</h2>
          <p>Donec id elit non mi porta gravida at eget metus. Fusce dapibus, tellus ac cursus commodo, tortor mauris condimentum nibh, ut fermentum massa justo sit amet risus. Etiam porta sem malesuada magna mollis euismod. Donec sed odio dui. </p>
          <p><a class="btn" href="/recent">View details &raquo;</a></p>
        </div>
        <div class="span4">
          <h2>Document Type</h2>
          <p>Dnec id elit non mi porta gravida at eget metus. Fusce dapibus, tellus ac cursus commodo, tortor mauris condimentum nibh, ut fermentum massa justo sit amet risus. Etiam porta sem malesuada magna mollis euismod. Donec sed odio dui. </p>
          <p><a class="btn" href="/recent">View details &raquo;</a></p>
       </div>
        <div class="span4">
          <h2>Monthly</h2>
          <p>Donec sed odio dui. Cras justo odio, dapibus ac facilisis in, egestas eget quam. Vestibulum id ligula porta felis euismod semper. Fusce dapibus, tellus ac cursus commodo, tortor mauris condimentum nibh, ut fermentum massa justo sit amet risus.</p>
          <p><a class="btn" href="/recent">View details &raquo;</a></p>
        </div>
      </div>
      ''')
	return (f,'text/html')

def recent(query_string=''):
	with Bootstrap() as f:
		xstr = lambda s: s or ''
		f.write('<h3>Recent Jobs</h3>')
		f.write('<pre style="font-size:11px;line-height: 11px;">')
		f.write('Links         Time                templ     doctype    host       preview<br>')
		for j in jobs:
			h = xstr(j['control'].get('H'))
			if j['templ']:
				f.write('<a href="/plain?/%s.txt">Text</a> <a href="/doc?name=%s">Info</a> <a href="/pdf/%s.pdf">PDF</a> %19s %-9s %-10s %-10s %s <br>' %(
					j['name'], j['name'],j['name'],
					str(j['ts'])[0:19], \
				 xstr(j['templ']),j['doctype'],h,j['summary']))
			else:
				f.write('<a href="/plain/%s.txt">Text</a>          %19s %-9s %-10s %-10s %s <br>' %(j['name'], str(j['ts'])[0:19], \
				xstr(j['templ']),j['doctype'], h,j['summary']))
		f.write('</pre>')
	return (f,'text/html')

def printers(query_string=''):
	with Bootstrap() as f:
		xstr = lambda s: s or ''
		f.write('<h3>Printers</h3>')
		f.write('Links         Time                templ     doctype    host       preview<br>')		
	return (f,'text/html')

def document(query_string=dict()):
	with Bootstrap() as f:
		job = None
		print(query_string)
		for j in jobs: 
			job = j
			if j['name'] == query_string.get('name', [''])[0]: break
		
		f.write('<h3>Job Data</h3>')
		if not job:
			f.write('unknown job %s' % query_string)
			return (f,'text/html')
		colouring = job.get('colouring', [])
		f.write(' name: %s<br>' % job.get('name'))
		f.write(' type: %s<br>' % job.get('templ'))
		f.write(' data = ')
		f.write('<pre style="font-size:11px;line-height: 11px;">')
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

		f.write('<pre style="font-size:11px;line-height: 11px;">')
		chunks10 = 12
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
	for x in [jobdir, rawdir, plaindir, pdfdir]:
		try:
			os.makedirs(x)
		except:
			pass

	recover()

	s = LpdServer(saveJob, ip='', port=515)
	ToyHttpServer(port=8081, pathhandlers={'/recent': recent, '/index':index, '/doc':document, '/printers':printers}, webroot=dir)
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

