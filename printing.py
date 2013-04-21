#!/usr/bin/python
import sys
import subprocess

printers = []

def getPrinters():
	if not sys.platform == "linux":
		return ['default']
	
	process = subprocess.Popen(["lpstat", "-a"], stdout=subprocess.PIPE)
	result = process.communicate()[0]
	# KONICA_bizhub_192.168.12.10 accepting requests since Sun 16 Dec 2012 07:43:59 PM GMT
	printers = [x.split(' ')[0] for x in result.lines()]
	print('[print] printers=%s' % repr(printers))
	return printers

def printFile(file, printer):
	cmd = ["lpr","-P", printer, file]
	#process = subprocess.Popen(cmd, stdout=subprocess.PIPE)
	#results = process.communicate()
	results = (None,None)
	print("[print] printer=%s file=%d cmd=%s result=%s" %(printer, file, repr(cmd), repr(results)))

if __name__=="__main__":
	print ('Installed printers: %s' % repr(getPrinters()))

