#!/usr/bin/env python3

import argparse
from datetime import datetime
import os
import random
import time

from prometheus_client import start_http_server, Summary
from prometheus_client.core import GaugeMetricFamily, REGISTRY
import workbook_api

# The string to use when converting times in Workbook
# Example: 2020-08-17T09:02:23.677Z
TIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"

# Jobs with status id in this list, are reported
ACTIVE_JOBS = [0,1]

# Create a metric to track time spent and requests made.
REQUEST_TIME = Summary('request_processing_seconds', 'Time spent processing request')


# Decorate function with metric.
@REQUEST_TIME.time()
def process_request(t):
    """A dummy function that takes some time."""
    time.sleep(t)


def parse_date(wb_time):
    '''
    Convert a Workbook time string to a datetime object
    '''
    return datetime.strptime(wb_time, TIME_FORMAT)
    

class WorkbookCollector(object):

  def __init__(self, wb_url, wb_user, wb_pass):
      # Workbook API object
      self.wb = workbook_api.WorkbookAPI(wb_url, wb_user, wb_pass)

  def collect(self):

    # A dictionary mapping id to ISO name
    currencies = {c['Id']:c['Iso4127'] for c in self.wb.get_currencies()}

    # A dictionary mapping id to company name
    companies = {c['Id']:c['Name'] for c in self.wb.get_companies(active=True)}

    # Assume no problems with getting data from Workbook
    wb_error = False

    # CREDIT #

    credit_due = GaugeMetricFamily(
        'workbook_credit_due',
        'Credit due',
        labels=['company_id', 'currency']
        )

    credit_total = GaugeMetricFamily(
        'workbook_credit_total',
        'Total credit',
        labels=['company_id', 'currency']
        )

    try:
        creditors = self.wb.get_creditors()
    except Exception as e:
        print("Error: {}".format(e))
        wb_error = True
    else:
        # Create a dictionary with companies.
        # Each company has dictionarys for each currency, with
        # amount due and total
        # company_id:CUR:due+total
        credit = {company_id:{c:{'due':0.0, 'total':0.0} for c in currencies.values()} for company_id in companies.keys()}

        for c in creditors:
            # Only get data from creditors with amounts
            if c.get('RemainingAmountTotal'):
                # Get data
                currency = currencies[c['CurrencyId']]
                total = c.get('RemainingAmountTotal',0.0)
                due = c.get('RemainingAmountDue',0.0)
                
                # Update the dictionary
                credit[c['CompanyId']][currency]['due'] += due
                credit[c['CompanyId']][currency]['total'] += total

        # Run through the dictionary and add data to the metric
        for company_id, data in credit.items():
            for cur, data in data.items():
                credit_due.add_metric([str(company_id), cur], data['due'])
                credit_total.add_metric([str(company_id), cur], data['total'])
        
        yield credit_due
        yield credit_total

    # DEBIT #

    debit_due = GaugeMetricFamily(
        'workbook_debit_due',
        'Debit due',
        labels=['company_id', 'currency']
        )

    debit_total = GaugeMetricFamily(
        'workbook_debit_total',
        'Total debit',
        labels=['company_id', 'currency']
        )

    try:
        debtors = self.wb.get_debtors_balance()
    except Exception as e:
        print("Error: {}".format(e))
        wb_error = True
    else:
        # Create a dictionary with companies.
        # Each company has dictionarys for each currency, with
        # amount due and total
        # company_id:CUR:due+total
        debit = {company_id:{c:{'due':0.0, 'total':0.0} for c in currencies.values()} for company_id in companies.keys()}

        for d in debtors:
            # Only get data from creditors with amounts
            if d.get('RemainingAmountTotal'):
                # Get data
                currency = currencies[d['CurrencyId']]
                total = d.get('RemainingAmountTotal',0.0)
                due = d.get('RemainingAmountDue',0.0)
                
                # Update the dictionary
                debit[d['CompanyId']][currency]['due'] += due
                debit[d['CompanyId']][currency]['total'] += total

        # Run through the dictionary and add data to the metric
        for company_id, data in debit.items():
            for cur, data in data.items():
                debit_due.add_metric([str(company_id), cur], data['due'])
                debit_total.add_metric([str(company_id), cur], data['total'])
        
        yield debit_due
        yield debit_total



    # A dictionary with customer_id as keys
    wb_customers = {}
    
    # Get the Workbook departments
    departments = {}
    try:
        result = self.wb.get_departments()
    except Exception as e:
        print("Error getting departments from WB: {}".format(e))
        wb_error = True
    else:
        # Dict of departments with company ID is key
        departments = {d['CompanyId']:{} for d in result}
        for d in result:
            departments[d['CompanyId']][d['Id']] = d['Name']
        print(departments)

    # JOBS #

    job_age_days = GaugeMetricFamily(
        'workbook_job_age_days',
        'Days since job was created',
        labels=[
            "job_id",
            "name",
            "status_id",
            "company_id",
            "created",
            "type_id",
            "customer_id",
            "customer_name",
            "department_id",
            "department_name",
            "retainer",
            "billable",
            "days_to_end_date",
            ])


    try:
        result = self.wb.get_jobs(Status=ACTIVE_JOBS)
    except Exception as e:
        print(e)
        wb_error = True
    else:
        for j in result:
            
            # Maintain dict with no of jobs pr. customer
            if not j.get('CustomerId') in wb_customers.keys():
                wb_customers[j.get('CustomerId')] = {'no_of_jobs': 0}
            else:
                wb_customers[j.get('CustomerId')]['no_of_jobs'] += 1
                
            # Time job was created
            date_created = parse_date(j.get('CreateDate'))
            
            # End date for job
            date_end = parse_date(j.get('EndDate'))
            
            # Add the metric(lables, value)
            job_age_days.add_metric(
                [str(j.get('Id')),
                    j.get('JobName'),
                    str(j.get('StatusId')),
                    str(j.get('CompanyId')),
                    str(j.get('CreateDate')),
                    str(j.get('JobTypeId')),
                    str(j.get('CustomerId')),
                    str(j.get('CustomerName')),
                    str(j.get('CompanyDepartmentId')),
                    departments[j.get('CompanyId')][j.get('CompanyDepartmentId')],
                    "1" if j.get('RetainerJob') else "0",
                    "1" if j.get('Billable') else "0",
                    str((date_end - datetime.today()).days)
                    ],
                # Days since creation
                (datetime.today() - date_created).days
                )
    
    #yield job_age_days


    # EMPLOYEES #

    employee_days_employed = GaugeMetricFamily(
        'workbook_employee_days_employed',
        'Days since the employee was hired',
        labels=[
            "company_id",
            "employee_id",
            "department_id",
            "type_id",
            "sex_id",
            "position_id",
            "employment_type_id",
            ])

    try:
        # Get active employees
        employees = self.wb.get_employees(Active=True)
    except Exception:
        print("Could not get WB employees with error: {}".format(e))
        wb_error = True
    else:
        for e in employees:
            employee_days_employed.add_metric(
                [
                    str(e.get('CompanyId', '')),
                    str(e.get('Id', '')),
                    str(e.get('DepartmentId', '')),
                    str(e.get('TypeId', '')),
                    str(e.get('Sex', '')),
                    str(e.get('EmployeePosition', '')),
                    str(e.get('EmploymentTypeId', '')),
                ],
                (datetime.today() - parse_date(e['HireDate'])).days
                )

        #yield employee_days_employed

    # CUSTOMERS #

    customers = GaugeMetricFamily(
        'workbook_customer_active_jobs',
        'No of active jobs for Workbook customer',
        labels=[
            "customer_id",
            "type_id",
            "responsible_employee_id",
            "payment_term_id",
            "name",
            ]
        )

    try:
        result = self.wb.get_costumers(Active=True)
    except Exception as e:
        print("Could not get customers with error: {}".format(e))
    else:
        for c in result:

            try:
                n = wb_customers[c['Id']]['no_of_jobs']
            except KeyError:
                n = 0
            
            customers.add_metric(
                [
                    str(c.get('Id', '')),
                    str(c.get('TypeId', '')),
                    str(c.get('ResponsibleEmployeeId', '')),
                    str(c.get('PaymentTermId', '')),
                    str(c.get('Name', '')),
                ],
                n
            )


        #yield customers
    
    #print(wb_customers)
    
    # PROBLEMS WITH WORKBOOK? #

    metric = GaugeMetricFamily(
        'workbook_up',
        'Is data beeing pulled from Workbook'
        )

    if wb_error:
        metric.add_metric([], 0)
    else:
        metric.add_metric([], 1)

    yield metric


def parse_args():
    '''
    Parse the command line arguments
    '''

    # Parser object
    parser = argparse.ArgumentParser(
        description='Exports data from Workbook to be consumed by Prometheus'
    )

    # The Workbook URL
    parser.add_argument(
        '--workbook-url',
        #metavar='wb_url',
        required=False,
        help='Server url for the Workbook API',
        default=os.environ.get('WORKBOOK_URL', 'https://example.workbook.dk')
    )

    # The Workbook user
    parser.add_argument(
        '--workbook-user',
        required=False,
        help='User name for logging in to Workbook',
        default=os.environ.get('WORKBOOK_USER', 'workbook-user')
    )

    # The Workbook password
    parser.add_argument(
        '--workbook-password',
        required=False,
        help='Password to for logging in to Workbook',
        default=os.environ.get('WORKBOOK_PASSWORD', 'workbook-password')
    )

    return parser.parse_args()


def main():
    
    try:
        # Parse the command line arguments
        args = parse_args()

        REGISTRY.register(
            WorkbookCollector(
                args.workbook_url,
                args.workbook_user,
                args.workbook_password
                )
            )
        
        # Start up the server to expose the metrics.
        start_http_server(8000)
        
        # Generate some requests.
        while True:
            process_request(random.random())

    except KeyboardInterrupt:
        print(" Interrupted by keyboard")
        exit(0)


if __name__ == '__main__':
    main()
