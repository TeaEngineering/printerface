printerface
===========

LPD document to PDF/email gateway. Setup a text-only line printer and point it at the lpd server port. Documents are stored, searchable and rendered to PDF. Results can be browsed over HTTP, emailed and printed.

* `lpdserver.py` implements a UNIX LPD daemon for recieving print jobs
* `httpserver.py` simple http server using asynchat
* `mailer.py` asynchronous mail queue to Gmail
* `docparser` recognise and parse some plain-text formats from 1990 to JSON
* `stationary.py` format JSON to nice PDF files
* `printing.py` Linux printing with CUPS via. command line

Requirements

    $ wget --no-check-certificate https://pypi.python.org/packages/source/s/setuptools/setuptools-1.4.2.tar.gz
    $ tar -xvf setuptools-1.4.2.tar.gz
    $ cd setuptools-1.4.2
    $ python2.7 setup.py install

    $ easy_install mako
    $ easy_install reportlab==2.7

Unit tests

    $ python -m unittest discover --pattern=*.py

Uses python asyncore/smtp, bootstrap web framework


### Docker & deploy

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

