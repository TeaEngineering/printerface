#!/usr/bin/env python3.11
"""Characterisation check of the python 3 code against output produced by the python 2 release.

    tools/compare_corpus.py CORPUS OUTDIR [--since YYYYMMDD]

CORPUS is a directory laid out like ~/printerface (data/pickle/YYYYMM/job-*, data/pdf/...), copied from a
system running the python 2 release. Every job is loaded and run through main.cleanJob, which parses it and
renders PDFs into OUTDIR (never into ~/printerface). Each rendered PDF is then compared, as text extracted
by pdftotext, against the PDF python 2 made for the same job in CORPUS.
"""
import argparse
import collections
import contextlib
import io
import os
import subprocess
import sys
import traceback

ap = argparse.ArgumentParser()
ap.add_argument('corpus')
ap.add_argument('outdir')
ap.add_argument('--since', default='')
ap.add_argument('--show', type=int, default=5, help='how many differences to print per category')
args = ap.parse_args()

corpus = os.path.abspath(args.corpus)
os.environ['PRINTERFACE_HOME'] = os.path.abspath(args.outdir)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main
from textutil import load_job_pickle

def pdftext(path):
	out = subprocess.run(['pdftotext', '-layout', path, '-'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout
	return [l.rstrip() for l in out.decode('utf-8', 'replace').split('\n')]

pickle_root = os.path.join(corpus, 'data', 'pickle')
errors, noref, same, differ = [], [], [], []
by_templ = collections.Counter()
by_doctype = collections.Counter()
non_ascii_plain = 0
jobs = 0

for yyyymm in sorted(os.listdir(pickle_root)):
	for name in sorted(os.listdir(os.path.join(pickle_root, yyyymm))):
		if not name.startswith('job-') or name[4:] < args.since:
			continue
		jobs += 1
		try:
			with open(os.path.join(pickle_root, yyyymm, name), 'rb') as f:
				j = load_job_pickle(f)
			j['name'] = name
			with contextlib.redirect_stdout(io.StringIO()):
				main.cleanJob(j)
		except Exception:
			errors.append((name, traceback.format_exc().strip().split('\n')[-1]))
			continue
		by_templ[j['templ']] += 1
		by_doctype[j['doctype']] += 1
		if not j['plain'].isascii():
			non_ascii_plain += 1
		for key, rel in sorted(j['groupfiles'].items()):
			ref = os.path.join(corpus, 'data', 'pdf', rel)
			new = os.path.join(main.pdfdir, rel)
			if not os.path.exists(ref):
				noref.append((name, rel))
				continue
			a, b = pdftext(ref), pdftext(new)
			if a == b:
				same.append((name, rel))
			else:
				n = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
				differ.append((name, rel, n, a[n:n + 1], b[n:n + 1], len(a), len(b)))

print('jobs=%d load/parse errors=%d non-ascii plain text=%d' % (jobs, len(errors), non_ascii_plain))
print('by templ   :', dict(by_templ))
print('by doctype :', dict(by_doctype))
print('pdfs: identical text=%d  different=%d  no reference pdf=%d' % (len(same), len(differ), len(noref)))
for e in errors[:args.show]:
	print('ERROR', e)
for d in differ[:args.show]:
	print('DIFF %s %s line %d\n   py2: %r\n   py3: %r  (lines %d vs %d)' % d)
for n in noref[:args.show]:
	print('NOREF', n)
sys.exit(1 if errors or differ else 0)
