#!/usr/bin/env python3.11
"""Rewrite an email.cfg written for the old sections to the current ones, keeping its comments and order:

    [Printing]  company details and logos   ->  [Stationery]
    [Robot]     auto_types, auto_printer    ->  [Printing]   (with the printed history's result_count)

    tools/migrate_config.py [PATH] [--dry-run]

PATH defaults to ~/printerface/email.cfg (or $PRINTERFACE_HOME/email.cfg). The original is kept beside it as
email.cfg.before-sections, unless that exists already. A file already in the new layout is left alone. Printerface
reads the old layout too, with a notice in its log, so this is tidying, not a requirement.
"""
import argparse
import configparser
import os
import re
import shutil
import sys

HEADER = re.compile(r'^\[([^\]]+)\]\s*$')
KEY = re.compile(r'^([^\s#;=:\[][^=:]*?)\s*[=:]')


def company_keys():
	base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
	c = configparser.RawConfigParser()
	c.read(os.path.join(base, 'defaults.cfg'))
	return set(c.options('Stationery'))


def blocks(text):
	"""[(section or None, [entry, ...])]. An entry is the comment and blank lines before a key, the key's line and its
	continuation lines, as one list of lines; lines after the last key of a section are an entry with no key."""
	out = [(None, [[]])]
	for line in text.splitlines():
		m = HEADER.match(line)
		if m:
			out.append((m.group(1), [[]]))
			continue
		entries = out[-1][1]
		if KEY.match(line):
			entries[-1].append(line)
			entries.append([])
		elif line[:1] in (' ', '\t') and line.strip() and len(entries) > 1 and entries[-1] == []:
			entries[-2].append(line)         # a continuation of the previous value
		else:
			entries[-1].append(line)
	return out


def key_of(entry):
	for line in entry:
		m = KEY.match(line)
		if m:
			return m.group(1).strip()
	return None


def migrate(text, keys=None):
	keys = company_keys() if keys is None else keys
	parts = blocks(text)
	names = [name for name, _ in parts]
	old_printing = [e for name, es in parts if name == 'Printing' for e in es]
	if 'Robot' not in names and not any(key_of(e) in keys for e in old_printing):
		return text
	stationery = [e for e in old_printing if key_of(e) in keys]
	printing = [e for name, es in parts if name == 'Robot' for e in es if key_of(e) is not None]
	printing += [e for e in old_printing if key_of(e) not in keys and key_of(e) is not None]
	trailer = {}
	out = []
	placed_printing = False

	def section(name, entries):
		lines = ['[%s]' % name]
		for e in entries:
			if key_of(e) is not None:
				lines.extend(e)
		return lines

	for name, entries in parts:
		if name is None:
			preamble = [l for e in entries for l in e]
			out.extend(preamble)
			continue
		if out and out[-1].strip():
			out.append('')
		if name == 'Printing':
			if stationery:
				out.extend(section('Stationery', stationery))
			if 'Robot' not in names and printing:
				out.append('')
				out.extend(section('Printing', printing))
				placed_printing = True
		elif name == 'Robot':
			out.extend(section('Printing', printing))
			placed_printing = True
		else:
			out.append('[%s]' % name)
			for e in entries:
				out.extend(e)
	if printing and not placed_printing:
		out.append('')
		out.extend(section('Printing', printing))
	while out and not out[-1].strip():
		out.pop()
	return '\n'.join(out) + '\n'


def main():
	ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	ap.add_argument('path', nargs='?', default=os.path.join(os.path.expanduser(os.environ.get('PRINTERFACE_HOME', '~/printerface')), 'email.cfg'))
	ap.add_argument('--dry-run', action='store_true', help='show the sections it would write, change nothing')
	args = ap.parse_args()
	with open(args.path) as f:
		old = f.read()
	new = migrate(old)
	if new == old:
		print('%s is already in the current layout' % args.path)
		return
	check = configparser.RawConfigParser()
	check.read_string(new)
	print('%s: sections now %s' % (args.path, check.sections()))
	if args.dry_run:
		return
	backup = args.path + '.before-sections'
	if not os.path.exists(backup):
		shutil.copy2(args.path, backup)
	mode = os.stat(args.path).st_mode & 0o777
	tmp = args.path + '.tmp'
	with open(tmp, 'w') as f:
		f.write(new)
	os.chmod(tmp, mode)
	os.replace(tmp, args.path)
	print('rewritten; the original is %s' % backup)


if __name__ == '__main__':
	main()
