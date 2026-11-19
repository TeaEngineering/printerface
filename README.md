# printerface
[![Tests](https://github.com/shuckc/printerface/actions/workflows/tests.yml/badge.svg)](https://github.com/shuckc/printerface/actions/workflows/tests.yml) [![License](https://img.shields.io/badge/License-BSD%203--Clause-blue.svg)](https://opensource.org/licenses/BSD-3-Clause)

Printerface is an application that acts as a virtual printer, accepting LPD (Line Printer Daemon) documents and parses/renders them to PDF files. Documents are stored, searchable to users on your LAN using the build in web interface. Results can be browsed, emailed and automatically printed to modern network printers (anything with a CUPS/ppd driver). It has been used in production for over eight years by customers with legacy stock control/management systems, alarm pannels and fire pannels. Tea Engineering Ltd. provides commercial support and custom/integration services in the UK.

The service is written in Python, with a Javascript web front end using bootstrap JS. It has a rich JSON API and can be used as a centralised interface to legacy system output, whereby documents can be parsed and then consumed by downstream services. We have production instances with over 100k documents a year, 5-6M pages.

Computer systems as old as Windows NT4 can print to LPD printers as standard, so integration even into the most challenging environments is relatively easy compared to modifying legacy systems. Printerface provides a great path forward for customers trapped with old fixed-width, fanfold or pre-printed stationary systems, or struggling to maintain old dot-matrix line printers.

Often we can de-duplicate or drop entirely sections of the documents that are no longer required in hard copies, to reduce the environmental footprint of legacy print jobs.

## Quickstart

The following will checkout the source code, build a docker image and start an instance of printerface on localhost. The web interface listens on http://localhost:8081 ands the LPR printing endpoint will be running on tcp port 515. These steps roughly work on mac, linux and windows.

    $ git clone git@github.com:shuckc/printerface.git
    $ cd printerface
    $ docker build -t printerface:latest .
    $ docker create --name p1 -p 8081:8081 -p 515:1515 printerface
    $ docker start p1


## Source code & implementation notes

* `lpdserver.py` implements a UNIX LPD daemon for recieving print jobs
* `httpserver.py` simple http server using asynchat
* `mailer.py` asynchronous mail queue to Gmail
* `docparser` recognise and parse some plain-text formats from 1990 to JSON
* `stationary.py` format JSON to nice PDF files
* `printing.py` Linux printing with CUPS via. command line

Requires **python 3.11** (3.9+ for the dependencies, but `asyncore`/`asynchat` were removed from the standard library in 3.12).
Requirements are specified in requirements.txt
Unit tests run during `docker build` or with:

    $ python3.11 -m unittest discover --pattern=*.py

Uses python asyncore/smtp, bootstrap web framework

Jobs, rendered PDFs, the email address book and `email.cfg` overrides live in `~/printerface`. Set the
`PRINTERFACE_HOME` environment variable to use a different directory, for example to run a second instance
against a copy of the data on other ports (`lpd_port` and `http_port` in `defaults.cfg`/`email.cfg`).

### Email templates

The text offered when emailing a document comes from a template per document type: `invoice`, `purchase` and
`statement` (other types use the single "Default Email Text" under Settings). Templates are Mako files.
`~/printerface/templates/<type>.mako` is used if it exists, otherwise the copy shipped in `templates/` in the
source, so an install that never customises a template follows the repository. Edit them under
Settings > Email Templates, which previews the result against a real document (leave the filter blank for the
newest, or enter a document number or account).

Variables: `${doc.<field>}` (the document: `doc.ourref`, `doc.doc_num`, `doc.accno`, `doc.tot_due`,
`doc.customer`, ... - the editor lists them), `${email.name}`, `${email.address}`, `${job.name}`,
`${company.name}`. If an account has several documents in one print run `doc` is the last; use
`% for d in docs:` ... `% endfor` to visit each. `% if doc.field:` / `% else:` / `% endif` and `##` comments work too.

The web interface has no authentication and Mako can run arbitrary python, so the editor only accepts that
subset (no calls, operators, `<% %>` blocks or names starting with an underscore; see `emailtemplates.validate`).
Files placed in `~/printerface/templates` by hand are trusted, but one that no longer renders falls back to the
shipped template with a warning.

`tools/compare_corpus.py` and `tools/replay_corpus.py` check a port or upgrade against real data: given a copy of
`data/pickle` and `data/pdf` from a running system, the first re-renders every job and compares the PDF text
with the PDFs the previous release produced, the second replays every stored payload through the LPD server.
`tools/compare_http.py` compares the read-only `/recent`, `/job` and `/raw` API of two running instances over the
jobs they both hold, for checking a candidate against the live release.

Jobs and the address book are stored as pickles. They are written with pickle protocol 2 (see
`PICKLE_PROTOCOL` in `textutil.py`) so that python 2.7 can still read them, and python 2 pickles from earlier
releases are converted when loaded. Print data is treated as latin-1 throughout, one byte per column.

### Detailed docker deploy

The Dockfile fully describes how to build a containerised printerface, including dependancies.

    $ git clone git@github.com:shuckc/printerface.git
    $ cd printerface
    $ docker build .

The built docker image does not appear on disk as a file, but is incorporated into docker's 'image repository'. To be able to use the docker image, you must tag it. For instance, build and tag like this:

    $ docker build -t printerface:latest .

If you wish to start a container locally, then you create a container, specifying the tagged image and provide the environment variables needed to start up successfully. You can do this as below:

    docker create --name p1 -p 8081:8081 -p 515:1515 printerface
    docker start p1

Note that the image is resolved permimently to a hash of some sort at this point. If you re-build and update the tag, you still need to throw away the container and recreate it.

     docker stop p1
     docker rm p1

On windows you may wish to mount the job storage directory externally, as follows:

    docker create --rm --name p1 -p 8081:8081 -p 515:1515 -v c:/Users/cshucks/printerface:/root/printerface printerface


### From-scratch userland python install

    $ mkdir ~/opt
    $ wget https://www.python.org/ftp/python/3.11.10/Python-3.11.10.tgz
    $ tar -xzf Python-3.11.10.tgz
    $ cd Python-3.11.10
    $ ./configure prefix=$HOME/opt --with-ensurepip=install
    $ make && make install
    $ ~/opt/bin/python3.11 -m pip install -r ~/repos/printerface/requirements.txt

On older distributions pip has no prebuilt wheels for `pillow`, so you also need a compiler and the
`libjpeg` and `zlib` development headers installed to build it.
