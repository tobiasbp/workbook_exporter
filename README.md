

# workbook_exporter
A Prometheus exporter of metrics from Deltek Workbook

Metrics are exported on port 9701 by default.
They are available at http://example.com:9701/metrics.

In my experience. Workbook is very slow. Scrapes can exceed 60 seconds.
Especially, if you have more than one company.


## Install
Install dependencies with pip
pip install prometheus_client workbook_api

## Metrics

> # HELP workbook_employees_profit_percent Estimated profit in percent
> # TYPE workbook_employees_profit_percent histogram
> workbook_employees_profit_percent_bucket{company_id="",le=""}
> workbook_employees_profit_percent_count{company_id=""}
> workbook_employees_profit_percent_sum{company_id=""}

> # HELP workbook_employees_hours_sale Estimated sales price for 1 hours work
> # TYPE workbook_employees_hours_sale histogram
> workbook_employees_hours_sale_bucket{company_id="",le=""}
> workbook_employees_hours_sale_count{company_id=""}
> workbook_employees_hours_sale_sum{company_id=""}

> # HELP workbook_employees_hours_cost Estimated cost of 1 hours work
> # TYPE workbook_employees_hours_cost histogram
> workbook_employees_hours_cost_bucket{company_id="",le=""}
> workbook_employees_hours_cost_count{company_id=""}
> workbook_employees_hours_cost_sum{company_id=""} 0.0


> # HELP workbook_employees_days_employed Days since employment
> # TYPE workbook_employees_days_employed histogram
> workbook_employees_days_employed_bucket{company_id="",le=""}
> workbook_employees_days_employed_count{company_id=""}
> workbook_employees_days_employed_sum{company_id=""}


> # HELP workbook_jobs_days_old Days since job was created
> # TYPE workbook_jobs_days_old histogram
> workbook_jobs_days_old_bucket{billable="",company_id="",le=""}
> workbook_jobs_days_old_count{billable="",company_id=""}
> workbook_jobs_days_old_sum{billable="",company_id=""}

> # HELP workbook_billable_jobs Number of billable jobs
> # TYPE workbook_billable_jobs gauge
> workbook_billable_jobs{company_id=""}

> # HELP workbook_jobs_total Number of jobs
> # TYPE workbook_jobs_total gauge
> workbook_jobs_total{company_id=""}


# Grafana dashboards
JSON files with dashboards to graph the Prometheus metrics can be found in 
the dir `grafana`.

## Projects
A dashboard with stats for projects (Jobs in Workbook terminology) is in
the file `dashboard_workbook_projects.json`. Use the import feature in Grafana
to start using it.

After import in Grafana, change variables `company_id` and `wb_job` to match the
labels `company_id` and `job` in your Prometheus metrics. When saving the
dashboard after setting the variables, make sure that you enable the
option "save current variables".

## Finance
A dashboard with financial data is in
the file `dashboard_workbook_finace.json`. Use the import feature in Grafana
to start using it.

After import in Grafana, change variables `company_id` and `wb_job` to match the
labels `company_id` and `job` in your Prometheus metrics. When saving the
dashboard after setting the variables, make sure that you enable the
option "save current variables".

The dashboards has the following variables which can be changed by the user
* "Finance accounts": The accounts to show graphs for (Multi choice)
* "Days to use when calculating change"
* "Number of days to base prediction on"
* "Number of days in the future to predict for"

The dashboard includes the following graphs
* Account balance
* Account prediction
* Account balance change
* Debit & Credit
* Debitors & Creditors
* Employment length
* Departments: Sum of hourly costs
* Departments: Average hourly cost

# Docker
Run the workbook_exporter in a docker container

## Basic usage

Run workbook_exporter in a container passing credentials as environment variables:
`docker run --detach --name wbe -p 9701:9701 -e "WORKBOOK_URL=https://your.url/api"
 -e "WORKBOOK_USER=user" -e "WORKBOOK_PASSWORD=secret" tobiasbp/workbook_exporter`

Anyone can scrape your data, so you should not allow incomming traffic by exposing
the port, unless you are on a trusted network.

## With authentication and HTTPS
Use the `docker-compose` with the file `docker-compose.yml` to set up the workbook exporter
behind an nginx reverse proxy with authentication and Let's Encrypt certificates.
You can edit the file, if you do not want to configure the setup using environment
variables, as I have done in the following.

Make sure you have the apache2-utils/httpd-tools, so you can create a
password file for nginx to use.

Set environment variables:
* export WORKBOOK_URL="https://me.workbook.dk/api"
* export WORKBOOK_USER="my_user"
* export WORKBOOK_PASSWORD="secret"
* export LETSENCRYPT_MAIL="me@example.com"
* export WORKBOOK_VIRTUAL_HOST="wbe.example.com"

Make sure $WORKBOOK_VIRTUAL_HOST resolves to the IP running your exporter. Otherwise,
the certificates can not be issued.

Create a directory to hold the password file for Nginx to use:
* `mkdir ~/htpasswd`

Create password file for user `scrape_user`. This is the user Prometheus should use when scraping:
* `htpasswd -c ~/htpasswd/$WORKBOOK_VIRTUAL_HOST scrape_user`

You should now have a password file with the name of your virtual host in `~/htpasswd`.

Start the containers:
`docker-compose up --detach [docker-compose.yml]`

Let's make sure everything is doing what we expect:


You should be asked for credentials (Status code 401) when connecting on ports 9701 & 443:
* `curl https://wbe.everland.dk:9701`
* `curl https://wbe.everland.dk`

Port 80 should be forwarded (Status code 301):
* `curl http://wbe.everland.dk`

You should get the Workbook metrics when logging in with your credentials:
`curl --user scrape_user https://wbe.everland.dk/metrics`


# Kubernetes

Create a new namespace
`kubectl create namespace workbook-exporter`

Create a secret with the Workbook credentials
`kubectl create secret --namespace workbook-exporter generic wbe-secret
 --from-literal=workbook_url='https://example.workbook.dk/api'
 --from-literal=workbook_user='my_user'
 --from-literal=workbook_password='my_password'`

Edit wbe-configmap.yml and apply if you want non-default config
`kubectl apply -f wbe-configmap.yml`

Add workbook-exporter as a service to your cluster
`kubectl apply -f wbe-service.yml`


# To do
Stuff to do. Should this not be in issues in GitHub?

* Status of active jobs in buckets
