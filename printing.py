#!/usr/bin/python
import sys
import subprocess

printers = []

def getPrinters():
	global printers
	if not sys.platform == "linux2":
		return ['default']
	if len(printers) > 0: return printers
	try:
		process = subprocess.Popen(["lpstat", "-a"], stdout=subprocess.PIPE)
		result = process.communicate()[0].strip()
		# KONICA_bizhub_192.168.12.10 accepting requests since Sun 16 Dec 2012 07:43:59 PM GMT
		print(result)
		printers = [x.split(' ')[0] for x in result.split('\n')]
		print('[print] printers=%s' % repr(printers))
	except OSError as e:
		print('[print] %s' % repr(e))
	return printers

def printFile(file, printer):
	cmd = ["lpr","-P", printer, file]
	print("[print] printer=%s file=%s cmd=%s" %(printer, file, repr(cmd) ))
	process = subprocess.Popen(cmd, stdout=subprocess.PIPE)
	results = process.communicate()
	results = (None,None)
	print("[print] printer=%s file=%s cmd=%s result=%s" %(printer, file, repr(cmd), repr(results)))

if __name__=="__main__":
	print ('Installed printers: %s' % repr(getPrinters()))

