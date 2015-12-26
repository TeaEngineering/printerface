#!/usr/bin/env python2.7
from __future__ import with_statement

from datetime import datetime
from docparser import DocParser
from printing import getPrinters, printFile

import sys
import pickle
import os
import re
from StringIO import StringIO
import collections
import traceback

data_dir = os.path.expanduser("~/printerface/data/")
jobdir = os.path.join(data_dir, 'pickle')
jobs = []

mainparser = DocParser()
loadQty = 500000

def recover(invf, invl):
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
				print(' recovering %s %s' % (p, s['name']))
				cleanJob(s, invf, invl)
			if len(jobs) > loadQty: break
		if len(jobs) > loadQty: break

control_char_re = re.compile('[^\w\s%s_\'=/]' % re.escape('.*+()-\\;:,#?%$^&!<>|`"'))

def cleanJob(j, invf, invl):
	
	j['plain'] = control_char_re.sub(' ', j['data'])
	j['doctype'] = j.get('control', {}).get('J').strip()
	j['templ'] = identify(j)

	# j['autofmt'] = formatter.getBestPageFormat(j['plain'])

	(j['colouring'],j['parsed']) = mainparser.parse(j)
	if not j['colouring']: del j['colouring']

	if j['templ'] == 'pr1':
		handlePr1(j)

	if j['templ'] == 'invoice':
		handleInv(j, invf, invl)
	return

def handlePr1(j, dest=os.path.expanduser('/tmp/pr1')):
	# variable length per page, split into pages by pagebreak
	if os.path.isfile(dest): return

	line = 0
	groups = {}
	suppliers = collections.defaultdict(int)
	szs = collections.defaultdict(int)
	with open(dest, 'w') as f:
		for part in filter(None, j['plain'].split("\f")):
			if len(part.strip()) > 0:
				for l in part.splitlines():
					if len(l.strip()) == 0: continue
					if 'STOCK MANAGEMENT' in l: continue
					if '=' * 46 in l: continue
					if '-' * 120 in l: continue
					if 'ALL PRICES ARE PER B' in l: continue
					if 'Prd Line   Wi' in l: continue
					if 'Grp Ref    Co' in l: continue
					if '====================' in l: continue
					if l[0:52] == ' '*52:
						section = l.strip()
					else:
						# data rows
						groups[int(l[0:3])] = section
						sup = l[54:65].strip()
						suppliers[sup] += 1
						sz  = l[48:52]
						szs[sz] += 1
						print l
						# l can spill over 130 characters if last column is negative (1)
						if len(l) > 129: l = l[0:129]
						f.write(l)
						f.write('\n')
	print groups
	print suppliers
	print szs
	with open(os.path.expanduser('/tmp/groups'), 'w') as f:
		for k,v in groups.iteritems():
			f.write("%3d %-40s\n" % (k, v))
	with open(os.path.expanduser('/tmp/sizes'), 'w') as f:
		for k,v in szs.iteritems():
			f.write("%s\n" % k)
	with open(os.path.expanduser('/tmp/suppliers'), 'w') as f:
		for k,v in suppliers.iteritems():
			f.write("%s\n" % k)

def handleInv(j, invf, invl):
	# print j['parsed']
	# dict( cust -> [ ord_date: __, custref: '', prod_desc: \n\n\n, prod_price: \n\n\n, prod_unit: \n\n\n, doc_num: .. 
	#   accno:  , ourref:... salesperson:  doc_num  prod_code:  prod_qty:  prod_net:   tot_net tot_due:   ] )
	# layout - summary
	#    doc_num   ourref  accno custref  salesperson ord_date tot_net tot_due
	# layout - lines
	#    doc_num   prod_code prod_desc  prod_qty  prod_price  prod_unit  prod_net
	for acc,pages in j['parsed'].iteritems():
		for page in pages:
			if len(page['tot_due'].strip()) > 0:
				invf.write("%6s %6s %7s %-12s %-20s %8s %10s %10s\n" % (page['doc_num'], page['ourref'], page['accno'], page['custref'], 
					page['salesperson'], page['ord_date'], page['tot_net'], page['tot_due']))

			xs = [ page[x].split('\n') for x in ['prod_code', 'prod_desc', 'prod_qty', 'prod_price', 'prod_unit', 'prod_net'] ]
			for x in zip(*xs):
				if len(x[0].strip()) > 0:
					invl.write('%6s %6s %7s %10s %30s %6s %8s %6s %9s\n' % (page['doc_num'], page['ourref'], page['accno'],
						x[0], x[1], x[2], x[3], x[4], x[5] ))

def identify(j):
	types = {
			'Sttments': 'statement',
			'Delvnote':'delnote',
			'Cr-note':'crednote',
			'Invoice':'invoice',
			'P order':'purchase',
			'Rem Advs':'remittance',
			'Pick lst': 'picklist',
			'D.PR6': 'pr1'
			}
	return types.get(j['doctype'])

if __name__=="__main__":
	
	try:
		os.remove(os.path.expanduser('/tmp/pr1'))
	except:
		None
	
	with open(os.path.expanduser('/tmp/inv'), 'w') as f:
		with open(os.path.expanduser('/tmp/invline'), 'w') as l:
			recover(f, l)
	print 'done'
