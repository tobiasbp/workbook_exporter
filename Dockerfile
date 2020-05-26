FROM python:3-alpine

EXPOSE 9701

# The config file
COPY workbook_exporter.yml /etc/

# The actual exporter
COPY workbook_exporter.py /usr/local/bin/

COPY requirements.txt .
RUN pip install --requirement requirements.txt

ENTRYPOINT [ "python", "/usr/local/bin/workbook_exporter.py", "--disable-log-file" ]
