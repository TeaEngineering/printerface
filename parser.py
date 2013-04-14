#!/usr/bin/python

import sys, os
from StringIO import StringIO

dir = os.path.expanduser("~/printerface/")
jobdir = dir + 'pickle/'

def field(col, r, c, w=10, h=1, t='??'):
	col.append(dict(r=r,c=c,w=w,h=h,t=t,line=r))

class DocParser(object):
	def parse(self, job):
		if job['templ']:
			mname = 'extract' + job['templ'].title()
			lines = job['plain'].splitlines()
			dims = (len(lines), max([len(line) for line in lines]))
			if hasattr(self, mname):
				return getattr(self, mname)(lines, dims)
			print('Warning: No parsing function %s' % mname)
		return (None,None)

	def extractCrednote(self, lines, dims):
		return self.extractInvoice(lines, dims)

	def extractInvoice(self, lines, (rows,cols)):
	        all_fields = []
		page_data = []

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
			field(fs, line+8, 12,w=38,h=5,t='caddr')
			field(fs, line+8, 66,w=38,h=5,t='daddr')
			field(fs, line+15,80,t='instruction',w=25)
			field(fs, line+16,0,w=8,t='account')
			field(fs, line+16,9,w=8,t='subaccount')
			field(fs, line+16,20,w=7,t='inv_num')
			field(fs, line+16,28,w=8,t='state_date')
			field(fs, line+16,39,w=14,t='salesp')
			
			field(fs, line+19,0,w=9,t='prod_code',h=18)
			field(fs, line+19,19,w=27,t='prod_desc',h=18)
			field(fs, line+19,55,w=6, t='prod_qty',h=18)
			field(fs, line+19,65,w=8,t='prod_each',h=18)
			field(fs, line+19,75,w=4,t='prod_unit',h=18)
			field(fs, line+19,90,w=11,t='prod_cost',h=18)
			field(fs, line+19,103,w=2,t='prod_del',h=18)

			field(fs, line+38,0,w=4,t='summ_code',h=4)
			field(fs, line+38,5,w=9,t='summ_netamt',h=4)
			field(fs, line+38,16,w=6,t='summ_rate',h=4)
			field(fs, line+38,26,w=6,t='summ_vat',h=4)

			field(fs, line+37, 89,w=12,t='tot_net')
			field(fs, line+39, 89,w=12,t='tot_vat')
			field(fs, line+42, 89,w=12,t='tot_due')

			field(fs, line+38, 36,w=40,t='summ_box',h=3)

			all_fields += fs
			page_data.append( self.populate(lines, fs) )

		return (all_fields, page_data)

	def populate(self, lines, fs):
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
		
		for (row,line) in enumerate(lines):
			for col,char in enumerate(line):
				if high[row][col]:
					node = high[row][col]
					if not node['line'] == row: 
						node['text'] += '\n'
						node['line'] = row
					node['text'] += char
		data = {}
		for c in fs:
			data[c['t']] = c['text'].strip()

		return data

if __name__=="__main__":
	x = DocParser()

