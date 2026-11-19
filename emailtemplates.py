# Email body templates, one per document type.
#
# The text offered when emailing a document is rendered from a Mako template chosen by the type of the
# job: invoice, purchase order or statement, and 'default' for every other kind of document (credit notes,
# delivery notes, reports...). Templates are looked up in USER_DIR (~/printerface/templates)
# first and fall back to the copies shipped with the source in SEED_DIR, so an install that has never
# customised a template keeps following the repository. The web editor saves into USER_DIR.
#
# SECURITY: Mako can run arbitrary python and the web interface has no authentication. Anything that
# comes from the editor (previews included) is therefore checked by validate() first, which only allows
# plain text, ${field.lookups}, 'for ... in docs', simple 'if' tests and comments. There are no calls, no
# <% %> blocks, no operators and no names starting with an underscore, so a template cannot reach
# anything but the document data it is given.
import collections
import os
import re
import unittest

from mako.template import Template

from settings import BASE_DIR, HOME

KINDS = collections.OrderedDict([('invoice', 'Invoice'), ('purchase', 'Purchase order'), ('statement', 'Statement'), ('default', 'Default')])
# job['templ'] -> template kind. Anything else uses 'default', which can only see the recipients and the job.
KIND_FOR_TEMPL = {'invoice': 'invoice', 'purchase': 'purchase', 'statement': 'statement'}
DEFAULT = 'default'

SEED_DIR = os.path.join(BASE_DIR, 'templates')
USER_DIR = os.path.join(HOME, 'templates')

ENCODING = 'utf-8'
NO_NAME = 'Sir or Madam'

class TemplateError(Exception):
	def __init__(self, errors):
		Exception.__init__(self, '; '.join(errors))
		self.errors = errors

# ---------------------------------------------------------------------------------------------- context

class Fields(object):
	"""Read-only attribute access to a dict of values. A field that does not exist reads as '' so that a
	template written for one document layout never fails on another."""
	def __init__(self, values):
		self.__dict__.update(values)

	def __getattr__(self, name):
		if name.startswith('_'):
			raise AttributeError(name)
		return ''

def field_names(fields):
	return sorted(k for k in vars(fields))

def merge_documents(pages):
	"""Pages of one account in a job -> one dict per document (grouped by document number, in print order).
	A document's totals are only printed on its last page, so a later non-empty value replaces an earlier
	one. Statements have no document number: all their pages are one document."""
	docs = collections.OrderedDict()
	for page in pages:
		d = docs.setdefault(page.get('doc_num', '').strip(), {})
		for k, v in page.items():
			v = v.strip() if isinstance(v, str) else v
			if v or k not in d:
				d[k] = v
	for d in docs.values():
		d['customer'] = d.get('addr_invoice', '').split('\n')[0].strip()
	return list(docs.values())

def account_for_key(parsed, key):
	"""PDF group key -> account code. Purchase orders also have '<account>-admin' and '<account>-transport'."""
	if key in parsed:
		return key
	for suffix in ('-admin', '-transport'):
		if key.endswith(suffix) and key[:-len(suffix)] in parsed:
			return key[:-len(suffix)]
	return None

def join_names(names):
	names = [n.strip() for n in dict.fromkeys(names) if n and n.strip()]
	if not names:
		return NO_NAME
	if len(names) == 1:
		return names[0]
	return ', '.join(names[:-1]) + ' and ' + names[-1]

def kind_for_job(job):
	return KIND_FOR_TEMPL.get(job.get('templ'), DEFAULT)

def build_context(job, key, names=(), addresses=(), company=None):
	"""The variables a template sees:
	  doc      the document (the last one, if the account has several in this print run); doc.<field>
	  docs     every document for the account in this print run, for '% for d in docs:'
	  email    the recipients: email.name ('Ann and Bob', or 'Sir or Madam' with none), email.address
	  job      job.name, job.doctype, job.host
	  company  company.name, company.email, company.website, from the [Printing] settings
	The default template sees only email and job: the other document types have no fields we know of."""
	addresses = [a for a in addresses if a]
	context = dict(
		email=Fields({'name': join_names(names), 'address': addresses[0] if addresses else ''}),
		job=Fields({'name': job.get('name', ''), 'doctype': job.get('doctype', ''), 'host': (job.get('control') or {}).get('H', '')}))
	if kind_for_job(job) == DEFAULT:
		return context
	parsed = job.get('parsed') or {}
	acc = account_for_key(parsed, key)
	docs = merge_documents(parsed[acc]) if acc else []
	context.update(doc=Fields(docs[-1] if docs else {}), docs=[Fields(d) for d in docs], company=Fields(company or {}))
	return context

def find_document(jobs, kind, term=''):
	"""The filter behind the editor's preview. jobs is newest first. Returns (job, key) for the newest
	document of this kind whose document number, or account code, equals term (ignoring case and spaces),
	or for the newest document of this kind if term is empty. None if there isn't one.
	For the default kind there are no document numbers: term matches the job name or the document type
	(for example 'Delvnote'), and key is the job's first PDF group, as the compose form would use."""
	norm = lambda s: re.sub(r'\s+', '', s or '').lower()
	want = norm(term)
	for job in jobs:
		if kind_for_job(job) != kind:
			continue
		if kind == DEFAULT:
			if not want or want in (norm(job.get('name')), norm(job.get('doctype'))):
				return job, next(iter(job.get('groupfiles') or {}), ('',))[0]
			continue
		for acc, pages in (job.get('parsed') or {}).items():
			for d in merge_documents(pages):
				if not want or want in (norm(d.get('doc_num')), norm(d.get('accno'))):
					return job, acc
	return None

# ------------------------------------------------------------------------------------------ validation

# a name may contain, but not start with, an underscore: field names are like tot_due, and this keeps __dunder__ out
_PATH = r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)*'
_EXPR = re.compile(r'^\s*(%s)\s*(?:\|\s*trim\s*)?$' % _PATH)
_FOR = re.compile(r'^\s*%\s*for\s+([a-z][a-z0-9]*)\s+in\s+docs\s*:\s*$')
_IF = re.compile(r'^\s*%%\s*if\s+(?:not\s+)?(%s)\s*:\s*$' % _PATH)
_ELSE = re.compile(r'^\s*%\s*else\s*:\s*$')
_END = re.compile(r'^\s*%\s*(?:endif|endfor)\s*$')
_ROOTS = frozenset(['doc', 'email', 'job', 'company'])
_DEFAULT_ROOTS = frozenset(['email', 'job'])

def validate(text, kind=None):
	"""Returns a list of 'line N: problem' strings; empty if the template is safe to render as this kind
	of template (the default template can only use email and job)."""
	errors = []
	loop_vars = set()
	lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
	for line in lines:
		m = _FOR.match(line)
		if m:
			loop_vars.add(m.group(1))
	roots = (_DEFAULT_ROOTS if kind == DEFAULT else _ROOTS) | loop_vars

	def check_path(n, path, where):
		root = path.split('.')[0]
		if root not in roots:
			errors.append('line %d: unknown name "%s" in %s (use %s)' % (n, root, where, ', '.join(sorted(roots))))

	for n, line in enumerate(lines, 1):
		if line.endswith('\\'):
			errors.append('line %d: a line may not end with a backslash' % n)
		if '<%' in line or '</%' in line:
			errors.append('line %d: <%% %%> blocks are not allowed' % n)
			continue
		stripped = line.lstrip()
		if stripped.startswith('##'):
			continue
		if stripped.startswith('%'):
			m = _IF.match(line)
			if m:
				check_path(n, m.group(1), 'the condition')
			elif _FOR.match(line) and kind == DEFAULT:
				errors.append('line %d: there are no documents to loop over in the default template' % n)
			elif not (_FOR.match(line) or _ELSE.match(line) or _END.match(line)):
				errors.append('line %d: only "%% for x in docs:", "%% if field:", "%% if not field:", "%% else:", "%% endif" and "%% endfor" are allowed' % n)
			continue
		found = 0
		for em in re.finditer(r'\$\{(.*?)\}', line):
			found += 1
			m = _EXPR.match(em.group(1))
			if not m:
				errors.append('line %d: "${%s}" is not allowed; use ${doc.field} or ${doc.field | trim}' % (n, em.group(1).strip()))
			else:
				check_path(n, m.group(1), '${%s}' % em.group(1).strip())
		if line.count('${') != found:
			errors.append('line %d: unterminated ${' % n)
	if not errors:
		try:
			Template(text)
		except Exception as e:
			errors.append('template structure: %s' % (str(e).splitlines() or ['invalid'])[0])
	return errors

def render(text, context, kind=None):
	errors = validate(text, kind)
	if errors:
		raise TemplateError(errors)
	try:
		out = Template(text, strict_undefined=True).render_unicode(**context)
	except Exception as e:
		raise TemplateError(['%s: %s' % (type(e).__name__, e)])
	return out.rstrip() + '\n'

# ------------------------------------------------------------------------------------------ storage

def _check_kind(kind):
	if kind not in KINDS:
		raise KeyError('unknown template %r' % (kind,))

def user_path(kind):
	_check_kind(kind)
	return os.path.join(USER_DIR, kind + '.mako')

def seed_path(kind):
	_check_kind(kind)
	return os.path.join(SEED_DIR, kind + '.mako')

def load(kind):
	"""(text, 'custom' | 'default'): the user's template if they have one, else the one shipped in the source."""
	for source, path in (('custom', user_path(kind)), ('default', seed_path(kind))):
		if os.path.isfile(path):
			with open(path, encoding=ENCODING) as f:
				return f.read(), source
	raise FileNotFoundError(seed_path(kind))

def save(kind, text):
	text = text.replace('\r\n', '\n').replace('\r', '\n')
	if not text.endswith('\n'):
		text += '\n'
	errors = validate(text, kind)
	if errors:
		raise TemplateError(errors)
	path = user_path(kind)
	os.makedirs(USER_DIR, exist_ok=True)
	tmp = path + '.tmp'
	with open(tmp, 'w', encoding=ENCODING, newline='\n') as f:
		f.write(text)
	os.replace(tmp, path)

def revert(kind):
	"""Delete the user's copy so the shipped template applies again. True if there was one."""
	path = user_path(kind)
	if os.path.isfile(path):
		os.remove(path)
		return True
	return False

MIGRATED_MARKER = '.legacy-default-text-migrated'

def migrate_legacy_default(text):
	"""Before there were per type templates a single email text was kept in email.pickle. Offer that text as
	the default template, once, unless the user already has a default.mako. A marker file stops it coming back
	if they later revert to the shipped default. Returns a message to log, or None if there was nothing to do."""
	marker = os.path.join(USER_DIR, MIGRATED_MARKER)
	if not (text or '').strip() or os.path.exists(marker) or os.path.exists(user_path(DEFAULT)):
		return None
	try:
		save(DEFAULT, text)
		message = 'migrated the old email text to %s' % user_path(DEFAULT)
	except TemplateError as e:
		message = 'could not migrate the old email text (%s); it is still in email.pickle' % e
	os.makedirs(USER_DIR, exist_ok=True)
	open(marker, 'w').close()
	return message

def render_for_job(job, key, names=(), addresses=(), company=None):
	"""(body, kind, warning) for the compose form. A user template that no longer renders falls back to
	the shipped one, with a warning."""
	kind = kind_for_job(job)
	context = build_context(job, key, names, addresses, company)
	text, source = load(kind)
	try:
		return render(text, context, kind), kind, None
	except TemplateError as e:
		if source != 'custom':
			raise
		body = render(open(seed_path(kind), encoding=ENCODING).read(), context, kind)
		return body, kind, 'Your %s template could not be used (%s); showing the default.' % (KINDS[kind].lower(), e)

# ----------------------------------------------------------------------------------------------- tests

class TestEmailTemplates(unittest.TestCase):
	def pages(self):
		return [
			{'doc_num': '336769', 'ourref': '289073', 'accno': 'HAR108', 'tot_due': '', 'addr_invoice': 'HISTORIC HOUSE\nAYLESBURY\n\n', 'page': '1'},
			{'doc_num': '336769', 'ourref': '289073', 'accno': 'HAR108', 'tot_due': '1,234.50', 'addr_invoice': 'HISTORIC HOUSE\nAYLESBURY\n\n', 'page': '2'},
			{'doc_num': '336770', 'ourref': '289099', 'accno': 'HAR108', 'tot_due': '10.00', 'addr_invoice': 'HISTORIC HOUSE\n', 'page': '1'},
		]

	def job(self, templ='invoice', name='job-1'):
		return {'name': name, 'templ': templ, 'doctype': 'Invoice', 'control': {'H': 'SALES-PC'}, 'parsed': {'HAR108': self.pages()}}

	def test_merge_documents_takes_totals_from_the_last_page(self):
		docs = merge_documents(self.pages())
		self.assertEqual(['336769', '336770'], [d['doc_num'] for d in docs])
		self.assertEqual('1,234.50', docs[0]['tot_due'])
		self.assertEqual('HISTORIC HOUSE', docs[0]['customer'])
		self.assertEqual('2', docs[0]['page'])

	def test_statement_pages_without_doc_num_are_one_document(self):
		docs = merge_documents([{'accno': 'A', 'tot_topay': ''}, {'accno': 'A', 'tot_topay': '5.00'}])
		self.assertEqual(1, len(docs))
		self.assertEqual('5.00', docs[0]['tot_topay'])

	def test_account_for_key(self):
		parsed = {'APA100': [], 'MULTI-21': []}
		self.assertEqual('APA100', account_for_key(parsed, 'APA100'))
		self.assertEqual('APA100', account_for_key(parsed, 'APA100-admin'))
		self.assertEqual('APA100', account_for_key(parsed, 'APA100-transport'))
		self.assertEqual('MULTI-21', account_for_key(parsed, 'MULTI-21'))
		self.assertIsNone(account_for_key(parsed, 'accounts'))

	def test_join_names(self):
		self.assertEqual(NO_NAME, join_names([]))
		self.assertEqual('Ann', join_names(['Ann', 'Ann', ' ']))
		self.assertEqual('Ann and Bob', join_names(['Ann', 'Bob']))
		self.assertEqual('Ann, Bob and Cy', join_names(['Ann', 'Bob', 'Cy']))

	def test_shipped_templates_are_valid_and_the_invoice_text_is_as_specified(self):
		for kind in KINDS:
			text = open(seed_path(kind), encoding=ENCODING).read()
			self.assertEqual([], validate(text, kind), kind)
		ctx = build_context(self.job(), 'HAR108', names=['Ann'])
		body = render(open(seed_path('invoice'), encoding=ENCODING).read(), ctx)
		self.assertEqual('To Ann\n\nPlease find your latest invoice 289099 attached for account HAR108, for \xa310.00.\n', body)

	def test_shipped_templates_render_with_no_data_at_all(self):
		for kind in KINDS:
			body = render(open(seed_path(kind), encoding=ENCODING).read(), build_context({'templ': kind}, 'nothing'), kind)
			self.assertTrue(body.startswith('To ' + NO_NAME), kind)

	def test_other_document_types_use_the_default_template(self):
		for templ in ('delnote', 'crednote', 'picklist', None):
			body, kind, warning = render_for_job({'templ': templ, 'name': 'job-9', 'doctype': 'Delvnote'}, 'X', ['Ann'])
			self.assertEqual(('To Ann\n\nPlease find your document attached.\n', DEFAULT, None), (body, kind, warning), templ)

	def test_the_default_context_is_only_email_and_job(self):
		ctx = build_context({'templ': 'delnote', 'name': 'job-9', 'doctype': 'Delvnote', 'control': {'H': 'PC1'}}, 'X', ['Ann'], ['a@b.c'], {'name': 'ABFW'})
		self.assertEqual(['email', 'job'], sorted(ctx))
		self.assertEqual(('Ann', 'a@b.c', 'job-9', 'Delvnote', 'PC1'), (ctx['email'].name, ctx['email'].address, ctx['job'].name, ctx['job'].doctype, ctx['job'].host))
		self.assertEqual([], validate('${email.name} ${job.doctype | trim}\n% if job.host:\nx\n% endif', DEFAULT))
		for text in ('${doc.ourref}', '${company.name}', '% for d in docs:\n% endfor', '% if doc.x:\n% endif'):
			self.assertTrue(validate(text, DEFAULT), text)
			if 'docs' not in text:
				self.assertEqual([], validate(text, 'invoice'), text)       # fine for a document type that has them

	def test_migrate_legacy_default_text_once(self):
		import tempfile
		global USER_DIR
		old, USER_DIR = USER_DIR, os.path.join(tempfile.mkdtemp(prefix='printerface-test-'), 'templates')
		try:
			self.assertIsNone(migrate_legacy_default(''))
			self.assertIsNone(migrate_legacy_default('   \r\n'))
			self.assertFalse(os.path.exists(user_path(DEFAULT)))
			self.assertIn('migrated', migrate_legacy_default('Please find it attached.\r\n\r\nRegards,\r\nTony'))
			self.assertEqual(('Please find it attached.\n\nRegards,\nTony\n', 'custom'), load(DEFAULT))
			# a user who reverts to the shipped text does not get the old text back at the next start
			revert(DEFAULT)
			self.assertIsNone(migrate_legacy_default('Please find it attached.'))
			self.assertEqual('default', load(DEFAULT)[1])
		finally:
			import shutil
			shutil.rmtree(os.path.dirname(USER_DIR), ignore_errors=True)
			USER_DIR = old

	def test_migrate_never_overwrites_or_imports_unsafe_text(self):
		import tempfile
		global USER_DIR
		old, USER_DIR = USER_DIR, os.path.join(tempfile.mkdtemp(prefix='printerface-test-'), 'templates')
		try:
			save(DEFAULT, 'mine')
			self.assertIsNone(migrate_legacy_default('legacy'))
			self.assertEqual('mine\n', load(DEFAULT)[0])
			revert(DEFAULT)
			self.assertIn('could not migrate', migrate_legacy_default("${__import__('os')}"))
			self.assertEqual('default', load(DEFAULT)[1])
		finally:
			import shutil
			shutil.rmtree(os.path.dirname(USER_DIR), ignore_errors=True)
			USER_DIR = old

	def test_validate_accepts_the_safe_subset(self):
		ok = '''## a comment ${anything()}
To ${email.name | trim}
% for d in docs:
Invoice ${d.ourref}: ${d.tot_due}
% endfor
% if doc.tot_due:
Total ${doc.tot_due}
% else:
none
% endif
% if not doc.customer:
x
% endif
50% off, 100% sure
'''
		self.assertEqual([], validate(ok))

	def test_validate_rejects_anything_that_could_run_code(self):
		bad = [
			"${__import__('os').system('id')}",
			'${doc.__class__}',
			'${doc.ourref()}',
			'${doc.ourref + doc.accno}',
			'${open("/etc/passwd").read()}',
			'${os.getcwd}',
			'${doc.ourref | h}',
			'${doc.ourref',
			'<% import os %>',
			'<%! import os %>',
			'<%include file="x"/>',
			'% import os',
			'% for x in range(3):\n% endfor',
			'% if doc.a == 1:\n% endif',
			'% if doc.a:\n% endif\n%% x',
			'${doc.ourref}\\\n% import os',
			'% for x in docs:\n${y.ourref}\n% endfor',
		]
		for text in bad:
			self.assertTrue(validate(text), text)
		with self.assertRaises(TemplateError):
			render("${__import__('os').system('true')}", build_context({}, 'x'))

	def test_comments_are_never_evaluated(self):
		# validate() skips '##' lines, so make sure mako really does too (strict_undefined would raise)
		self.assertEqual('hello\n', render('## ${nothing.defined.here}\nhello', build_context({}, 'x')))
		# ...but <% is refused everywhere, comment or not
		self.assertTrue(validate('## <% x %>'))

	def test_validate_reports_unbalanced_blocks(self):
		self.assertTrue(validate('% if doc.a:\nx\n'))

	def test_storage_custom_overrides_shipped_and_revert_restores(self):
		import tempfile
		global USER_DIR
		old, USER_DIR = USER_DIR, os.path.join(tempfile.mkdtemp(prefix='printerface-test-'), 'templates')
		try:
			text, source = load('invoice')
			self.assertEqual('default', source)
			save('invoice', 'Hello ${email.name}\r\nbye')
			text, source = load('invoice')
			self.assertEqual(('Hello ${email.name}\nbye\n', 'custom'), (text, source))
			with self.assertRaises(TemplateError):
				save('invoice', '${__import__("os")}')
			self.assertEqual('Hello ${email.name}\nbye\n', load('invoice')[0])
			self.assertTrue(revert('invoice'))
			self.assertFalse(revert('invoice'))
			self.assertEqual('default', load('invoice')[1])
			with self.assertRaises(KeyError):
				user_path('../../etc/passwd')
		finally:
			import shutil
			shutil.rmtree(os.path.dirname(USER_DIR), ignore_errors=True)
			USER_DIR = old

	def test_a_broken_custom_template_falls_back_to_the_shipped_one(self):
		import tempfile
		global USER_DIR
		old, USER_DIR = USER_DIR, os.path.join(tempfile.mkdtemp(prefix='printerface-test-'), 'templates')
		try:
			os.makedirs(USER_DIR)
			with open(user_path('invoice'), 'w') as f:
				f.write('${__import__("os")}')       # written to disk behind the editor's back
			body, kind, warning = render_for_job(self.job(), 'HAR108', ['Ann'])
			self.assertTrue(body.startswith('To Ann\n\nPlease find your latest invoice'))
			self.assertIn('could not be used', warning)
		finally:
			import shutil
			shutil.rmtree(os.path.dirname(USER_DIR), ignore_errors=True)
			USER_DIR = old

	def test_find_document(self):
		a, b = self.job(name='job-new'), self.job(name='job-old')
		b['parsed'] = {'ZZZ999': [{'doc_num': '500 100', 'accno': 'ZZZ999'}]}
		jobs = [self.job('delnote', 'job-d'), a, b]
		self.assertEqual(('job-new', 'HAR108'), (lambda r: (r[0]['name'], r[1]))(find_document(jobs, 'invoice')))
		self.assertEqual('job-new', find_document(jobs, 'invoice', '336770')[0]['name'])
		self.assertEqual('job-old', find_document(jobs, 'invoice', '500100')[0]['name'])
		self.assertEqual('job-old', find_document(jobs, 'invoice', 'zzz999')[0]['name'])
		self.assertIsNone(find_document(jobs, 'invoice', 'nope'))
		self.assertIsNone(find_document(jobs, 'statement'))

	def test_find_document_for_the_default_kind_matches_job_name_or_type(self):
		d1 = {'name': 'job-2', 'templ': 'delnote', 'doctype': 'Delvnote', 'groupfiles': {('accounts',): 'x.pdf'}}
		d2 = {'name': 'job-1', 'templ': None, 'doctype': 'Batch', 'groupfiles': {('plain',): 'y.pdf'}}
		jobs = [self.job('invoice', 'job-3'), d1, d2]
		self.assertEqual(('job-2', 'accounts'), (lambda r: (r[0]['name'], r[1]))(find_document(jobs, DEFAULT)))
		self.assertEqual(('job-1', 'plain'), (lambda r: (r[0]['name'], r[1]))(find_document(jobs, DEFAULT, 'batch')))
		self.assertEqual('job-1', find_document(jobs, DEFAULT, 'JOB-1')[0]['name'])
		self.assertIsNone(find_document(jobs, DEFAULT, 'nope'))

if __name__ == "__main__":
	unittest.main()
