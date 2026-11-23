#
# Pushes invoices, credit notes and statements to the website as they are printed. A queue worked by the event
# loop, like the mailer, with the blocking HTTP call in a worker thread. Each document is a multipart POST: a
# JSON `payload` part (see webupload.py) and its own `pdf`. The website replaces a document it already has, so
# sending one twice is harmless, and a failed one can simply be sent again.
#
# The outcome of the last `result_count` uploads is kept (newest first) in upload.pickle, flushed from the main loop.

import asyncio
import datetime
import json
import os
import traceback
import urllib.error
import urllib.request
import uuid

import printing
import webupload
from settings import config, HOME

pickle_file = os.path.join(HOME, 'upload.pickle')

# a network failure or a 5xx is tried again after each of these delays (seconds); anything else is final
RETRY_DELAYS = (5, 30)
TIMEOUT = 30


class UploadLog(printing.PrintLog):
	"""What was uploaded, newest first, one record per document: the job and key it came from, what the website
	did with it and any error. Kept in a side pickle, like the printed history, and capped at [Web] result_count,
	which is set independently of the email and print histories."""

	def __init__(self, path=None, limit=None):
		super().__init__(path, limit if limit is not None else config.getint('Web', 'result_count'))


def settings():
	"""(base_url, api_key); both blank when the feature is off."""
	return (config.get('Web', 'base_url', fallback='').strip(), config.get('Web', 'api_key', fallback='').strip())


def enabled():
	return all(settings())


def prepare(job, key, pdfdir):
	"""The uploads for a job page's key (an account, or 'accounts' for all of them), ready to queue. The PDF is cut
	into one per document. Raises webupload.UploadError for a job that can't be converted."""
	items = []
	for doc in webupload.documents(job):
		if key != 'accounts' and doc.account != key:
			continue
		with open(os.path.join(pdfdir, job['groupfiles'][(doc.account,)]), 'rb') as f:
			pdf = webupload.split_pdf(f.read(), doc.pages)
		items.append(dict(job=job['name'], key=doc.account, kind=doc.kind, account=doc.account, docnum=doc.docnum,
			payload=webupload.payload_json(doc), pdf=pdf))
	return items


def multipart(fields, files):
	"""(content type, body) for a multipart/form-data post. fields: {name: text}; files: {name: (filename, bytes)}."""
	boundary = uuid.uuid4().hex
	out = []
	for name, value in fields.items():
		out.append(('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n' % (boundary, name)).encode() + value.encode('utf-8') + b'\r\n')
	for name, (filename, data) in files.items():
		out.append(('--%s\r\nContent-Disposition: form-data; name="%s"; filename="%s"\r\nContent-Type: application/pdf\r\n\r\n'
			% (boundary, name, filename)).encode() + data + b'\r\n')
	out.append(('--%s--\r\n' % boundary).encode())
	return 'multipart/form-data; boundary=' + boundary, b''.join(out)


def post(item, base_url, api_key):
	"""Blocking: POST one document. Returns (status, reply text), also for an error status. Raises OSError (which
	URLError is) when the website could not be reached."""
	kind = 'statement' if item['kind'] == 'statement' else 'invoice'
	ctype, body = multipart({'payload': item['payload']}, {'pdf': ('%s-%s.pdf' % (item['kind'], item['docnum']), item['pdf'])})
	req = urllib.request.Request(base_url.rstrip('/') + '/api/ingest/%s/' % kind, data=body, method='POST',
		headers={'Content-Type': ctype, 'Authorization': 'Token ' + api_key, 'Accept': 'application/json'})
	try:
		with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
			return r.status, r.read().decode('utf-8', 'replace')
	except urllib.error.HTTPError as e:
		return e.code, e.read().decode('utf-8', 'replace')


def describe(status, text):
	"""A short message for a refusal: the website's own field errors if it sent them."""
	try:
		text = json.dumps(json.loads(text))
	except ValueError:
		text = ''           # an HTML error page is no use in a table cell
	return ('HTTP %d %s' % (status, text)).strip()[:300]


class WebUploader(object):
	"""Uploads queued documents one at a time, in order. Like JobMailer, `append` is called from page handlers and
	`start` / `close` from main.serve, all on the event loop."""

	def __init__(self, queuesz=200, log=None, transport=None):
		self.queue = asyncio.Queue(queuesz)
		self.log = log if log is not None else UploadLog(pickle_file)
		self.transport = transport or post         # replaced in tests
		self.task = None

	def start(self):
		self.task = asyncio.get_running_loop().create_task(self.run())

	async def close(self, timeout=30):
		if self.task:
			try:
				await asyncio.wait_for(self.queue.join(), timeout)
			except asyncio.TimeoutError:
				print('upload: %d documents still queued at shutdown' % self.queue.qsize())
			self.task.cancel()
			self.task = None

	def append(self, item):
		"""Queue one document. Raises asyncio.QueueFull if too many are waiting."""
		self.queue.put_nowait(item)

	def attempt(self, item):
		"""One try (blocking: runs in a worker thread): (outcome, status, message, retry)."""
		base_url, api_key = settings()
		try:
			status, text = self.transport(item, base_url, api_key)
		except OSError as e:
			return 'failed', None, 'could not reach the website: %s' % (e.reason if hasattr(e, 'reason') else e), True
		if status in (200, 201):
			return ('created' if status == 201 else 'replaced'), status, None, False
		return 'failed', status, describe(status, text), status >= 500

	async def run(self):
		while True:
			item = await self.queue.get()
			try:
				for delay in (0,) + RETRY_DELAYS:
					if delay:
						await asyncio.sleep(delay)
					outcome, status, message, retry = await asyncio.to_thread(self.attempt, item)
					if not retry:
						break
				print('upload: %s %s -> %s %s' % (item['kind'], item['docnum'], outcome, message or ''))
				self.log.add(dict(job=item['job'], key=item['key'], kind=item['kind'], account=item['account'], docnum=item['docnum'],
					added=datetime.datetime.now(), outcome=outcome, status=status, error=message if outcome == 'failed' else None))
			except asyncio.CancelledError:
				raise
			except Exception:
				traceback.print_exc()
			finally:
				self.queue.task_done()
