# workbook_exporter
A Prometheus exporter of metrics from Deltek Workbook

# HELP workbook_employees_profit_percent Estimated profit in percent
# TYPE workbook_employees_profit_percent histogram
workbook_employees_profit_percent_bucket{company_id="",le=""}
workbook_employees_profit_percent_count{company_id=""}
workbook_employees_profit_percent_sum{company_id=""}

# HELP workbook_employees_hours_sale Estimated sales price for 1 hours work
# TYPE workbook_employees_hours_sale histogram
workbook_employees_hours_sale_bucket{company_id="",le=""}
workbook_employees_hours_sale_count{company_id=""}
workbook_employees_hours_sale_sum{company_id=""}

# HELP workbook_employees_hours_cost Estimated cost of 1 hours work
# TYPE workbook_employees_hours_cost histogram
workbook_employees_hours_cost_bucket{company_id="",le=""}
workbook_employees_hours_cost_count{company_id=""}
workbook_employees_hours_cost_sum{company_id=""} 0.0


# HELP workbook_employees_days_employed Days since employment
# TYPE workbook_employees_days_employed histogram
workbook_employees_days_employed_bucket{company_id="",le=""}
workbook_employees_days_employed_count{company_id=""}
workbook_employees_days_employed_sum{company_id=""}


# HELP workbook_jobs_days_old Days since job was created
# TYPE workbook_jobs_days_old histogram
workbook_jobs_days_old_bucket{billable="",company_id="",le=""}
workbook_jobs_days_old_count{billable="",company_id=""}
workbook_jobs_days_old_sum{billable="",company_id=""}

# HELP workbook_billable_jobs Number of billable jobs
# TYPE workbook_billable_jobs gauge
workbook_billable_jobs{company_id=""}

# HELP workbook_jobs_total Number of jobs
# TYPE workbook_jobs_total gauge
workbook_jobs_total{company_id=""}

# To do

* Status of active jobs in buckets
