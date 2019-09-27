FROM python:2.7-alpine as builder
MAINTAINER chris@shucksmith.co.uk

# add the dev dependencies
RUN apk add --no-cache python make gcc g++ libc-dev

# use cached layer for node modules
COPY requirements.txt /app/

WORKDIR /app/
RUN pip install -r requirements.txt
# RUN python -m unittest

RUN echo $HOME
VOLUME ["/root/printerface"]
EXPOSE 8081 1515
ENTRYPOINT [ "/usr/local/bin/python" ]
CMD [ "/app/main.py" ]

COPY . /app/

WORKDIR /app
RUN python -m unittest discover --pattern=*.py
# RUN ls -la /app/
