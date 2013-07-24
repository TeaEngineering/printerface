#!/usr/bin/env python

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
import collections
import traceback

config = ConfigParser.ConfigParser()
config.read('defaults.cfg')
config.read(os.path.expanduser('~/printerface/email.cfg'))


dir = os.path.expanduser("~/repos/printerface/web/")
jobdir = dir + 'pickle/'
rawdir = dir + 'raw/'
plaindir = dir + 'plain/'
pdfdir = dir + 'pdf/'
jobs = []
mailqueue = JobMailer(100)

email_accounts = { }
email_addresses = collections.defaultdict(dict)
email_template = ''

mainparser = DocParser()
formatter = DocFormatter(pdfdir)
template_lookup = TemplateLookup(directories=[dir], output_encoding='utf-8', encoding_errors='replace', format_exceptions=True)
recentQty = 300

summary_regexps = [ re.compile(x) for x in config.get('Main', 'summary_trim').strip().split(',') ]
	
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

	cleanJob(d)

def saveEmails():
	with open(os.path.expanduser('~/printerface/email.pickle'), 'wb') as f:
		p = pickle.Pickler(f)
		p.dump(email_addresses)
		p.dump(email_accounts)
		p.dump(email_template)
		print('[control] Wrote email pickles')

def recover():
	global email_template
	try:
		with open(os.path.expanduser('~/printerface/email.pickle'), 'rb') as f:
			p = pickle.Unpickler(f)
			for (k,v) in p.load().iteritems():
				email_addresses[k].update(v)
			email_accounts.update(p.load())
			email_template = p.load()

		print('recovered emails: %s' % email_addresses)
		print('recovered accounts: %s' % email_accounts)
	except IOError:
		print('[control] email pickle load failed')

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

	if j['parsed']:
		for y in j['parsed'].itervalues():
			for x in y:
				acc = None
				addr = None
				try:
					acc = x['accno']				
				except:
					try:
						acc = x['doc_num']
					except:
						pass
				try:	
					addr = x['addr_invoice'].split('\n')[0]
				except:
					pass
				print("got email %s -> %s" % (acc, addr))
				if acc and addr:
					email_accounts[acc] = (addr),

	# if colouring succeded, might be able to generate docs
	if j.get('colouring'):
		# protocol: PDF file names are dict values. keys are document
		# groups {('all'): p}, ('all')
		(j['groupfiles'], j['groupkey']) = formatter.format(j)



		for f in j['groupfiles'].itervalues():
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

def sent(query_string=''):
	return ( template_lookup.get_template("/sent.html").render(mailqueue=mailqueue), 'text/html')

def settings_email(query_string='', postreq=None):
	warning=None
	print('query_string=%s' % query_string)
	try:
		acc = query_string['account'][0]
		email = query_string['email'][0]
		contact = query_string['contact'][0]
		try:
			email_accounts[acc]
			if not email.strip() in email_addresses[acc]:
				email_addresses[acc][email.strip()] = contact
				saveEmails()
		except KeyError:			
			warning='Unknown account %s' % acc
	except KeyError:
		pass

	try:
		acc = query_string['account'][0]
		delete_email = query_string['delete'][0]
		if email_addresses[acc].pop(delete_email, None):
			saveEmails()
	except KeyError:
		pass

	email_list = []
	for key in sorted(email_accounts.iterkeys()):
		email_list.append( (key, email_accounts[key], email_addresses[key].iteritems()) )
	
	return ( template_lookup.get_template("/settings_email.html").render(emails=email_list, warning=warning), 'text/html')

def settings_template(query_string='', postreq=None):
	global email_template

	print('query_string=%s' % query_string)
	message = None
	try:
		template = query_string.get('template', None)
		if template:
			email_template = template[0]
			saveEmails()
			message = '<strong>Thanks!</strong> Template updated'
	except:
		message = '<strong>Ohno!</strong> Template failed'
	return ( template_lookup.get_template("/settings_template.html").render(template=email_template, message=message), 'text/html')

def printfn(query_string=''):
	job = getJob(query_string)
	default_key = job['groupfiles'].iterkeys().next()[0]
	key = query_string.get('key', [default_key])[0]
	docf = getJobFile( job, key)

	if docf:
		try:		
			printFile(pdfdir + docf, ''.join(query_string['printer']) )
			return doMessage(title='Printing', message='Document %s sent to printer %s<br>' % (docf, query_string['printer']))
		except:
			traceback.print_exc(file=sys.stdout)
	return doMessage(title='Printing', message='Could not find document, problem printing! Source: %s sent to printer %s<br>' % (docf, query_string['printer']))

def pdf(query_string=dict()):
	job = getJob(query_string)
	default_key = job['groupfiles'].iterkeys().next()[0]
	key = query_string.get('key', [default_key])[0]
	email_dest = email_addresses.get(key, {})
	email_outcome, email_error = None, None
	
	# test if callback from email form
	try:
		addresses = query_string.get('em', [])
		email_body = ''.join(query_string.get('emailbody', ['']))
		email_subject = ''.join(query_string.get('subject', ['no subject']))
		action = query_string.get('action', None)
		
		docf = getJobFile( job, key)
		
		if len(addresses) > 0 and docf and len(email_subject) > 1:
			email_outcome = "Queueing email to " + ','.join(addresses) + ' - check the result later!';
			print(email_outcome)
			try:
				mailqueue.append(dict(
					to=addresses, body=email_body, subject=email_subject,
					attachment="~/repos/printerface/web/pdf/" + docf))
			except:
				traceback.print_exc(file=sys.stdout)
				email_error = "<strong>Problem!</strong> unable to queue email!"
		elif action:
			email_error = "<strong>Oh snap!</strong> Some fields missing or incomplete!"
	except:
		raise

	return ( template_lookup.get_template("/pdf.html").render(printers=getPrinters(), job=job, key=key, email_templ=email_template, email_dest=email_dest, email_outcome=email_outcome, email_error=email_error), 'text/html')

def plain(query_string=dict()):
	job = getJob(query_string)

	return ( template_lookup.get_template("/plain.html").render(printers=getPrinters(), job=job), 'text/html')

def getJob(query_string, returnLast=False):
	for j in jobs: 
		job = j
		if j['name'] == query_string.get('name', [''])[0]: return j
	if returnLast: return job

def getJobFile(job, key):
	docf = None
	for (groupnum, gname) in enumerate(job['groupkey']):
		for (dockey,doc) in job['groupfiles'].iteritems():
			if dockey[groupnum] == key:
				docf = doc

	return docf

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

	s = LpdServer(saveJob, ip='', port=int(config.get('Main', 'lpd_port')))
	ToyHttpServer(port=int(config.get('Main', 'http_port')), pathhandlers={
		'/recent': recent, '/index':index, '/doc':document, '/printers':printers, '/pdf':pdf,
		'/sent':sent,
		'/print' : printfn, '/plaintext':plain, '/settings/email':settings_email, '/settings/template':settings_template
		}, webroot=dir)
	try:
		while True:
			asyncore.loop(timeout=1, count=10)
			print '[control] poll %s' % str(datetime.now())
			sys.stdout.flush()

	except KeyboardInterrupt:
		print "Crtl+C pressed. Shutting down."

