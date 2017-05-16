#!/usr/bin/env python2.7

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
import json

config = ConfigParser.ConfigParser()
config.readfp(open(os.path.expanduser('defaults.cfg')))
config.read(os.path.expanduser('~/printerface/email.cfg'))

email_pickle = os.path.expanduser('~/printerface/email.pickle')

data_dir = os.path.expanduser("~/printerface/data/")
jobdir = os.path.join(data_dir, 'pickle')
pdfdir = os.path.join(data_dir, 'pdf/')
web_dir = os.path.expanduser("~/repos/printerface/web/")
jobs = []
mailqueue = JobMailer(100)

# seed some 'system' accounts
email_accounts = { 'accounts': 'Accounts', 'plain': 'printerface', 'transport': 'Transport'}
email_addresses = collections.defaultdict(dict)
email_template = ''

mainparser = DocParser()
formatter = DocFormatter(pdfdir)
template_lookup = TemplateLookup(directories=[web_dir], output_encoding='utf-8', encoding_errors='replace', format_exceptions=True)
loadQty = int(config.get('History', 'loadqty'))
pageQty = int(config.get('History', 'pageqty'))
base_uri = config.get('Main', 'baseuri')

summary_regexps = [ re.compile(x) for x in config.get('Main', 'summary_trim').strip().split(',') ]
	
def saveJob(queue, local, remote, control, data):
	ts = datetime.utcnow()
	jobname = 'job-%s' % ts.strftime('%Y%m%d-%H%M%S')
	subdir = ts.strftime('%Y%m')
	d = {'queue':queue, 'from':repr(local), 'to':repr(remote), 'control':control, 'data':data, 'ts': ts, 'name':jobname}

	try:
		os.makedirs(os.path.join(jobdir, subdir))
	except:
		pass

	f = file(os.path.join(jobdir, subdir, jobname), "wb")
	pickle.dump(d, f)
	f.close()

	cleanJob(d)
	autoPrint(d)

	jobs.insert(0, d)
	if len(jobs) > loadQty: jobs.pop()

def autoPrint(j):
	if j['autoprint']:
		ptr = j['autoprint']
		default_key = j['groupfiles'].iterkeys().next()[0]
		#key = query_string.get('key', [default_key])[0]
		docf = getJobFile( j, default_key)
		if docf:
			printFile(pdfdir + docf, ptr )
			print( 'auto printing: Document %s sent to printer %s' % (docf, ptr))


def saveEmails():
	with open(email_pickle, 'wb') as f:
		p = pickle.Pickler(f)
		p.dump(email_addresses)
		p.dump(email_accounts)
		p.dump(email_template)
		print('[control] Wrote email pickles')

def recover():
	global email_template
	try:
		with open(email_pickle, 'rb') as f:
			p = pickle.Unpickler(f)
			for (k,v) in p.load().iteritems():
				email_addresses[k].update(v)
			email_accounts.update(p.load())
			email_template = p.load()

		print('recovered emails: %s' % email_addresses)
		print('recovered accounts: %s' % email_accounts)
	except IOError:
		print('[control] email pickle load failed')

	# jobdir structured /YYYYMM/job-blah-blah.pickle. We want to avoid stating
	# more dated directories than necessary, so load the 
	# xs = sorted([ x for x in os.listdir(jobdir) if x != 'raw'])
	for yyyymmdir in reversed(sorted(os.listdir(jobdir))):
		print('[control] recovering jobs from %s' % yyyymmdir)
		for x in reversed(sorted( os.listdir(os.path.join(jobdir, yyyymmdir)) )):
			p = os.path.join(jobdir, yyyymmdir, x)
			if not os.path.isfile(p): continue
			with file(p, "rb") as f:
				s = pickle.load(f)
				s['name'] = x;
				jobs.append(s)				
			if len(jobs) > loadQty: break
		if len(jobs) > loadQty: break

	for j in jobs:
		cleanJob(j)

control_char_re = re.compile('[^\w\s%s_\'=/]' % re.escape('.*+()-\\;:,#?%$^&!<>|`"'))

def cleanJob(j):
	print(' recovering %s' % j['name'])
	
	j['plain'] = control_char_re.sub(' ', j['data'])
	
	summary = re.compile('[^\w\s]').sub('', j['data'])
	for r in summary_regexps:
		summary = r.sub(' ', summary)
	summary = re.compile('\s+').sub(' ', summary)
	summary = summary.strip()[0:120]

	j['summary'] = summary
	j['doctype'] = j.get('control', {}).get('J').strip()
	j['templ'] = identify(j)

	j['autofmt'] = formatter.getBestPageFormat(j['plain'])

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
				if acc and addr:
					print("   got email %s -> %s" % (acc, addr))
					email_accounts[acc] = (addr),

	# if colouring succeded, might be able to generate docs
	if j.get('colouring'):
		# protocol: PDF file names are dict values. keys are document
		# groups {('all'): p}, ('all')
		(j['groupfiles'], j['groupkey']) = formatter.format(j)

		#for f in j['groupfiles'].itervalues():
		#	from subprocess import call
		#	proc = ['convert','-size','150x150','%s[0]' % f, '%s.png' % f]
		#	print(proc)
		#	call(proc)
	else:
		(j['groupfiles'], j['groupkey']) = formatter.plainFormat(j)
	
	# all done
	j['autoprint'] = None
	if j['doctype'] in config.get('Robot', 'auto_types').split(','):
		j['autoprint'] = config.get('Robot', 'auto_printer')

def identify(j):
	types = {
			'Sttments': 'statement',
			'Delvnote':'delnote',
			'Cr-note':'crednote',
			'Invoice':'invoice',
			'P order':'purchase',
			'Rem Advs':'remittance',
			'Pick lst': 'picklist'
			}
	return types.get(j['doctype'])

def home(query_string=''):
	email_fails = sum([1 for x in mailqueue.results if x['error']])
	account = sum([ 1 for k in email_accounts.iterkeys() if len(email_addresses[k]) > 0 ]), len(email_accounts.keys())
	return template_lookup.get_template("/home.html").render(email_fails=email_fails, account=account), 'text/html'

def getrows_byslice(seq, rowlen):
    for start in xrange(0, len(seq), rowlen):
        yield seq[start:start+rowlen]

def recent(query_string=dict()):
	query = query_string.get('query', [''])[0]
	templ = query_string.get('templ', [''])[0]
	doctype = query_string.get('doctype', [''])[0]
	fmt = query_string.get('fmt', ['html'])[0]
	res = []
	for j in jobs:
		if not query or query in j['plain']:
			if not templ or templ == j['templ']:
				if not doctype or doctype == j['doctype']:
					res.append(j)

	pagejobs = list(getrows_byslice(res, pageQty))
	page = max(min(int(query_string.get('page', ['0'])[0]), len(pagejobs)-1),0)
	print('recent pages=%d page=%d q=%s' % (len(pagejobs), page, query))
	if fmt == 'json':
		nextQry = base_uri + '/recent?query={query}&templ={templ}&doctype={doctype}&page={page}&fmt={fmt}'.format(query=query, templ=templ, doctype=doctype, page=page+1, fmt=fmt)
		output = { 'results': [
				{ 'name': p['name'], 'host': p['control'].get('H'), 'doctype': p['doctype'], 'ts': j['ts'].isoformat(), 'details':
					('' if not p['templ'] else '{base}/job?name={name}'.format(base=base_uri, name=p['name'])) }
				for p in pagejobs[page]
			], 'next': '' if page >= len(pagejobs)-1 else nextQry }
		return json.dumps(output, indent=3), 'text/json'
	else:
		return template_lookup.get_template("/recent.html").render(jobs=pagejobs, page=page, pages=len(pagejobs), query=query, templ=templ, doctype=doctype), 'text/html'


def job(query_string=dict()):
	job = getJob(query_string, returnLast=True)
	if not job:
		return doMessage(message=('Unknown job %s' % query_string) )

	output = { 'parsed': job['parsed'],
			'name': job['name'],
			'templ': job.get('templ'),
			'doctype': job.get('doctype'),
			'autofmt': job.get('autofmt'),
			'stationary':
				dict([ (' '.join(k), '{base}/pdf/{pdf}'.format(base=base_uri, pdf=v)) for k,v in job.get('groupfiles', {}).iteritems() ])
		}
	return json.dumps(output, indent=3), 'text/json'

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
					attachment=pdfdir + docf))
			except:
				traceback.print_exc(file=sys.stdout)
				email_error = "<strong>Problem!</strong> unable to queue email!"
		elif action:
			email_error = "<strong>Oh snap!</strong> Some fields missing or incomplete!"
	except:
		raise

	return ( template_lookup.get_template("/pdf.html").render(printers=getPrinters(), job=job, key=key, email_templ=email_template, email_dest=email_dest, email_outcome=email_outcome, email_error=email_error), 'text/html')

def plain(query_string=dict()):
	job = getJob(query_string, returnLast=True)

	return ( template_lookup.get_template("/plain.html").render(printers=getPrinters(), job=job, pb='always'), 'text/html')

def raw(query_string=dict()):
	job = getJob(query_string, returnLast=True)
	return job['plain'], 'text/plain'

def getJob(query_string, returnLast=False):
	for j in jobs: 
		job = j
		if j['name'] == query_string.get('name', [''])[0]: return j
	if len(jobs) > 0 and returnLast: return jobs[0]
	return {'name': 'None', 'plain':'none'}

def getJobFile(job, key):
	docf = None
	for (groupnum, gname) in enumerate(job['groupkey']):
		for (dockey,doc) in job['groupfiles'].iteritems():
			if dockey[groupnum] == key:
				docf = doc

	return docf

def doMessage(message='?', title='Printerface'):
	return ( template_lookup.get_template("/message.html").render(title=title, message=message), 'text/html')

def debug(query_string=dict()):
	job = getJob(query_string, returnLast=True)

	if not job:
		return doMessage(message=('Unknown job %s' % query_string) )

	pformatted = json.dumps(job.get('parsed'), indent=4)

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

	chunks10 = (cols+9)/10
	f = StringIO()
	f.write('     ' +  ''.join(["%-10d" % (d*10) for d in range(chunks10)]))
	f.write('\n     ' + ('0123456789' * chunks10))

	def htmlcol(rgb):
		return ''.join([('%02x' % int(c*256)) for c in rgb])

	last_fmt = None
	for (row,line) in enumerate(lines):
		f.write('\n%-4d ' % row)
		pad = ' '*(max(0,len(high[row])-len(line)))
		for col,char in enumerate(line + pad):
			if high[row][col] != last_fmt:
				if last_fmt: 
					f.write('</span>')
				if high[row][col]: 
					f.write('<span title="%s" style="background-color: #%s">' % (high[row][col]['t'],htmlcol(high[row][col]['rgb'])))
			f.write(char)
			last_fmt = high[row][col]
		if last_fmt:
			last_fmt = None
			f.write('</span>')
	
	return ( template_lookup.get_template("/debug.html").render( job=job,
			rows=rows, cols=cols, coloured_plaintext=f.getvalue(), pformatted=pformatted), 'text/html')

if __name__=="__main__":
	# launch the server on the specified port
	for x in [jobdir, pdfdir]:
		try:
			os.makedirs(x)
		except:
			pass

	recover()

	s = LpdServer(saveJob, ip='', port=int(config.get('Main', 'lpd_port')))
	ToyHttpServer(port=int(config.get('Main', 'http_port')), pathhandlers={
		'/recent': recent,
		'/home':home,
		'/debug':debug,
		'/raw':raw,
		'/job': job,
		'/printers':printers,
		'/pdf':pdf,
		'/sent':sent,
		'/print' : printfn,
		'/plaintext':plain,
		'/settings/email':settings_email,
		'/settings/template':settings_template
		}, webroot=web_dir)
	try:
		while True:
			asyncore.loop(timeout=1, count=10)
			print('[control] poll %s' % str(datetime.now()))
			sys.stdout.flush()

	except KeyboardInterrupt:
		print("Crtl+C pressed. Shutting down.")
	except:
		print("Terminating: Unexpected error: %s", sys.exc_info()[0])
		sys.stdout.flush()
		raise

