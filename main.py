#!/usr/bin/env python3.11

from mako.template import Template
from mako.lookup import TemplateLookup
from mako import exceptions

import asyncio, os, re, signal
from datetime import datetime
from lpdserver import LpdServer
from httpserver import HttpServer, Redirect
import mailer
from mailer import JobMailer
from docparser import DocParser
from stationary import DocFormatter
from printing import getPrinters, printFile
import printing
import printstatus
import uploader
import webupload

import sys, pickle
import html
import urllib.parse
from io import StringIO
import collections
import traceback
import json
import time
import pytz
from settings import config, HOME
import emailtemplates
from textutil import split_lines, load_job_pickle, load_user_pickles, PICKLE_PROTOCOL

email_pickle = os.path.join(HOME, 'email.pickle')

data_dir = os.path.join(HOME, 'data') + os.sep
jobdir = os.path.join(data_dir, 'pickle')
pdfdir = os.path.join(data_dir, 'pdf/')

base_dir = os.path.dirname(os.path.abspath(__file__))
print('base_dir = ' + base_dir)
web_dir = os.path.join(base_dir, 'web')
jobs = []
mailqueue = JobMailer(100)
uploadqueue = uploader.WebUploader()

# seed some 'system' accounts
email_accounts = { 'accounts': 'Accounts', 'plain': 'printerface', 'transport': 'Transport'}
email_addresses = collections.defaultdict(dict)
# the single email text from before there were templates. Kept (and written back) so email.pickle keeps its
# layout, but only used to migrate it to templates/default.mako, see emailtemplates.migrate_legacy_default
email_template = ''

mainparser = DocParser()
formatter = DocFormatter(pdfdir)
template_lookup = TemplateLookup(directories=[web_dir], output_encoding='utf-8', encoding_errors='replace', format_exceptions=True)
loadQty = int(config.get('History', 'loadqty'))
pageQty = int(config.get('History', 'pageqty'))
base_uri = config.get('Main', 'baseuri')

summary_regexps = [ re.compile(x) for x in config.get('Main', 'summary_trim').strip().split(',') ]
local_tz = pytz.timezone(config.get('Main', 'tz'))

def saveJob(queue, local, remote, control, data):
	ts = datetime.utcnow()
	jobname = 'job-%s' % ts.strftime('%Y%m%d-%H%M%S')
	subdir = ts.strftime('%Y%m')
	d = {'queue':queue, 'from':repr(local), 'to':repr(remote), 'control':control, 'data':data, 'ts': ts, 'name':jobname}

	os.makedirs(os.path.join(jobdir, subdir), exist_ok=True)

	with open(os.path.join(jobdir, subdir, jobname), "wb") as f:
		pickle.dump(d, f, protocol=PICKLE_PROTOCOL)

	cleanJob(d)
	try:
		autoPrint(d)
	except Exception:
		# a printing problem (no lpr, no CUPS...) must not lose the job: it is already saved to disk, and
		# not registering it here would hide it from the web interface until the next restart
		traceback.print_exc(file=sys.stdout)

	jobs.insert(0, d)
	if len(jobs) > loadQty: jobs.pop()

	time.sleep(1) # hack for unique filenames - oh dear

def autoPrint(job):
	if job['autoprint']:
		printer = job['autoprint']
		for (groupnum, gname) in enumerate(job['groupkey']):
			for (dockey, doc) in job['groupfiles'].items():
				if doc:
					try:
						printFile(pdfdir + doc, printer )
						print( 'auto printing: Document %s sent to printer %s' % (doc, printer))
					except Exception as e:
						# recorded in the print history; carry on with the other documents
						print( 'auto printing: Document %s NOT sent to printer %s: %s' % (doc, printer, e))

def saveEmails():
	with open(email_pickle, 'wb') as f:
		p = pickle.Pickler(f, protocol=PICKLE_PROTOCOL)
		p.dump(email_addresses)
		p.dump(email_accounts)
		p.dump(email_template)
		print('[control] Wrote email pickles')

def recover():
	global email_template
	try:
		with open(email_pickle, 'rb') as f:
			(addresses, accounts, email_template) = load_user_pickles(f, 3)
			for (k,v) in addresses.items():
				email_addresses[k].update(v)
			email_accounts.update(accounts)

		print('recovered emails: %s' % email_addresses)
		print('recovered accounts: %s' % email_accounts)
	except IOError:
		print('[control] email pickle load failed')

	migrated = emailtemplates.migrate_legacy_default(email_template)
	if migrated:
		print('[control] ' + migrated)

	# jobdir structured /YYYYMM/job-blah-blah.pickle. We want to avoid stating
	# more dated directories than necessary, so load the
	# xs = sorted([ x for x in os.listdir(jobdir) if x != 'raw'])
	for yyyymmdir in reversed(sorted(os.listdir(jobdir))):
		print('[control] recovering jobs from %s' % yyyymmdir)
		for x in reversed(sorted( os.listdir(os.path.join(jobdir, yyyymmdir)) )):
			p = os.path.join(jobdir, yyyymmdir, x)
			if not os.path.isfile(p): continue
			try:
				with open(p, "rb") as f:
					s = load_job_pickle(f)
					s['name'] = x;
					jobs.append(s)
			except Exception as e:
				print("Cannot load {} caught {}".format(p, e))
			if len(jobs) > loadQty: break
		if len(jobs) > loadQty: break

	for j in jobs:
		cleanJob(j)

# re.ASCII: python 2 str patterns only ever treated ASCII as word/space characters, so any 8-bit
# character in the print data becomes a space. Without it \x85 etc. count as whitespace and survive.
control_char_re = re.compile(r'[^\w\s%s_\'=/]' % re.escape('.*+()-\\;:,#?%$^&!<>|`"'), re.ASCII)

def cleanJob(j):
	print(' recovering %s' % j['name'])

	# crucial to preserve \f (formfeed) in 'plain', as some parsers need it to
	# handle input
	j['plain'] = control_char_re.sub(' ', j['data'])

	summary = re.compile(r'[^\w\s]', re.ASCII).sub('', j['data'])
	for r in summary_regexps:
		summary = r.sub(' ', summary)
	summary = re.compile(r'\s+', re.ASCII).sub(' ', summary)
	summary = summary.strip()[0:120]

	j['summary'] = summary
	j['doctype'] = j.get('control', {}).get('J').strip()
	j['templ'] = identify(j)

	# ts object is from datetime.utcnow() which is unaware for compactness
	# force it to utc-aware, then convert to our local timezone for display
	ts = j['ts']
	if not ts.tzinfo:
		ts = ts.replace(tzinfo=pytz.utc)
	j['localts'] = ts.astimezone(tz=local_tz)

	j['autofmt'] = formatter.getBestPageFormat(j['plain'])

	(j['colouring'],j['parsed']) = mainparser.parse(j)
	if not j['colouring']: del j['colouring']

	if j['parsed']:
		for y in j['parsed'].values():
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

		#for f in j['groupfiles'].values():
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

def home(query_string='', resp=None):
	email_fails = sum([1 for x in mailqueue.results if x['error']])
	upload_fails = sum([1 for x in uploadqueue.log.records if x['error']]) if uploader.enabled() else None
	account = sum([ 1 for k in email_accounts if len(email_addresses[k]) > 0 ]), len(email_accounts.keys())
	return template_lookup.get_template("/home.html").render(email_fails=email_fails, upload_fails=upload_fails, account=account), 'text/html'

def getrows_byslice(seq, rowlen):
	for start in range(0, len(seq), rowlen):
		yield seq[start:start+rowlen]

def recent(query_string=dict(), resp=None):
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
				{ 'name': p['name'], 'host': p['control'].get('H'), 'doctype': p['doctype'], 'ts': p['ts'].isoformat(), 'details':
					('' if not p['templ'] else '{base}/job?name={name}'.format(base=base_uri, name=p['name'])) }
				for p in pagejobs[page]
			], 'next': '' if page >= len(pagejobs)-1 else nextQry }
		return json.dumps(output, indent=3), 'text/json'
	else:
		return template_lookup.get_template("/recent.html").render(jobs=pagejobs, page=page, pages=len(pagejobs), query=query, templ=templ, doctype=doctype), 'text/html'


def job(query_string=dict(), resp=None):
	job = getJob(query_string, returnLast=True)
	if not job:
		return doMessage(message=('Unknown job %s' % query_string) )

	output = { 'parsed': job['parsed'],
			'name': job['name'],
			'templ': job.get('templ'),
			'doctype': job.get('doctype'),
			'autofmt': job.get('autofmt'),
			'stationary':
				dict([ (' '.join(k), '{base}/pdf/{pdf}'.format(base=base_uri, pdf=v)) for k,v in job.get('groupfiles', {}).items() ])
		}
	return json.dumps(output, indent=3), 'text/json'

def printers(query_string='', resp=None):
	"""What CUPS says about the printers and the auto-print setup. Read-only: lpstat is the only thing run."""
	auto_types = [t for t in config.get('Robot', 'auto_types').split(',') if t]
	auto_printer = config.get('Robot', 'auto_printer')
	try:
		st = printstatus.status()
		error = None
		verdict = printstatus.assess(st, auto_printer)
	except printstatus.LpstatError as e:
		st, error, verdict = None, str(e), None
	return ( template_lookup.get_template("/printers.html").render(st=st, error=error, verdict=verdict,
		auto_types=auto_types, auto_printer=auto_printer, humanise=printstatus.humanise,
		now=datetime.now(), stale=printstatus.STALE_AFTER), 'text/html')

# The Sent Emails page only shows this many of the most recent emails, however long the history is: the
# history goes back years and the whole of it makes a page of many MB.
SENT_SHOWN = 100

def sent(query_string='', resp=None):
	results = mailqueue.results            # newest first; the mail thread inserts at the front
	loaded = set(j['name'] for j in jobs)
	rows = []
	for p in results[:SENT_SHOWN]:
		ref = mailer.job_ref(p.get('attachment'))
		# only jobs still in memory can be opened; for older ones the name is shown without a link
		rows.append(dict(p=p, job=ref[0] if ref else None, key=ref[1] if ref else None, loaded=bool(ref and ref[0] in loaded)))
	return ( template_lookup.get_template("/sent.html").render(rows=rows, total=len(results)), 'text/html')

def printed(query_string='', resp=None):
	results = printing.printlog.records    # newest first
	loaded = set(j['name'] for j in jobs)
	rows = [dict(p=p, loaded=p.get('job') in loaded) for p in results[:SENT_SHOWN]]
	return ( template_lookup.get_template("/printed.html").render(rows=rows, total=len(results)), 'text/html')

def settings_email(query_string='', postreq=None, resp=None):
	"""The address book. Adding and removing a contact change it, so they only happen on a POST, which then
	redirects back here: a refresh (or a bookmarked URL) shows the list and never repeats the change."""
	if postreq is not None:
		account = postreq.get('account', [''])[0]
		warning = None
		if 'delete' in postreq:
			if email_addresses[account].pop(postreq['delete'][0], None):
				saveEmails()
		elif 'email' in postreq and 'contact' in postreq:
			email = postreq['email'][0].strip()
			if account not in email_accounts:
				warning = 'Unknown account %s' % account
			elif email not in email_addresses[account]:
				email_addresses[account][email] = postreq['contact'][0]
				saveEmails()
		return Redirect('/settings/email' + ('?' + urllib.parse.urlencode({'warning': warning}) if warning else ''))

	warning = html.escape(query_string.get('warning', [''])[0]) or None
	email_list = []
	for key in sorted(email_accounts):
		email_list.append( (key, email_accounts[key], list(email_addresses[key].items())) )

	return ( template_lookup.get_template("/settings_email.html").render(emails=email_list, warning=warning), 'text/html')

def printfn(query_string='', postreq=None, resp=None):
	"""Print a document on one of the printers. Paper comes out, so only a POST does it, and it redirects back
	to the job page so that a refresh doesn't print it again."""
	if postreq is None:
		return doMessage(title='Printing', message='Documents are printed from their <a href="/recent">job page</a>.')
	job = getJob(postreq)
	docf = getJobFile(postreq, job)
	printer = postreq.get('printer', [''])[0]
	if docf and printer:
		try:
			printFile(pdfdir + docf, printer)
			key = postreq.get('key', [next(iter(job['groupfiles']))[0]])[0]
			return Redirect('/pdf?' + urllib.parse.urlencode({'name': job['name'], 'key': key, 'printed': printer}))
		except Exception as e:
			traceback.print_exc(file=sys.stdout)
			return doMessage(title='Printing', message='The document was not printed: %s<br>Source: %s sent to printer %s<br>' % (html.escape(str(e)), html.escape(str(docf)), html.escape(printer)))
	return doMessage(title='Printing', message='Could not find the document, or a problem printing it! Source: %s sent to printer %s<br>' % (html.escape(str(docf)), html.escape(printer)))

def company_info():
	printing = lambda k: config.get('Printing', k, fallback='')
	return {'name': printing('address').split('\\n')[0].strip(), 'email': printing('email'), 'website': printing('website')}

def settings_templates(query_string='', postreq=None, resp=None):
	"""Editor for the per document type email templates, with a preview against a real document. A POST
	(postreq is not None) carries the edited text and one of the actions preview, save or revert."""
	params = dict((k, v[0]) for k, v in query_string.items())
	posted = postreq is not None
	params.update(dict((k, v[0]) for k, v in (postreq or {}).items()))
	kind = params.get('kind', 'invoice')
	if kind not in emailtemplates.KINDS:
		kind = 'invoice'
	term = params.get('docnum', '').strip()
	action = params.get('action', '') if posted else ''

	def back(**flash):
		return Redirect('/settings/templates?' + urllib.parse.urlencode(dict(kind=kind, docnum=term, **flash)))

	text, source = emailtemplates.load(kind)
	message, errors = None, []
	if action == 'revert':
		return back(reverted='1' if emailtemplates.revert(kind) else '0')
	elif action in ('preview', 'save'):
		text = params.get('template', '').replace('\r\n', '\n').replace('\r', '\n')
		if action == 'save':
			try:
				emailtemplates.save(kind, text)
				return back(saved='1')
			except emailtemplates.TemplateError as e:
				errors = e.errors
	elif not posted:
		# back from a save or revert: the redirect only says which
		if params.get('saved'):
			message = 'Saved the %s template.' % emailtemplates.KINDS[kind].lower()
		elif params.get('reverted') == '1':
			message = 'Reverted to the shipped %s template.' % emailtemplates.KINDS[kind].lower()
		elif params.get('reverted') == '0':
			message = 'Already using the shipped template.'

	# preview: the newest document of this type, or the one whose document number / account matches the filter
	# (for the default template: the newest other document, or the job name / document type that matches)
	found = emailtemplates.find_document(jobs, kind, term)
	is_default = kind == emailtemplates.DEFAULT
	preview, preview_subject, preview_job, preview_acc, fields, summary_fields, names = None, None, None, None, [], [], []
	if not found:
		what = 'document' if is_default else '%s document' % emailtemplates.KINDS[kind].lower()
		preview_note = 'No %s found%s.' % (what, (' matching "%s"' % term) if term else '')
	else:
		preview_job, preview_acc = found
		contacts = email_addresses.get(preview_acc, {})
		names = list(contacts.values())
		ctx = emailtemplates.build_context(preview_job, preview_acc, names=names, addresses=list(contacts.keys()), company=company_info())
		fields = emailtemplates.field_names(ctx['doc']) if 'doc' in ctx else []
		summary_fields = emailtemplates.field_names(ctx['all']) if 'all' in ctx else []
		preview_note = None
		try:
			rendered = emailtemplates.render_message(text, ctx, kind)
			preview, preview_subject = rendered.body, rendered.subject
		except emailtemplates.TemplateError as e:
			errors = errors or e.errors

	return ( template_lookup.get_template("/settings_templates.html").render(
		kinds=emailtemplates.KINDS, kind=kind, text=text, source=source, filename=os.path.basename(emailtemplates.user_path(kind)),
		term=term, message=message, errors=errors, preview=preview, preview_subject=preview_subject, preview_note=preview_note,
		preview_job=preview_job, preview_acc=preview_acc, names=names, fields=fields, summary_fields=summary_fields, is_default=is_default), 'text/html')

def email_body(query_string=dict(), resp=None):
	"""The suggested email text for a document if only the contacts whose addresses are in 'em' are
	recipients. The compose form asks for this when contacts are ticked or unticked, since a template can use
	the recipients' names. No 'em' means no recipients. Answers {"subject": ..., "body": ..., "warning": ...}."""
	job = getJob(query_string)
	default_key = next(iter(job.get('groupfiles') or {}), ('',))[0]
	key = query_string.get('key', [default_key])[0]
	known = email_addresses.get(key, {})
	ticked = query_string.get('em', [])
	message, kind, warning = emailtemplates.render_for_job(
		job, key, names=[known[a] for a in ticked if a in known], addresses=ticked, company=company_info())
	return json.dumps({'subject': message.subject, 'body': message.body, 'warning': warning}), 'text/json'

def pdf(query_string=dict(), postreq=None, resp=None):
	"""A job's document page. Sending the email is a POST (the form); it redirects back here, so a refresh of
	the page never sends it again. A GET only ever shows the page."""
	params = dict(query_string)
	if postreq is not None:
		params.update(postreq)
	job = getJob(params)
	if not job.get('groupfiles'):
		name = params.get('name', [''])[0]
		return doMessage(title='Job not found', message='There is no job %s loaded. Only the most recent jobs are kept in memory, so older ones '
			'can\'t be opened here. <a href="/recent">Recent documents</a>' % (html.escape(name) or '(none given)'))
	default_key = next(iter(job['groupfiles']))[0]
	key = params.get('key', [default_key])[0]
	email_dest = email_addresses.get(key, {})
	email_outcome, email_error = None, None
	typed = None      # what the user typed, kept if the send is refused so that nothing has to be retyped

	if postreq is not None and params.get('action', [''])[0] == 'send':
		addresses = params.get('em', [])
		email_subject = ''.join(params.get('subject', ['']))
		email_body = ''.join(params.get('emailbody', ['']))
		docf = getJobFile(params, job)
		if len(addresses) > 0 and docf and len(email_subject) > 1:
			try:
				mailqueue.append(dict(to=addresses, body=email_body, subject=email_subject, attachment=pdfdir + docf))
				print('Queueing email to ' + ','.join(addresses))
				return Redirect('/pdf?' + urllib.parse.urlencode({'name': job['name'], 'key': key, 'queued': len(addresses)}))
			except Exception:
				traceback.print_exc(file=sys.stdout)
				email_error = "<strong>Problem!</strong> unable to queue email!"
		else:
			email_error = "<strong>Oh snap!</strong> Some fields missing or incomplete!"
		typed = dict(subject=email_subject, body=email_body, ticked=addresses)
	elif postreq is not None and params.get('action', [''])[0] == 'upload':
		try:
			if not uploader.enabled():
				raise webupload.UploadError('Uploading to the website is not set up: see [Web] in email.cfg')
			items = uploader.prepare(job, key, pdfdir)
			if not items:
				raise webupload.UploadError('There is nothing to upload for %s' % key)
			for item in items:
				uploadqueue.append(item)
			return Redirect('/pdf?' + urllib.parse.urlencode({'name': job['name'], 'key': key, 'uploading': len(items)}))
		except Exception as e:
			if not isinstance(e, webupload.UploadError):
				traceback.print_exc(file=sys.stdout)
			email_error = '<strong>Not uploaded.</strong> %s' % html.escape(str(e) or 'The upload queue is full.')
	elif postreq is None:
		# a redirect from a send or a print lands here; the note only says what happened
		try:
			queued = int(query_string.get('queued', ['0'])[0])
		except ValueError:
			queued = 0
		try:
			uploading = int(query_string.get('uploading', ['0'])[0])
		except ValueError:
			uploading = 0
		if uploading:
			email_outcome = 'Queued %d document%s for the website. %s listed under "Uploaded from this job" once done.' % (uploading, '' if uploading == 1 else 's', 'It is' if uploading == 1 else 'They are')
		elif queued:
			email_outcome = 'Queued the email to %d recipient%s. It is listed under "Sent from this job" once it has gone.' % (queued, '' if queued == 1 else 's')
		elif query_string.get('printed'):
			email_outcome = 'Sent the document to printer %s.' % html.escape(query_string['printed'][0])

	# the suggested subject and body come from the template for this type of document (or the default template)
	email_subject_default, email_body_default = '', ''
	template_kind, template_warning, template_docnum = emailtemplates.DEFAULT, None, ''
	try:
		message, template_kind, template_warning = emailtemplates.render_for_job(
			job, key, names=list(email_dest.values()), addresses=list(email_dest.keys()), company=company_info())
		email_subject_default, email_body_default = message.subject, message.body
	except Exception:
		traceback.print_exc(file=sys.stdout)
		template_warning = 'The email template for this document could not be used.'
	if typed:
		email_subject_default, email_body_default = typed['subject'], typed['body']

	# emails made from this job that are still in the sent history, newest first
	sent_from_this_job = mailer.sent_from_job(mailqueue.results, job['name'])
	# and what was sent to a printer from it, with the CUPS request ids
	printed_from_this_job = printing.printlog.for_job(job['name'])
	# and what was uploaded to the website
	uploaded_from_this_job = uploadqueue.log.for_job(job['name'])
	can_upload = uploader.enabled() and job.get('templ') in ('invoice', 'crednote', 'statement')

	# what the editor's preview filter should be set to so that it shows this document
	if template_kind == emailtemplates.DEFAULT:
		template_docnum = job.get('name', '')
	else:
		parsed = job.get('parsed') or {}
		pages = parsed.get(emailtemplates.account_for_key(parsed, key)) or [{}]
		template_docnum = pages[0].get('doc_num', '').strip()

	return ( template_lookup.get_template("/pdf.html").render(printers=getPrinters(), job=job, key=key, email_templ=email_body_default, email_subject_default=email_subject_default, ticked=typed['ticked'] if typed else None,
		template_kind=template_kind, template_warning=template_warning, template_docnum=template_docnum, sent_from_this_job=sent_from_this_job, printed_from_this_job=printed_from_this_job, uploaded_from_this_job=uploaded_from_this_job, can_upload=can_upload,
		email_body_url='/email_body?' + urllib.parse.urlencode({'name': job['name'], 'key': key}),
		email_dest=email_dest, email_outcome=email_outcome, email_error=email_error), 'text/html')


def pdf_file(query_string='', resp=None):
	docf = getJobFile(query_string)
	if docf:
		fpath = pdfdir + docf
		filename = os.path.basename(fpath)
		print('serving ' + fpath + ' as ' + filename)
		if query_string.get('attach'):
			resp.add_header('Content-Disposition', 'attachment; filename="' + filename + '"')
		with open(fpath, 'rb') as f:
			content = f.read()
		return content, 'application/pdf'

def plain(query_string=dict(), resp=None):
	job = getJob(query_string, returnLast=True)

	return ( template_lookup.get_template("/plain.html").render(printers=getPrinters(), job=job, pb='always'), 'text/html')

def raw(query_string=dict(), resp=None):
	job = getJob(query_string, returnLast=True)
	return job['plain'], 'text/plain'

def getJob(query_string, returnLast=False):
	for j in jobs:
		job = j
		if j['name'] == query_string.get('name', [''])[0]: return j
	if len(jobs) > 0 and returnLast: return jobs[0]
	return {'name': 'None', 'plain':'none'}

def getJobFile(query_string, job=None):
	if not job:
		job = getJob(query_string)
	if not job.get('groupfiles'):
		return None
	default_key = next(iter(job['groupfiles']))[0]
	key = query_string.get('key', [default_key])[0]

	docf = None
	for (groupnum, gname) in enumerate(job['groupkey']):
		for (dockey,doc) in job['groupfiles'].items():
			if dockey[groupnum] == key:
				docf = doc

	return docf

def doMessage(message='?', title='Printerface'):
	return ( template_lookup.get_template("/message.html").render(title=title, message=message), 'text/html')

def debug(query_string=dict(), resp=None):
	job = getJob(query_string, returnLast=True)

	if not job:
		return doMessage(message=('Unknown job %s' % query_string) )

	pformatted = json.dumps(job.get('parsed'), indent=4)

	colouring = job.get('colouring', [])

	lines = split_lines(job['plain'])
	(rows, cols) = (len(lines), max([len(line) for line in lines]))

	cols = max([cols] + [c['c']+c['w'] for c in colouring])
	rows = max([rows] + [c['r']+c['h'] for c in colouring])

	high = [[None for col in range(cols)] for row in range(rows)]

	for c in colouring:
		for row in range(c['r'], c['r']+c['h']):
			for col in range(c['c'], c['c']+c['w']):
				high[row][col] = c

	chunks10 = (cols+9)//10
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
			if char == '\f':
				f.write('F')
			else:
				f.write(char)
			last_fmt = high[row][col]
		if last_fmt:
			last_fmt = None
			f.write('</span>')

	return ( template_lookup.get_template("/debug.html").render( job=job,
			rows=rows, cols=cols, coloured_plaintext=f.getvalue(), pformatted=pformatted), 'text/html')

path_handlers = {
	'/recent': recent,
	'/home':home,
	'/debug':debug,
	'/raw':raw,
	'/job': job,
	'/printers':printers,
	'/pdf':pdf,
	'/pdf_file': pdf_file,
	'/sent':sent,
	'/printed':printed,
	'/print' : printfn,
	'/plaintext':plain,
	'/settings/email':settings_email,
	'/settings/templates':settings_templates,
	'/email_body':email_body
	}

async def serve():
	"""Run the LPD receiver and the web server on one event loop until interrupted."""
	mailqueue.start()
	uploadqueue.start()
	lpd = await LpdServer(saveJob, ip='', port=int(config.get('Main', 'lpd_port'))).start()
	http = await HttpServer(path_handlers, web_dir, port=int(config.get('Main', 'http_port'))).start()
	stopping = asyncio.Event()
	for sig in (signal.SIGINT, signal.SIGTERM):
		try:
			asyncio.get_running_loop().add_signal_handler(sig, stopping.set)
		except NotImplementedError:
			pass  # windows: Ctrl+C is raised as KeyboardInterrupt instead
	try:
		while not stopping.is_set():
			try:
				await asyncio.wait_for(stopping.wait(), 10)
			except asyncio.TimeoutError:
				pass
			print('[control] poll %s' % str(datetime.now()))
			printing.printlog.flush()
			uploadqueue.log.flush()
			sys.stdout.flush()
		print("Shutting down.")
	except BaseException as e:
		print("Terminating: Unexpected error: %s" % repr(e))
		sys.stdout.flush()
		raise
	finally:
		printing.printlog.flush()
		await uploadqueue.close()
		uploadqueue.log.flush()
		await lpd.close()
		await http.close()
		await mailqueue.close()

if __name__=="__main__":
	# launch the server on the specified port
	for x in [jobdir, pdfdir]:
		os.makedirs(x, exist_ok=True)

	recover()

	try:
		asyncio.run(serve())
	except KeyboardInterrupt:
		print("Crtl+C pressed. Shutting down.")
