# asyncore/asynchat (used by lpdserver.py and httpserver.py) were removed in python 3.12
FROM python:3.11-slim
MAINTAINER chris@shucksmith.co.uk

COPY requirements.txt /app/

WORKDIR /app/
RUN pip install --no-cache-dir -r requirements.txt

RUN echo $HOME
VOLUME ["/root/printerface"]
EXPOSE 8081 1515
ENTRYPOINT [ "/usr/local/bin/python" ]
CMD [ "/app/main.py" ]

COPY . /app/

WORKDIR /app
RUN python -m unittest discover --pattern=*.py
