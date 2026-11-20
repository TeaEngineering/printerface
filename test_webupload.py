# The document layer for the website upload: what a job becomes on the wire. The corpus test runs only when
# WEBUPLOAD_CORPUS points at a directory laid out like ~/printerface (data/pickle/YYYYMM/job-*); it checks every
# stored invoice, credit note and statement.
import datetime
import glob
import io
import os
import unittest
from decimal import Decimal

import webupload
from webupload import UploadError


def page(doc_num='100', lines=(), totals=('120.00', '24.00', '144.00'), date='02/11/26', accno='ACC1', summ=('1', '120.00', '20.00', '24.00')):
	col = lambda key: '\n'.join(l[key] for l in lines) + '\n' * 3
	p = dict(accno=accno, doc_num=doc_num, date=date, custref='PO9', ourref='555', salesperson='SAM',
		addr_invoice='A WINE BAR\n1 HIGH ST\nTOWN\n\n', tot_net=totals[0], tot_vat=totals[1], tot_due=totals[2],
		summ_code='%s\n\n' % summ[0], summ_netamt='%s\n\n' % summ[1], summ_rate='%s\n\n' % summ[2], summ_vat='%s\n\n' % summ[3])
	for key in webupload.LINE_FIELDS:
		p[key] = col(key)
	return p


def line(code='', desc='', qty='', price='', unit='', net='', vat=''):
	return dict(prod_code=code, prod_desc=desc, prod_qty=qty, prod_price=price, prod_unit=unit, prod_net=net, prod_vcode=vat)


def job(templ, parsed, name='job-20261102-090507'):
	return dict(name=name, templ=templ, ts=datetime.datetime(2026, 11, 2, 9, 5, 7), parsed=parsed)


class TestHelpers(unittest.TestCase):
	def test_amount(self):
		self.assertEqual('1234.50', webupload.amount(' 1,234.50 '))
		self.assertEqual('-12.00', webupload.amount('12.00CR'))
		self.assertEqual('-12.00', webupload.amount('-12.00'))
		self.assertIsNone(webupload.amount('  '))
		self.assertRaises(UploadError, webupload.amount, '12.0.0')

	def test_dates(self):
		self.assertEqual('2026-11-02', webupload.iso_date('02/11/26'))
		self.assertRaises(UploadError, webupload.iso_date, '2026-11-02')
		self.assertEqual('2026-11-02T09:05:07Z', webupload.received(dict(ts=datetime.datetime(2026, 11, 2, 9, 5, 7))))
		bst = datetime.timezone(datetime.timedelta(hours=1))
		self.assertEqual('2026-07-02T08:05:07Z', webupload.received(dict(ts=datetime.datetime(2026, 7, 2, 9, 5, 7, tzinfo=bst))))


class TestInvoices(unittest.TestCase):
	LINES = [line('BOR00101', 'Bordeaux 2015', '12', '10.00', 'BOTT', '120.00', '1')]

	def test_invoice(self):
		(doc,) = webupload.documents(job('invoice', {'ACC1': [page(lines=self.LINES)]}))
		p = doc.payload
		self.assertEqual(('invoice', 'ACC1', '100', [0]), (doc.kind, doc.account, doc.docnum, doc.pages))
		self.assertEqual(('2026-11-02', False, 'PO9', '555', '120.00', '24.00', '144.00'),
			(p['date'], p['is_credit_note'], p['cust_ref'], p['our_ref'], p['total_net'], p['total_vat'], p['total_gross']))
		self.assertEqual(dict(acc='ACC1', name='A WINE BAR, 1 HIGH ST, TOWN', salesperson='SAM'), p['account'])
		self.assertEqual([dict(product_code='BOR00101', description='Bordeaux 2015', quantity='12', unit='BOTT', unit_price='10.00',
			net='120.00', vat_code='1', vat_rate='20.00')], p['lines'])
		self.assertEqual([dict(vat_code='1', net='120.00', rate='20.00', vat='24.00')], p['vat_summary'])
		self.assertEqual(('job-20261102-090507', '2026-11-02T09:05:07Z'), (p['job_name'], p['printed_at']))

	def test_text_rows_are_not_lines_and_credit_notes_keep_their_references(self):
		lines = [line('B0321001', 'BAUCHET Rose', '3', '21.53', 'BOTT', '64.59', '5'), line(desc='RE: KIR105 REF: 1452')]
		(doc,) = webupload.documents(job('crednote', {'ACC1': [page('21636', lines, ('64.59', '0.00', '64.59'))]}))
		self.assertTrue(doc.payload['is_credit_note'])
		self.assertEqual(1, len(doc.payload['lines']))
		self.assertEqual('RE: KIR105 REF: 1452', doc.payload['credit_refs'])
		(inv,) = webupload.documents(job('invoice', {'ACC1': [page(lines=lines)]}))
		self.assertEqual('', inv.payload['credit_refs'])

	def test_a_document_over_several_pages_takes_its_totals_from_the_last(self):
		first = page('7', [line('BOR00101', 'a', '1', '5.00', 'BOTT', '5.00', '1')], ('', '', ''))
		second = page('7', [line('BOR00102', 'b', '2', '5.00', 'BOTT', '10.00', '1')], ('15.00', '3.00', '18.00'))
		other = page('8', self.LINES)
		(a, b) = webupload.documents(job('invoice', {'ACC1': [first, second, other]}))
		self.assertEqual(([0, 1], '18.00', ['BOR00101', 'BOR00102']), (a.pages, a.payload['total_gross'], [l['product_code'] for l in a.payload['lines']]))
		self.assertEqual(([2], '7' != '8'), (b.pages, True))

	def test_missing_totals_are_an_error(self):
		self.assertRaises(UploadError, webupload.documents, job('invoice', {'ACC1': [page(totals=('', '', ''))]}))

	def test_other_types_are_not_uploaded(self):
		self.assertEqual([], webupload.documents(job('delnote', {'ACC1': [page()]})))


class TestStatements(unittest.TestCase):
	def stmt(self, **ages):
		p = dict(accno='ACC1', date='30/10/26', addr_invoice='A WINE BAR\n', age_curr='10.00', age_1m='5.00CR', age_2m='0.00', age_3m='', age_due='5.00')
		p.update(ages)
		return p

	def test_statement(self):
		(doc,) = webupload.documents(job('statement', {'ACC1': [self.stmt(age_3m='1.00')]}))
		p = doc.payload
		self.assertEqual('261102-090507-ACC1', p['docnum'])
		self.assertEqual(('10.00', '-5.00', '0.00', '1.00', '5.00'), (p['amt_current'], p['amt_1month'], p['amt_2month'], p['amt_3month'], p['amt_due']))

	def test_details_are_on_the_last_page(self):
		blank = self.stmt(age_curr='', age_1m='', age_2m='', age_3m='', age_due='')
		(doc,) = webupload.documents(job('statement', {'ACC1': [blank, self.stmt(age_3m='0.00')]}))
		self.assertEqual(([0, 1], '5.00'), (doc.pages, doc.payload['amt_due']))

	def test_incomplete_statement_is_an_error(self):
		self.assertRaises(UploadError, webupload.documents, job('statement', {'ACC1': [self.stmt(age_due='')]}))


class TestSplitPdf(unittest.TestCase):
	def test_split(self):
		from pypdf import PdfReader
		from reportlab.pdfgen import canvas
		buf = io.BytesIO()
		c = canvas.Canvas(buf)
		for n in range(3):
			c.drawString(100, 100, 'page %d' % n)
			c.showPage()
		c.save()
		out = PdfReader(io.BytesIO(webupload.split_pdf(buf.getvalue(), [2, 0])))
		self.assertEqual(['page 2', 'page 0'], [p.extract_text().strip() for p in out.pages])
		self.assertRaises(UploadError, webupload.split_pdf, buf.getvalue(), [3])


@unittest.skipUnless(os.environ.get('WEBUPLOAD_CORPUS'), 'set WEBUPLOAD_CORPUS to a directory like ~/printerface')
class TestCorpus(unittest.TestCase):
	def test_every_document_adds_up(self):
		import main
		from docparser import DocParser
		from textutil import load_job_pickle
		seen, rejected = 0, []
		for f in sorted(glob.glob(os.path.join(os.environ['WEBUPLOAD_CORPUS'], 'data/pickle/*/job-*'))):
			with open(f, 'rb') as fh:
				j = load_job_pickle(fh)
			doctype = (j.get('control') or {}).get('J', '').strip()
			if main.identify(dict(doctype=doctype)) not in ('invoice', 'crednote', 'statement'):
				continue
			j['doctype'], j['plain'] = doctype, main.control_char_re.sub(' ', j['data'])
			j['templ'] = main.identify(j)
			j['parsed'] = DocParser().parse(j)[1] or {}
			try:
				docs = webupload.documents(j)
			except UploadError as e:
				rejected.append('%s: %s' % (j['name'], e))      # the empty test documents sent while developing
				continue
			for doc in docs:
				seen += 1
				p = doc.payload
				if doc.kind == 'invoice':
					net = sum(Decimal(l['net']) for l in p['lines'])
					self.assertEqual(Decimal(p['total_net']), net, '%s %s' % (j['name'], doc.docnum))
					self.assertEqual(Decimal(p['total_gross']), Decimal(p['total_net']) + Decimal(p['total_vat']), '%s %s' % (j['name'], doc.docnum))
					self.assertEqual(Decimal(p['total_vat']), sum(Decimal(v['vat']) for v in p['vat_summary']), '%s %s' % (j['name'], doc.docnum))
		self.assertTrue(seen)
		self.assertTrue(all('ACC001' in r or '12345' in r for r in rejected), rejected)


if __name__ == '__main__':
	unittest.main()
