# workbook_exporter
A Prometheus exporter of metrics from Deltek Workbook

No of active jobs for a customer
workbook_customer_active_jobs{
  customer_id="220",
  name="Example Inc.",
  payment_term_id="24",
  responsible_employee_id="21",
  type_id="1"
  } 5.0

No of days since job was created
workbook_job_age_days{
  billable="0",
  company_id="1",
  created="2011-10-18T15:39:27.493Z",
  customer_id="5",
  customer_name="Example Inc.",
  days_to_end_date="286",
  department_id="1",
  department_name="Example department",
  job_id="1000003",
  name="Example job",
  retainer="0",
  status_id="1",
  type_id="15"
  } 3074.0

Days an employee has been employed
workbook_employee_days_employed{
  company_id="1",
  department_id="2",
  employee_id="100",
  employment_type_id="1",
  position_id="2",
  sex_id="1",
  type_id="1"
  } 688.0

Did we get data from Workbook without errors (0.0|1.0)?
workbook_up 1.0
