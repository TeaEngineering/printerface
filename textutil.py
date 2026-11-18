# Helpers that pin down text semantics which differ between python 2 str and python 3 str.
import re
import pickle
import unittest

# Pickles written during the cutover use protocol 2 so that the previous python 2.7 release can still
# read anything written by python 3 if we have to roll back. Remove once rollback is no longer needed.
PICKLE_PROTOCOL = 2

# Python 2 str.splitlines() split on \n, \r and \r\n only. Python 3 str.splitlines() also splits on
# \f \v \x1c-\x1e \x85    . The parsers address fixed rows and rely on \f surviving inside
# a line (it marks page breaks), so we must keep the python 2 behaviour.
_eol_re = re.compile(r'\r\n|\r|\n')

def split_lines(s):
	lines = _eol_re.split(s)
	if lines and lines[-1] == '':
		lines.pop()
	return lines

def load_job_pickle(f):
	"""Load a print job pickle. Python 2 'str' values were raw 8-bit bytes (the LPD payload); latin-1
	maps each byte to one character, matching lpdserver.ENCODING. Also loads datetimes."""
	return pickle.load(f, encoding='latin-1')

def _text(b):
	try:
		return b.decode('utf-8')
	except UnicodeDecodeError:
		return b.decode('latin-1')

def decode_bytes(obj):
	"""Recursively turn the bytes python 2 'str' objects load as into text. Values entered through the web
	forms (contact names, email subjects) were utf-8 encoded. Text already written by python 3 is untouched.
	Containers are updated in place so that defaultdict and friends keep their type."""
	if isinstance(obj, bytes):
		return _text(obj)
	if isinstance(obj, dict):
		items = [(decode_bytes(k), decode_bytes(v)) for k, v in obj.items()]
		obj.clear()
		obj.update(items)
	elif isinstance(obj, list):
		obj[:] = [decode_bytes(x) for x in obj]
	elif isinstance(obj, tuple):
		return type(obj)(decode_bytes(x) for x in obj) if type(obj) is tuple else obj
	elif isinstance(obj, (set, frozenset)):
		return type(obj)(decode_bytes(x) for x in obj)
	return obj

def load_user_pickles(f, count=1):
	"""Load `count` consecutive pickles holding user entered data (email.pickle, mailer.pickle)"""
	u = pickle.Unpickler(f, encoding='bytes')
	return [decode_bytes(u.load()) for _ in range(count)]

class TestTextUtil(unittest.TestCase):
	def test_split_lines(self):
		self.assertEqual(['a', 'b'], split_lines('a\nb'))
		self.assertEqual(['a', 'b'], split_lines('a\r\nb\n'))
		self.assertEqual(['a', '', 'b'], split_lines('a\n\nb'))
		self.assertEqual([], split_lines(''))
		self.assertEqual(['a\x0cb'], split_lines('a\x0cb'))
		self.assertEqual(['a\x0bb\x85c\x1cd'], split_lines('a\x0bb\x85c\x1cd'))

	# what python 2.7 pickle.dump(..., protocol 0) wrote for {'ts': datetime, 'data': 'caf\xe9 \x0c'}
	PY2_JOB = b"(dp0\nS'ts'\np1\ncdatetime\ndatetime\np2\n(S'\\x07\\xde\\x03\\x04\\x14\\x35\\x00\\x00\\x00\\x00'\ntp3\nRp4\nsS'data'\np5\nS'caf\\xe9 \\x0c'\np6\ns."

	def test_load_job_pickle_py2(self):
		import io, datetime
		d = load_job_pickle(io.BytesIO(self.PY2_JOB))
		self.assertEqual(datetime.datetime(2014, 3, 4, 20, 53), d['ts'])
		self.assertEqual('caf\xe9 \x0c', d['data'])

	def test_user_pickles_py2_utf8(self):
		import io, collections
		# {'ACC': {'a@b.c': 'Jos\xc3\xa9'}} as python 2 str (utf-8 bytes from a web form), then a py3 style text value
		raw = b"(dp0\nS'ACC'\np1\n(dp2\nS'a@b.c'\np3\nS'Jos\\xc3\\xa9'\np4\nss."
		[d] = load_user_pickles(io.BytesIO(raw))
		self.assertEqual({'ACC': {'a@b.c': 'Jos\xe9'}}, d)
		dd = collections.defaultdict(dict, ACC={b'x': b'\xff\xfe', 'y': 'caf\xe9'})
		out = decode_bytes(dd)
		self.assertIsInstance(out, collections.defaultdict)
		self.assertEqual({'x': '\xff\xfe', 'y': 'caf\xe9'}, out['ACC'])

	def test_pickle_roundtrip_protocol2(self):
		import io, datetime
		d = {'ts': datetime.datetime(2014, 3, 4, 20, 53), 'data': 'caf\xe9'}
		buf = io.BytesIO(); pickle.dump(d, buf, protocol=PICKLE_PROTOCOL); buf.seek(0)
		self.assertEqual(d, load_job_pickle(buf))

if __name__ == "__main__":
	unittest.main()
