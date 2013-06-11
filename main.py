#!/usr/bin/python

from __future__ import with_statement

import asynchat, asyncore, socket, os, re
from datetime import datetime
from lpdserver import LpdServer
from httpserver import ToyHttpServer
from mailer import JobMailer
from docparser import DocParser
from stationary import DocFormatter
from printing import getPrinters, printFile

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
recentQty = 300

with open(dir + 'bootstrap.html') as templ:
	bootstrapTemplate = templ.read().split('BOOTSTRAP', 1)

def saveJob(queue, local, remote, control, data):
	ts = datetime.utcnow()
	jobname = 'job-%s' % ts.strftime('%Y%m%d-%H%M%S')
	d = {'queue':queue, 'from':repr(local), 'to':repr(remote), 'control':control, 'data':data, 'ts': ts, 'name':jobname}
	# print "    %s" % repr(d)
	jobs.append(d)
	if len(jobs) > recentQty: jobs.pop(0)
	
	f = file(jobdir + jobname, "wb")
	pickle.dump(d, f)
	f.close()

	mailqueue.append(d)

	cleanJob(d)

def recover():
	xs = sorted([ x for x in os.listdir(jobdir) if x != 'raw'])
	if len(xs) > recentQty: xs = xs[-recentQty:]

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
	types = {'Sttments': 'statement', 'Delvnote':'delnote', 'Cr-note':'crednote', 'Invoice':'invoice', 'P order':'purchase', 'Rem Advs':'remittance'}
	return types.get(j['doctype'])

class Bootstrap(object):
	def __init__(self,recent=False,printers=False,document=False,settings=False):
		self.kwtoggle = dict(recent=recent, printers=printers, document=document, settings=settings)
	def __enter__(self):
		self.f = StringIO()
		bt = bootstrapTemplate[0]
		for k,v in self.kwtoggle.items():
			bt = bt.replace('%%%s%%' % k.upper(), 'class="active"' if v else '' )
			#'class="active"'bt = bt.replace('%PRINTERS%', 'class="active"')
			#bt = bt.replace('%DOCUMENT%', 'class="active"')
		self.f.write(bt)
		return self.f

	def __exit__(self, type, value, tb):
		self.f.write(bootstrapTemplate[1])
		return False

def index(query_string=''):
	with Bootstrap() as f:
		f.write('''

      <div class="hero-unit" style="margin-top: 30px;">
        <h1>Printerface</h1>
        <p>Printerface collects documents sent to the LPR print queue at 192.168.4.1 and stores them. Some documents are recognised and re-formatted to PDF files. 
        </p>
        <p><a href="/recent" class="btn btn-primary btn-large">Recent Documents &raquo;</a></p>
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
	with Bootstrap(recent=True) as f:
		xstr = lambda s: s or ''
		f.write('<h3>Recent Jobs</h3>')
		f.write('<pre style="font-size:11px;line-height: 11px;">')
		f.write('Links         Time                templ      doctype    host       preview<br>')
		for j in reversed(jobs):
			h = xstr(j['control'].get('H'))
			if j['templ']:
				f.write('<a href="/plaintext?name=%s">Text</a> <a href="/doc?name=%s">Info</a> <a href="/pdf?name=%s">PDF</a> %19s %-10s %-10s %-10s %s\n' %(
					j['name'], j['name'],j['name'],
					str(j['ts'])[0:19], \
				 xstr(j['templ']),j['doctype'],h,j['summary']))
			else:
				f.write('<a href="/plaintext?name=%s">Text</a>          %19s %-10s %-10s %-10s %s\n' %(j['name'], str(j['ts'])[0:19], \
				xstr(j['templ']),j['doctype'], h,j['summary']))
		f.write('</pre>')

		f.write('<ul class="pager"><li class="previous"> <a href="#">&larr; Older</a> </li> <li class="next"> <a href="#">Newer &rarr;</a> </li> </ul>')
	return (f,'text/html')

def printers(query_string=''):
	with Bootstrap(printers=True) as f:
		f.write('<h3>Printers</h3>')
		f.write('<ul>')
		for p in getPrinters():
			f.write('<li>%s</li>' % (p))
		f.write('</ul>')
		f.write('<p>To add or change printers use <a href="https://192.168.12.4:631/">CUPS Administration</a>') 
	return (f,'text/html')

def printfn(query_string=''):
	job = getJob(query_string)
	for f in [job['files']]:
		printFile(f, ''.join(query_string['printer']) )
	with Bootstrap(printers=True) as f:
		f.write('<h3>Printing...</h3>')
		f.write('Document %s sent to printer %s<br>' % (query_string['name'], query_string['printer']) )
	return (f,'text/html')

def pdf(query_string=dict()):
	job = getJob(query_string)
	with Bootstrap(document=True) as f:
		# style="width: 100%; height: 300px;"
		f.write('<p><div class="row" style="position: absolute; top: 35px; bottom: 5px; left: 65px; right:65px;"> ')
		# f.write('<p>')
		f.write('<div class="btn-group">\n')
		f.write('  <a class="btn dropdown-toggle" data-toggle="dropdown" href="#">Print <span class="caret"></span></a> <ul class="dropdown-menu"> ')
		for p in getPrinters():
			f.write('<li><a tabindex="-1" href="/print?name=%s&printer=%s">%s</a></li>' % (job['name'],p,p))
		f.write('</ul>\n')	
		f.write('</div> ')
		f.write(' <div class="btn-group">\n')
		f.write('  <a class="btn dropdown-toggle" data-toggle="dropdown" href="#">Email <span class="caret"></span></a> <ul class="dropdown-menu"> ')
		for p in getPrinters():
			f.write('<li><a tabindex="-1" href="/email?name=%s&printer=%s">%s</a></li>' % (job['name'],p,p))
		f.write('</ul>\n')

		f.write('</div>')
		f.write('<object	data="/pdf/%s.pdf#toolbar=1&amp;navpanes=0&amp;scrollbar=1&amp;page=0&amp;zoom=30" ' % job['name'])
		f.write(' type="application/pdf" width="100%" height="95%">')
		f.write(' <p>It appears you don\'t have a PDF plugin for this browser. No biggie... you can <a href="/pdf/sample.pdf">click here to download the PDF file.</a></p>')
		f.write('\n</object>\n</div>')
		f.write('<p>&nbsp;<p>&nbsp;<p>&nbsp;<p>&nbsp;')
	return (f, 'text/html')

def plain(query_string=dict()):
	job = getJob(query_string)
	with Bootstrap(document=True) as f:
		# style="width: 100%; height: 300px;"
		f.write('<p><div class="row" style="position: absolute; top: 35px; bottom: 5px; left: 65px; right:65px;"> ')
		f.write('<p>')
		f.write('<div class="btn-group hidden-print">\n')
		f.write('  <a class="btn dropdown-toggle" data-toggle="dropdown" href="#">Print <span class="caret"></span></a> <ul class="dropdown-menu"> ')
		for p in getPrinters():
			f.write(' <li><a tabindex="-1" href="/print?name=%s&printer=%s">%s</a></li>' % (job['name'],p,p))
		f.write(' </ul>\n')	
		f.write('</div> ')
		f.write('<div class="btn-group hidden-print">\n')
		f.write('  <a class="btn dropdown-toggle" data-toggle="dropdown" href="#">Email <span class="caret"></span></a> <ul class="dropdown-menu"> ')
		for p in getPrinters():
			f.write(' <li><a tabindex="-1" href="/print?name=%s&printer=%s">%s</a></li>' % (job['name'],p,p))
		f.write(' </ul>\n')	
		f.write('</div>')

		f.write('<pre style="font-size:10px;line-height: 10px;">')
		for l in job['plain']:
			f.write(l)
		f.write('</pre>')
		f.write('<p>&nbsp;')
	return (f, 'text/html')

def getJob(query_string, returnLast=False):
	for j in jobs: 
		job = j
		if j['name'] == query_string.get('name', [''])[0]: return j
	if returnLast: return job

def document(query_string=dict()):
	with Bootstrap(document=True) as f:
		job = getJob(query_string, returnLast=True)
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

			f.write('<a href="/pdf?name=%s"> <img src="/pdf/%s.pdf.png" width="400px"><br> PDF File</a>' % (job['name'], job['name']))

		if query_string.get('raw'): f.write(job)
		f.write('</body></html>')
	return (f,'text/html')

# def printFile(file, printer):

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

