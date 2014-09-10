printerface
===========

LPD document to PDF/email gateway

* `lpdserver.py` implements a UNIX LPD daemon for recieving print jobs
* `httpserver.py` simple http server using asynchat
* `mailer.py` asynchronous mail queue to Gmail
* `docparser` recognise and parse some plain-text formats from 1990 to JSON
* `stationary.py` format JSON to nice PDF files
* `printing.py` Linux printing with CUPS via. command line

Requires
$ wget --no-check-certificate https://pypi.python.org/packages/source/s/setuptools/setuptools-1.4.2.tar.gz
$ tar -xvf setuptools-1.4.2.tar.gz
$ cd setuptools-1.4.2
$ python2.7 setup.py install

$ easy_install mako
$ easy_install reportlab==2.7

