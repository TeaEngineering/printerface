#!/usr/bin/python

import sys
import os
import itertools
import collections
from StringIO import StringIO

jobdir = os.path.expanduser("~/printerface/pickle/")

import colorsys
N=20
HSV_tuples = [(x*1.0/N, 0.5, 0.8) for x in range(N)]
colours = itertools.cycle(map(lambda x: colorsys.hsv_to_rgb(*x), HSV_tuples))

def field(col, r, c, w=10, h=1, t='??'):
	col.append(dict(r=r,c=c,w=w,h=h,t=t,line=r,rgb=colours.next()))

class DocParser(object):
	def parse(self, job):
		if job['templ']:
			mname = 'extract' + job['templ'].title()
			lines = job['plain'].splitlines()
			dims = (len(lines), max([len(line) for line in lines]))
			if hasattr(self, mname):
				fields, page_data = getattr(self, mname)(job, lines, dims)
				data = page_data

				return (fields, data)
			print('Warning: No parsing function %s' % mname)
		return (None,None)

	def extractCrednote(self, job, lines, dims):
		return self.extractInvoice(job, lines, dims)

	def extractInvoice(self, job, lines, (rows,cols)):
		all_fields = []
		page_data = collections.OrderedDict()

		pages = (rows-48)/48
		for page in range(pages):
			line =(page+1) * 48
			fs = []
			field(fs, line+0, 0,w=20,t='doctype')
			field(fs, line+0, 95,w=10,t='date')
			field(fs, line+2, 95,w=10,t='page')
			field(fs, line+4, 95,w=10,t='doc_num')
			field(fs, line+4, 10,w=16,t='vat_supp')
			field(fs, line+5, 10,w=16,t='vat_cust')
			field(fs, line+8, 12,w=38,h=6,t='addr_invoice')
			field(fs, line+8, 66,w=38,h=6,t='addr_delivery')
			field(fs, line+15,75,t='instructions',w=30,h=2)
			field(fs, line+16,0,w=8,t='accno')
			field(fs, line+16,9,w=10,t='custref')
			field(fs, line+16,20,w=7,t='ourref')
			field(fs, line+16,28,w=8,t='ord_date')
			field(fs, line+16,66,w=8,t='req_date')
			field(fs, line+16,39,w=26,t='salesperson')
			
			field(fs, line+19,0,w=15,t='prod_code',h=18)
			field(fs, line+19,19,w=30,t='prod_desc',h=18)
			field(fs, line+19,55,w=6, t='prod_qty',h=18)
			field(fs, line+19,64,w=9,t='prod_price',h=18)
			field(fs, line+19,75,w=5,t='prod_unit',h=18)
			field(fs, line+19,81,w=6,t='prod_blank',h=18)
			field(fs, line+19,90,w=11,t='prod_net',h=18)
			field(fs, line+19,103,w=2,t='prod_vcode',h=18)

			field(fs, line+38,0, w=4,t='summ_code',h=4)
			field(fs, line+38,5, w=9,t='summ_netamt',h=4)
			field(fs, line+38,14,w=6,t='summ_rate',h=4)
			field(fs, line+38,25,w=7,t='summ_vat',h=4)

			field(fs, line+37, 89,w=12,t='tot_net')
			field(fs, line+39, 89,w=12,t='tot_vat')
			field(fs, line+42, 89,w=12,t='tot_due')

			field(fs, line+38, 36,w=40,t='summ_box',h=3)

			all_fields += fs
			extracted = self.populate(lines, fs)
			page_data.setdefault(extracted['accno'], []).append(extracted)

		return (all_fields, page_data)

	def extractDelnote(self, job, lines, (rows,cols)):
		all_fields = []
		page_data = collections.OrderedDict()

		pages = (rows-48)/48
		for page in range(pages):
			line =(page+1) * 48
			fs = []
			field(fs, line+0, 0,w=20,t='doctype')
			field(fs, line+0, 95,w=10,t='date')
			field(fs, line+2, 95,w=10,t='page')
			field(fs, line+4, 95,w=10,h=2,t='doc_num')
			field(fs, line+8, 12,w=38,h=6,t='addr_invoice')
			field(fs, line+8, 66,w=38,h=6,t='addr_delivery')
			field(fs, line+15,75,t='instructions',w=30,h=2)
			field(fs, line+16,0,w=8,t='accno')
			field(fs, line+16,9,w=10,t='custref')
			field(fs, line+16,20,w=7,t='ourref')
			field(fs, line+16,28,w=8,t='ord_date')
			field(fs, line+16,66,w=8,t='req_date')
			field(fs, line+16,40,w=26,t='salesperson')
			
			field(fs, line+19,0,w=15,t='prod_code',h=18)
			field(fs, line+19,18,w=30,t='prod_desc',h=18)
			field(fs, line+19,53,w=6, t='prod_qty',h=18)
			field(fs, line+19,64,w=9,t='prod_price',h=18)
			field(fs, line+19,75,w=5,t='prod_unit',h=18)
			field(fs, line+19,83,w=5,t='prod_blank',h=18)
			field(fs, line+19,90,w=11,t='prod_net',h=18)
			field(fs, line+19,103,w=2,t='prod_vcode',h=18)

			field(fs, line+38, 35,w=44,t='summ_box',h=3)

			all_fields += fs
			extracted = self.populate(lines, fs)
			page_data.setdefault(extracted['accno'], []).append(extracted)

		return (all_fields, page_data)

	def extractStatement(self, job, lines, (rows,cols)):
		# any lines after line containing 'PRINT STATEMENT SUMMARY' should be ignored
		rows = min([rows] + [lnum for (lnum,text) in enumerate(lines) if 'PRINT STATEMENT SUMMARY' in text])
		all_fields = []
		page_data = collections.OrderedDict()

		pages = (rows-51)/51
		for page in range(pages):
			line =(page+1) * 51
			fs = []
			field(fs, line+12,58,w=10,t='date')
			field(fs, line+12,92,w=10,t='date_recv')
			field(fs, line+1, 82,w=10,t='page')
			field(fs, line+8, 12,w=38,h=6,t='addr_invoice')
			field(fs, line+10,58,w=10,t='accno')
			
			field(fs, line+19,1 ,w=9, t='prod_date',h=22)
			field(fs, line+19,12,w=24,t='prod_code',h=22)
			field(fs, line+19,37,w=4, t='prod_trans',h=22)
			field(fs, line+19,43,w=12,t='prod_debt',h=22)
			field(fs, line+19,57,w=12,t='prod_credit',h=22)
			field(fs, line+19,71,w=12,t='prod_bal',h=22)
			field(fs, line+19,85,w=8, t='prod_date',h=22)
			field(fs, line+19,95,w=9,t='prod_ref',h=22)
			field(fs, line+19,104,w=12,t='prod_total',h=22)
			field(fs, line+19,116,w=2, t='prod_tick',h=22)

			field(fs, line+41, 44,w=12,t='tot_debt')
			field(fs, line+41, 57,w=12,t='tot_credit')
			field(fs, line+41, 71,w=12,t='tot_bal')
			field(fs, line+41, 104,w=13,t='tot_topay')

			field(fs, line+42, 16,w=40,t='summ_box',h=3)

			field(fs, line+47,8,w=14,t='age_curr')
			field(fs, line+47,22,w=14,t='age_1m')
			field(fs, line+47,36,w=14,t='age_2m')
			field(fs, line+47,50,w=14,t='age_3m')
			field(fs, line+47,69,w=14,t='age_due')

			all_fields += fs

			extracted = self.populate(lines, fs)
			page_data.setdefault(extracted['accno'], []).append(extracted)
			
		return (all_fields, page_data)

	def extractPurchase(self, job, lines, (rows,cols)):
		all_fields = []
		page_data = collections.OrderedDict()

		pages = (rows-48)/48
		for page in range(pages):
			line =(page+1) * 48 
			fs = []
			field(fs, line+2, 0,w=20,t='doctype')
			field(fs, line+2, 95,w=10,t='date')
			field(fs, line+4, 95,w=10,t='page')
			field(fs, line+6, 95,w=14,h=1,t='doc_num')
			field(fs, line+9, 14,w=38,h=6,t='addr_invoice')
			field(fs, line+2, 53,w=38,h=5,t='addr_office')
			field(fs, line+9, 67,w=38,h=6,t='addr_delivery')
			field(fs, line+15,75,t='instructions',w=30,h=2)
			field(fs, line+17,0,w=8,t='accno')
			field(fs, line+17,9,w=10,t='custref')
			field(fs, line+17,20,w=20,t='ourref')
			field(fs, line+17,44,w=18,t='ourcontact')
			field(fs, line+17,65,w=8,t='orderdate')

			field(fs, line+20,0 ,w=14, t='prod_code',h=20)
			field(fs, line+20,21,w=30,t='prod_desc',h=20)
			field(fs, line+20,52,w=6, t='prod_qty',h=20)
			field(fs, line+20,65,w=11,t='prod_price',h=20)
			field(fs, line+20,74,w=8,t='prod_unit',h=20)
			
			field(fs, line+43,84,w=12,t='tot_net')
			all_fields += fs
			extracted = self.populate(lines, fs)
			page_data.setdefault(extracted['accno'], []).append(extracted)

		return (all_fields, page_data)

	def extractRemittance(self, job, lines, (rows,cols)):
		all_fields = []
		page_data = collections.OrderedDict()

		pages = (rows-48)/48
		for page in range(pages):
			line =(page+1) * 48 
			fs = []
			field(fs, line+0, 8,w=38,h=5,t='addr_firm')
			field(fs, line+0, 68,w=10,t='date')
			field(fs, line+2, 68,w=10,t='page')
			field(fs, line+4, 68,w=14,t='doc_num')
			field(fs, line+6, 8,w=38,h=5,t='addr_invoice')

			field(fs, line+17,0,w=20,h=20,t='rem_desc')
			field(fs, line+17,21,w=10,h=20,t='rem_ourref')
			field(fs, line+17,32,w=13,h=20,t='rem_yourref')
			field(fs, line+17,46,w=10,h=20,t='rem_net')
			field(fs, line+17,58,w=8,h=20,t='rem_vat')
			field(fs, line+17,70,w=9,h=20,t='rem_gross')
			
			field(fs, line+40,8,w=40,t='instructions',h=2)
			field(fs, line+38,60,w=19,t='amt_discount')
			field(fs, line+40,60,w=19,t='amt_encl')
			all_fields += fs
			
			extracted = self.populate(lines, fs)
			page_data.setdefault(extracted['doc_num'], []).append(extracted)

		return (all_fields, page_data)

	def extractPicklist(self, job, lines, (rows,cols)):
		all_fields = []
		page_data = collections.defaultdict(list)

		# variable length per page, split into pages by pagebreak
		line = 0
		for part in filter(None, job['plain'].split("\f")):
			if len(part.strip()) > 0:
				h = len(part.splitlines())
				fs = []
				field(fs, line,0,w=cols,t='data',h=h)
				all_fields += fs
				line = line + h
				extracted = self.populate(lines, fs, stripText=False)
				page_data['all'].append(extracted)

		return (all_fields, page_data)

	def populate(self, lines, fs, stripText=True):
		(rows, cols) = (len(lines), max([len(line) for line in lines]))

		# if any fields extend beyond the document, extends the number of columns
		cols = max(cols, max([c['c']+c['w'] for c in fs]))
		rows = max(rows, max([c['r']+c['h'] for c in fs]))

		high = [[None for col in range(cols)] for row in range(rows)]
		
		for c in fs:
			c['text'] = ''
			for row in range(c['r'], c['r']+c['h']):
				for col in range(c['c'], c['c']+c['w']):
					high[row][col] = c
		
		for row,line in enumerate(lines):
			for col,char in enumerate(line + (' '*(cols-len(line)))):
				if high[row][col]:
					node = high[row][col]
					if not node['line'] == row: 
						node['text'] += '\n'
						node['line'] = row
					node['text'] += char
		data = {}
		for c in fs:
			if stripText:
				data[c['t']] = '\n'.join( [ s.strip() for s in c['text'].split('\n')] )
			else:
				data[c['t']] = c['text']

		return data

if __name__=="__main__":
	x = DocParser()

