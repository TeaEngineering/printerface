FROM python:2.7-alpine as builder
MAINTAINER chris@shucksmith.co.uk

# add the dev dependencies
RUN apk add --no-cache python make gcc g++ libc-dev

# use cached layer for node modules
COPY requirements.txt /app/

WORKDIR /app/
RUN pip install -r requirements.txt
# RUN python -m unittest
RUN python -m unittest discover --pattern=*.py

RUN echo $HOME
VOLUME ["/root/printerface"]

COPY . /app/

EXPOSE 8081
EXPOSE 1515

WORKDIR /app
RUN ls -la /app/
ENTRYPOINT [ "/usr/local/bin/python" ]
CMD [ "/app/main.py" ]
