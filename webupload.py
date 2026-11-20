"""
Turns parsed Printerface documents into what the website's ingest endpoints take, with no network code so it
can be tested on its own. See the website's README ("Sales documents from Printerface").

Each function takes a job (as stored: `name`, `ts`, `parsed`) and returns a list of `Document`s, one per
invoice, credit note or statement. A document records which pages of its account's PDF it occupies, because
one PDF holds every document the account was sent in the print run, and a document may run to several pages
(the totals are then on its last page).
"""

import collections
import datetime
import io
import json
import re

Document = collections.namedtuple('Document', 'kind account docnum pages payload')

LINE_FIELDS = ('prod_code', 'prod_desc', 'prod_qty', 'prod_price', 'prod_unit', 'prod_net', 'prod_vcode')
VAT_FIELDS = ('summ_code', 'summ_netamt', 'summ_rate', 'summ_vat')


class UploadError(Exception):
	pass


def amount(text):
	"""'1,234.50' -> '1234.50'; a trailing CR (credit) makes it negative. Blank is None. Kept as text so no
	float rounding can creep in; the website parses it as a decimal."""
	text = (text or '').strip().replace(',', '')
	if not text:
		return None
	negative = text.endswith('CR')
	text = text[:-2].strip() if negative else text
	if not re.match(r'^-?\d+(\.\d+)?$', text):
		raise UploadError('not an amount: %r' % text)
	return '-' + text.lstrip('-') if negative and not text.startswith('-') else text


def iso_date(text):
	"""Printerface prints dd/mm/yy"""
	try:
		return datetime.datetime.strptime(text.strip(), '%d/%m/%y').date().isoformat()
	except ValueError:
		raise UploadError('not a date: %r' % text)


def received(job):
	"""When Printerface received the job, as UTC. job['ts'] is a naive utcnow() unless it was made aware."""
	ts = job['ts']
	if ts.tzinfo:
		ts = ts.astimezone(datetime.timezone.utc).replace(tzinfo=None)
	return ts.strftime('%Y-%m-%dT%H:%M:%SZ')


def columns(page, names):
	"""The rows of a page's columns, which are newline joined strings, as a list of dicts. Short columns are padded."""
	cols = [page.get(n, '').split('\n') for n in names]
	height = max(len(c) for c in cols)
	return [dict(zip(names, [(c[i] if i < len(c) else '').strip() for c in cols])) for i in range(height)]


def lines_of(pages):
	"""(lines, notes) for the pages of one document. A line has a product code, a quantity or an amount; a row with none of
	those is text (a reference printed under a credit note's lines) and goes in notes."""
	lines, notes = [], []
	for page in pages:
		for row in columns(page, LINE_FIELDS):
			if row['prod_code'] or row['prod_qty'] or row['prod_net'] or row['prod_price']:
				lines.append(dict(product_code=row['prod_code'], description=row['prod_desc'],
					quantity=amount(row['prod_qty']) or '0', unit=row['prod_unit'], unit_price=amount(row['prod_price']) or '0',
					net=amount(row['prod_net']) or '0', vat_code=row['prod_vcode']))
			elif row['prod_desc']:
				notes.append(row['prod_desc'])
	return lines, notes


def vat_summary(page):
	return [dict(vat_code=r['summ_code'], net=amount(r['summ_netamt']), rate=amount(r['summ_rate']), vat=amount(r['summ_vat']))
		for r in columns(page, VAT_FIELDS) if r['summ_code']]


def sales_documents(job):
	"""Invoices or credit notes, depending on the job's template."""
	credit = job.get('templ') == 'crednote'
	docs = []
	for account, pages in (job.get('parsed') or {}).items():
		by_number = collections.OrderedDict()
		for index, page in enumerate(pages):
			if not page.get('doc_num', '').strip():
				continue		# a blank page, not a document
			by_number.setdefault(page['doc_num'].strip(), []).append(index)
		for docnum, indexes in by_number.items():
			doc_pages = [pages[i] for i in indexes]
			last = doc_pages[-1]
			if not last.get('tot_due', '').strip():
				raise UploadError('%s %s has no totals on its last page' % (account, docnum))
			lines, notes = lines_of(doc_pages)
			vat = vat_summary(last)
			for line in lines:
				rate = [v['rate'] for v in vat if v['vat_code'] == line['vat_code']]
				line['vat_rate'] = rate[0] if rate else None
			if amount(last['tot_net']) is None:
				raise UploadError('%s %s has no net total' % (account, docnum))
			first = doc_pages[0]
			desc = [x for x in first['addr_invoice'].split('\n') if x.strip()]
			payload = dict(docnum=docnum, is_credit_note=credit, date=iso_date(first['date']),
				account=dict(acc=account, name=', '.join(x.strip() for x in desc[:3]), salesperson=first['salesperson'].strip()),
				cust_ref=first['custref'].strip(), our_ref=first['ourref'].strip(),
				total_net=amount(last['tot_net']), total_vat=amount(last['tot_vat']) or '0', total_gross=amount(last['tot_due']),
				vat_summary=vat, credit_refs='; '.join(notes)[:200] if credit else '',
				job_name=job['name'], printed_at=received(job), lines=lines)
			docs.append(Document('invoice', account, docnum, indexes, payload))
	return docs


def statements(job):
	"""One statement per account: its details are on the last page when it runs to several."""
	docs = []
	for account, pages in (job.get('parsed') or {}).items():
		last = pages[-1]
		desc = [x for x in last['addr_invoice'].split('\n') if x.strip()]
		payload = dict(docnum='%s-%s' % (job['name'][6:], account), date=iso_date(last['date']),
			account=dict(acc=account, name=', '.join(x.strip() for x in desc[:3]), salesperson=''),
			amt_current=amount(last['age_curr']), amt_1month=amount(last['age_1m']), amt_2month=amount(last['age_2m']),
			amt_3month=amount(last['age_3m']), amt_due=amount(last['age_due']), printed_at=received(job))
		missing = [k for k, v in payload.items() if v is None]
		if missing:
			raise UploadError('statement for %s has no %s' % (account, ', '.join(missing)))
		docs.append(Document('statement', account, payload['docnum'], list(range(len(pages))), payload))
	return docs


def documents(job):
	"""Everything uploadable in a job, or [] for a type that is not uploaded."""
	if job.get('templ') in ('invoice', 'crednote'):
		return sales_documents(job)
	if job.get('templ') == 'statement':
		return statements(job)
	return []


def split_pdf(pdf_bytes, pages):
	"""A PDF holding just the given (0 based) pages of pdf_bytes."""
	from pypdf import PdfReader, PdfWriter
	reader = PdfReader(io.BytesIO(pdf_bytes))
	if pages and max(pages) >= len(reader.pages):
		raise UploadError('page %d wanted but the PDF has %d' % (max(pages) + 1, len(reader.pages)))
	writer = PdfWriter()
	for i in pages:
		writer.add_page(reader.pages[i])
	out = io.BytesIO()
	writer.write(out)
	return out.getvalue()


def payload_json(document):
	return json.dumps(document.payload)
