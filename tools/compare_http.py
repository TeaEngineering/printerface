#!/usr/bin/env python3.11
"""Compare the read-only HTTP API of two printerface instances (for example the python 2 release and a
python 3 candidate) over the jobs they both hold. Only GET /recent, /job and /raw are used.

    tools/compare_http.py http://localhost:8081 http://localhost:18081 [--limit 100] [--delay 0.15]

The instances may hold different windows of jobs, so only jobs present in both are compared. Not compared:
the 'ts' field of /recent (it reports one job's timestamp for every row) and the order of keys inside JSON
objects (python 2 dicts had arbitrary order). Order of jobs, of accounts inside 'parsed' and the values of
every field are compared. Exit status is non-zero on any difference.
"""
import argparse
import json
import sys
import time
import urllib.request

ap = argparse.ArgumentParser()
ap.add_argument('ref')
ap.add_argument('cand')
ap.add_argument('--limit', type=int, default=100, help='max parsed documents to compare with /job')
ap.add_argument('--raw', type=int, default=5, help='max stock-report jobs to compare with /raw')
ap.add_argument('--delay', type=float, default=0.15, help='seconds between requests (the server is a single event loop)')
args = ap.parse_args()

def get(base, path):
	time.sleep(args.delay)
	with urllib.request.urlopen(base.rstrip('/') + path, timeout=120) as r:
		return r.read()

def recent_all(base):
	out, page = [], 0
	while True:
		d = json.loads(get(base, '/recent?query=&templ=&doctype=&page=%d&fmt=json' % page).decode('utf-8'))
		out += d['results']
		if not d['next']:
			return out
		page += 1

ref, cand = recent_all(args.ref), recent_all(args.cand)
R, C = {r['name']: r for r in ref}, {r['name']: r for r in cand}
common = [r['name'] for r in ref if r['name'] in C]
fails = 0
def fail(*a):
	global fails
	fails += 1
	print('DIFF', *a)

print('/recent: ref=%d cand=%d common=%d' % (len(ref), len(cand), len(common)))
for n in common:
	for k in ('host', 'doctype', 'details'):
		if R[n][k] != C[n][k]:
			fail('/recent', n, k, R[n][k], C[n][k])
if common != [r['name'] for r in cand if r['name'] in R]:
	fail('/recent order of common jobs differs')

parsed = [n for n in common if R[n]['details']][:args.limit]
for n in parsed:
	a = json.loads(get(args.ref, '/job?name=' + n).decode('utf-8'))
	b = json.loads(get(args.cand, '/job?name=' + n).decode('utf-8'))
	if a != b:
		fail('/job', n, [k for k in a if a[k] != b.get(k)])
print('/job: compared %d parsed documents' % len(parsed))

stock = [n for n in common if R[n]['doctype'] in ('D.PR6', 'D.AEB28A', 'D.SIZE')][:args.raw]
for n in stock:
	if get(args.ref, '/raw?name=' + n) != get(args.cand, '/raw?name=' + n):
		fail('/raw', n)
print('/raw: compared %d stock report jobs' % len(stock))
print('FAILED: %d differences' % fails if fails else 'OK: no differences')
sys.exit(1 if fails else 0)
