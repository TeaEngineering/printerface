# printerface
[![Build Status](https://travis-ci.org/shuckc/printerface.svg?branch=master)](https://travis-ci.org/shuckc/printerface) [![License](https://img.shields.io/badge/License-BSD%203--Clause-blue.svg)](https://opensource.org/licenses/BSD-3-Clause)

Printerface is a self-hosted service to accept LPD (Line Printer Daemon) documents, and parse/render them to PDF files. Documents are stored, searchable to users on your LAN. Results can be browsed over HTTP, emailed and automatically printed to modern network printers (anything with a CUPS/ppd driver). It has been used in production for over eight years by customers with legacy stock control/management systems, alarm pannels and fire pannels. Tea Engineering Ltd. provides commercial support and custom/integration services in the UK.

The service is written in Python, with a Javascript web front end using bootstrap JS. It has a rich API and can be used as a centralised interface to legacy system output, whereby documents can be parsed to JSON and then consumed by downstream services. We have production instances with over 100k documents a year, 5-6M pages.

Computer systems as old as Windows NT4 can print to LPD printers built-in, so integration even into the most challenging environments is relatively easy compared to modifying legacy systems. Printerface provides a great path forward for customers trapped with old fixed-width, fanfold or pre-printed stationary systems, or struggling to maintain old dot-matrix line printers.

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

Requirements are specified in requirements.txt
Unit tests run during `docker build` or with:

    $ python -m unittest discover --pattern=*.py

Uses python asyncore/smtp, bootstrap web framework

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
    $ wget https://www.python.org/ftp/python/2.7.18/Python-2.7.18.tgz
    $ tar -xzf Python-2.7.18.tgz
    $ cd Python-2.7.18
    $ ./configure prefix=$HOME/opt --with-ensurepip=install
    $ make && make install
    $ ~/opt/bin/pip install -r ~/repos/printerface/requirements.txt

