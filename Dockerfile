FROM python:3-alpine

EXPOSE 9701

# The config file
ADD workbook_exporter.yml /etc/

# The actual exporter
ADD workbook_exporter.py /usr/local/bin/

RUN pip install workbook-api prometheus-client PyYAML

ENTRYPOINT [ "python", "/usr/local/bin/workbook_exporter.py" ]
