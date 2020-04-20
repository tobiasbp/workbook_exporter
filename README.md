

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

## Usage
Build the image as 'workbook_exporter' (From the repo dir):
`docker build -t workbook_exporter .`

Run a container (In the background), passing credentials as environment variables:
`docker run --detach --name wbe -e "WORKBOOK_URL=https://your.url/api"
 -e "WORKBOOK_USER=user" -e "WORKBOOK_PASSWORD=secret" workbook_exporter`

Confirm the container is running:
`docker container ls`

Take a look at the log file in the container, to make sure things work as expected:
docker exec wbe cat /var/log/workbook_exporter.log


## Security
Anyone can scrape your data, so you should not allow incomming traffic by exposing
the port, unless you are on a trusted network.

Use another container in the same network to scrape the data,
or run a a proxy server with authentication in front of the
workbook_exporter, to control the access to the data.

If you want to be able to allow incomming traffic to the container from
any source (Not recomended) you can `publish` the port 9701 to allow incomming
traffic by adding `--publish 9701:9701` to the run command. You can make the container
listen on another port, and forward to the local port 9701. To listen on port 8080,
you would use the command `--publish 8080:9701`.


# To do
Stuff to do. Should this not be in issues in GitHub?

* Status of active jobs in buckets
