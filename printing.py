#!/usr/bin/env python3
import subprocess
import printstatus

def getPrinters():
	"""Names of the CUPS queues, as the Printers page sees them (same lpstat call, so the two always agree).
	Empty if CUPS can't be asked, so the print menu is empty rather than offering a queue that doesn't exist."""
	try:
		return [p.name for p in printstatus.status().printers]
	except printstatus.LpstatError as e:
		print('[print] %s' % e)
		return []

def printFile(file, printer):
	cmd = ["lpr","-P", printer, file]
	print("[print] printer=%s file=%s cmd=%s" %(printer, file, repr(cmd) ))
	process = subprocess.Popen(cmd, stdout=subprocess.PIPE)
	results = process.communicate()
	results = (None,None)
	print("[print] printer=%s file=%s cmd=%s result=%s" %(printer, file, repr(cmd), repr(results)))

if __name__=="__main__":
	print ('Installed printers: %s' % repr(getPrinters()))

