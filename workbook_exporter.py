#!/usr/bin/env python3

import argparse
from datetime import datetime
import os
import random
import time

from prometheus_client import start_http_server, Summary
from prometheus_client.core import GaugeMetricFamily, HistogramMetricFamily, REGISTRY
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


def data_to_histogram(observations, buckets):
    '''Returns a list of buckets with values and the sum of the observations
    
    Keyword arguments:
    observations (List): A list of numbers
    buckets (List): A list of bucket values
    '''
    
    # Convert buckets to a dict with bucket values as keys
    buckets = {v:0 for v in buckets}

    # Add key "infinite" if missing
    if not float("inf") in buckets.keys():
        buckets[float("inf")] = 0
    
    # Sort observations in to the bucket dict
    for o in observations:
        for key in sorted(buckets.keys()):
            if o <= key:
                buckets[key] += 1

    # List holding lists of [bucket_name, value]
    buckets_list = []
    
    # Add the bucket data to the buckets_list
    for key in sorted(buckets.keys()):
        # Calculate bucket name
        if key < float("inf"):
            bucket_name = str(key)
        else:
            bucket_name = "+Inf"
        # Append bucket data [name, value]
        buckets_list.append([bucket_name, buckets[key]])

    return(buckets_list, sum(observations))

def build_histogram(observations, buckets, name, desc, label_names, label_values):

    # Histogram billable (Total)
    bucket_values, buckets_sum = data_to_histogram(
        observations,
        buckets
        )

    # Job age histogram billable
    h = HistogramMetricFamily(name, desc, labels=label_names)

    # Add data
    h.add_metric(label_values, bucket_values, buckets_sum)

    # Return histogram with data
    return h


class WorkbookCollector(object):

    def __init__(self, wb_url, wb_user, wb_pass):
          # Workbook API object
          self.wb = workbook_api.WorkbookAPI(wb_url, wb_user, wb_pass)

    def collect(self):
    
        # A dictionary mapping id to ISO name
        currencies = {c['Id']:c['Iso4127'] for c in self.wb.get_currencies()}

        # A dictionary mapping id to company name
        self.companies = {c['Id']:c['Name'] for c in self.wb.get_companies(active=True)}

        # A dictionary mapping IDs to employees
        employees = {e['Id']:e for e in self.wb.get_employees(Active=True)}

        # Assume no problems with getting data from Workbook
        wb_error = False


        # Buckets for histograms
        days_employed_buckets = [3*30, 5*30, 2*12*30+9*30, 5*12*30+8*30, 8*12*30+7*30]
        job_age_buckets = [30, 2*30, 6*30, 365]
        profit_buckets = [0.2, 0.4, 0.6, 0.8]
        hours_sale_buckets = [500, 1000, 1500, 2000]
        hours_cost_buckets = [250, 500, 750, 1000]
        
        # FIXME: Credit/Debit buckets should probably be currency dependant
        credit_buckets = [-50000, -25000, -10000, 0, 10000, 25000, 50000]
        reporting_currency_id = 'DKK'

        #for company_id in self.companies.keys():
        try:
            # Get prices for active employees
            prices = self.wb.get_employee_prices_hour(ActiveEmployees=True)
        except Exception as e:
            print("Could not get WB employees prices with error: {}".format(e))
            wb_error = True
        else:
            # A dict with company id as key for dicts with EmployeeId as key.
            # An employee can have more than 1 entry.
            # Only store the newest. They have ValidFrom date.
            # We don't know the company IDs  
            price_dict = {c_id:{} for c_id in self.companies.keys()}
            #print(price_dict)
            for p in prices:
                # FIXME: We should abort if this ID is not in our
                # company list
                c_id = employees[p['EmployeeId']]['CompanyId']
                
                # If we allready have data on the current employee
                # We may need to update the price
                if price_dict[c_id].get(p['EmployeeId']):
                    # Date for currently known data
                    existing_date = parse_date(
                    price_dict[c_id][p['EmployeeId']]['ValidFrom']
                    )
                    # Dato for this price
                    new_date = parse_date(p['ValidFrom'])
                    # Update data if this entry is newer than existing
                    # date, but not in the future
                    if new_date > existing_date and new_date <= datetime.now():
                        price_dict[c_id][p['EmployeeId']] = p
                else:
                    # Add missing date
                    price_dict[c_id][p['EmployeeId']] = p
                
            # Loop through company price dicts
            for c_id, prices in price_dict.items():
              # FIXME: Make sure the company is in our list
              # It could possible be changed from config
              # Store observations for company here
              observations = {
                'Profit': [],
                'HoursCost': [],
                'HoursSale': []
                }
              # Loop price data, and add to observations dicts
              for e_id, p in prices.items():
                for field in observations.keys():
                  # Add observation if present
                  if p.get(field):
                    observations[field].append(p.get(field))

              # PROFIT #
              # FIXME: CURRENCY!
              yield build_histogram(
                observations['Profit'],
                profit_buckets,
                'workbook_employees_profit_ratio',
                'Estimated sales price of 1 hours work',
                ['company_id'],
                [str(c_id)])

              # HOURS SALE #
              # FIXME: CURRENCY!
              yield build_histogram(
                observations['HoursSale'],
                hours_sale_buckets,
                'workbook_employees_hours_sale',
                'Estimated sales price of 1 hours work',
                ['company_id', 'currency'],
                [str(c_id), 'DKK'])

              # HOURS COST #
              # FIXME: CURRENCY!
              yield build_histogram(
                observations['HoursCost'],
                hours_cost_buckets,
                'workbook_employees_hours_cost',
                'Estimated cost of 1 hours work',
                ['company_id', 'currency'],
                [str(c_id), 'DKK'])

        # EMPLOYEES #
        for company_id in self.companies.keys():
            try:
                # Get active employees
                employees = self.wb.get_employees(Active=True,CompanyId=company_id)
            except Exception as e:
                print("Could not get WB employees with error: {}".format(e))
                wb_error = True
            else:
                # Gather observations (Days since employment)
                observations = []
                for e in employees:
                    observations.append((datetime.today() - parse_date(e['HireDate'])).days)
                
                # Job age histogram (Non billable)
                yield build_histogram(
                   observations,
                   days_employed_buckets,
                   'workbook_employees_days_employed',
                   'Days since employment',
                   ['company_id'],
                   [str(company_id)])

        # JOBS #
        for company_id in self.companies.keys():
            try:
                # Get active jobs
                jobs = self.wb.get_jobs(Status=ACTIVE_JOBS, CompanyId=company_id)
            except Exception as e:
                print("Could not get WB jobs with error: {}".format(e))
                wb_error = True
            else:
                # Gather observations (Days since employment)
                observations = {
                    'billable': [],
                    'non_billable': []
                    }
                #no_of_billable_jobs = 0
                for j in jobs:
                    # Time job was created
                    date_created = parse_date(j.get('CreateDate'))
                    # End date for job
                    date_end = parse_date(j.get('EndDate'))
                    # Add observation
                    if j.get('Billable'):
                        observations['billable'].append((date_end - datetime.today()).days)
                    else:
                        observations['non_billable'].append((date_end - datetime.today()).days)

                # Job age histogram (billable)
                yield build_histogram(
                   observations['billable'],
                   job_age_buckets,
                   'workbook_jobs_age_days',
                   'Days since job was created',
                   ['company_id', 'billable'],
                   [str(company_id), '1'])

                # Job age histogram (Non billable)
                yield build_histogram(
                   observations['non_billable'],
                   job_age_buckets,
                   'workbook_jobs_age_days',
                   'Days since job was created',
                   ['company_id', 'billable'],
                   [str(company_id), '0'])


        # CREDIT #
        try:
            # Get all creditors accross companies
            creditors = self.wb.get_creditors()
        except Exception as e:
            print("Error: {}".format(e))
            wb_error = True
        else:
            for company_id in self.companies.keys():
                # Store credit observations here
                observations = {
                    'total': [],
                    'due': [],
                    }
                # Run through creditors for current company
                for c in [c for c in creditors if c['CompanyId'] == company_id]:
                    total = c.get('RemainingAmountTotal', None)
                    due = c.get('RemainingAmountDue', None)
                    # FIXME: Convert currency
                    if due:
                        observations['due'].append(due)
                    if total:
                        observations['total'].append(total)

                # Credit total
                yield build_histogram(
                   observations['total'],
                   credit_buckets,
                   'workbook_credit_total',
                   'Amount owed',
                   ['company_id', 'currency'],
                   [str(company_id), 'DKK'])

                # Credit due
                yield build_histogram(
                   observations['due'],
                   credit_buckets,
                   'workbook_credit_due',
                   'Amount owed',
                   ['company_id', 'currency'],
                   [str(company_id), 'DKK'])


        return
        #return
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
            credit = {company_id:{c:{'due':0.0, 'total':0.0} for c in currencies.values()} for company_id in self.companies.keys()}
    
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
                    credit_due.add_metric([str(company_id), cur], int(data['due']))
                    credit_total.add_metric([str(company_id), cur], int(data['total']))
    
            yield credit_due
            yield credit_total

        return 
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
            debtors = []
            for i in companies.keys():
                debtors += self.wb.get_debtors_balance(company_id=i)
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
                # Only get data from debtors with amounts
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
                    debit_due.add_metric([str(company_id), cur], int(data['due']))
                    debit_total.add_metric([str(company_id), cur], int(data['total']))

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
    
        '''
        employee_days_employed_o = GaugeMetricFamily(
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
        '''
    
        '''
        employees_days_employed = Histogram(
            'workbook_employees_days_employed',
            'Days passed since employment began'
            #labels=[],
            #buckets=(90, 365, 2 * 365, float("inf"))
            )
        '''
    
        '''
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
        '''
        #employee_days_employed.add_metric([],20)
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
          pass
          process_request(random.random())

    except KeyboardInterrupt:
        print(" Interrupted by keyboard")
        exit(0)


if __name__ == '__main__':
    main()
