#!/usr/bin/env python3

import argparse
from datetime import datetime, timedelta
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
ACTIVE_JOBS = [0,1,2,3]

# The type IDs of accounts to report balance for
FINANCE_ACCOUNT_TYPES = [3]
# The field with the reported balance metric
FINANCE_ACCOUNT_BALANCE_FIELD = 'AmountBeginning'

# Create a metric to track time spent and requests made.
REQUEST_TIME = Summary('request_processing_seconds', 'Time spent processing request')

# Fields to use for summing hours/week
EMPLOYEE_HOURS_CAPACITY_FIELDS = [
    "HoursNormalMonday",
    "HoursNormalTuesday",
    "HoursNormalWednesday",
    "HoursNormalThursday",
    "HoursNormalFriday",
    "HoursNormalSaturday",
    "HoursNormalSunday"
    ]

# The currency to use for reporting
REPORTING_CURRENCY_ID = 1

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

    def convert_to_reporting_currency(self, amount, currency_id, company_id):

        # Don't convert if amount is in reporting currency
        if currency_id == REPORTING_CURRENCY_ID:
            return amount

        converted_amount = self.wb.currency_convert(
            Amount=amount,
            FromCurrencyId=currency_id,
            ToCurrencyId=REPORTING_CURRENCY_ID,
            CompanyId=company_id)
        #print("Converted:", amount, self.currencies[currency_id], "to",
        #  converted_amount, self.currencies[REPORTING_CURRENCY_ID])
        return converted_amount

    def collect(self):

        # Metric for status on getting data from WB
        workbook_up = GaugeMetricFamily(
            'workbook_up', 'Is data beeing pulled from Workbook')

        # Assume no problems with getting data from Workbook
        wb_error = False

        # Get all the data from WB
        try:
            # A dictionary mapping id to ISO name
            self.currencies = {c['Id']:c['Iso4127'] for c in self.wb.get_currencies()}

            # A dictionary mapping id to company name
            #companies = {c['Id']:c['Name'] for c in self.wb.get_companies(active=True)}
            companies = {c['Id']:c for c in self.wb.get_companies(active=True)}

            # Add currency_id to companies
            for c_id, c_data in companies.items():
              # Get full company info from WB
              c_info = self.wb.get_company(CompanyId=c_id)
              # Add currency to company dict
              c_data['CurrencyId'] = c_info['CurrencyID']

            # A dictionary mapping IDs to employees
            employees = \
              {e['Id']:e for e in self.wb.get_employees(Active=True)}

            # Capacity profiles (Hours pr/day for employees)
            # EMployee ID is key
            capacity_profiles = {}
            for e in employees.values():
              #print(e['EmployeeName'], e['TimeRegistration'])
              # Get profile for employee
              assert not e['Id'] in capacity_profiles.keys()

              # Save latest (FIXME) profile for employee
              # FIXME: Choice must be based on field ValidFrom
              p = self.wb.get_capacity_profiles(e['Id'])[-1]

              # Add calculated sum of work hours pr. week to profile
              p['hours_week'] = 0
              for key in p.keys():
                if key in EMPLOYEE_HOURS_CAPACITY_FIELDS:
                  p['hours_week'] += p[key]

              # Add the profile to the profiles dict 
              capacity_profiles[e['Id']] = p

            # A dictionary mapping IDs to departments
            departments = {d['Id']:d for d in self.wb.get_departments()}

            # A dictionary mapping IDs to jobs
            jobs = {j['Id']:j for j in self.wb.get_jobs(Status=ACTIVE_JOBS)}

            # A dictionary mapping IDs to creditors
            creditors = {c['Id']:c for c in self.wb.get_creditors()}

            # Employee prices
            prices = self.wb.get_employee_prices_hour(ActiveEmployees=True)

            # A list of accounts
            accounts = self.wb.get_finance_accounts(
              TypeIds=FINANCE_ACCOUNT_TYPES)

            # Add balance to accounts
            for a in accounts:
              balance_list = self.wb.get_finance_account_balance(
                CompanyId=a['CompanyId'],
                AccountId=a['Id'],
                )
              # Makes sure we have data. Some typeIds do not.
              if len(balance_list) > 0:
                  # We want the latest balance entry.
                  # Assume latest entry has highest ID
                  # A dict with Ids as key
                  b = {b['Id']:b for b in balance_list}
                  # Get highest Id
                  max_id = max(b.keys())

                  # Add field Balance to account
                  a['balance'] = b[max_id].get(
                    FINANCE_ACCOUNT_BALANCE_FIELD, 0)

        except Exception as e:
            print("Error when getting data from Workbook: {}".format(e))
            # Report no data from Workbook
            workbook_up.add_metric([], 0)
            yield workbook_up
            return

        # FINANCE ACCOUNTS

        for a in accounts:
          # Get the currency to use
          currency_id = companies[a['CompanyId']]['CurrencyId']
          g = GaugeMetricFamily(
            'workbook_finance_account_balance',
            'Balance of finance account',
            labels=['company_id', 'currency', 'account_id', 'account_description', 'account_number']
            )
          g.add_metric(
            [str(a['CompanyId']), str(self.currencies[currency_id]), str(a['Id']), str(a['AccountDescription']), str(a['AccountNumber'])],
            a['balance']
            )
          yield g

        # Buckets for histograms
        days_employed_buckets = [3*30, 5*30, 2*12*30+9*30, 5*12*30+8*30, 8*12*30+7*30]
        job_age_buckets = [1, 15, 30, 2*30, 6*30, 365]
        profit_buckets = [0.2, 0.4, 0.6, 0.8]
        hours_sale_buckets = [500, 1000, 1500, 2000]
        hours_cost_buckets = [250, 500, 750, 1000]

        # FIXME: Credit/Debit buckets should probably be currency dependant
        credit_buckets = [-50000, -25000, -10000, 0, 10000, 25000, 50000]
        debit_buckets = [-50000, -25000, -10000, 0, 10000, 25000, 50000, 100000]

        # Days to look in to the past for timeentries
        time_entry_days = 7

        # TIME ENTRIES #
        # Time entries don't have ClientIds
        # FIxme: (We could look them up in jobs?)
        # Time period to get time entries for (Time where work was done)
        start_date = (datetime.today() - timedelta(days=time_entry_days)).isoformat()
        end_date = datetime.today().isoformat()

        # Top key is company_id:department_id
        time_entries_data = {c_id:{} for c_id in companies.keys()}

        for c_id, c_data in time_entries_data.items():
            for d_id, d_data in departments.items():
                if d_data['CompanyId'] == c_id:
                    c_data[d_id] = {
                        'billable': 0,
                        'total': 0,
                        'resource_ids': set(),
                        'job_ids': set(),
                        'customer_ids': set()
                        }

        # TIME ENTRIES #
        try:
          time_entries = self.wb.get_time_entries(
            Start=start_date, End=end_date,HasTimeRegistration=True)
        except Exception as e:
            print("Could not get WB time entries with error: {}".format(e))
            wb_error = True
        else:
            # FIXME: Label department
            # FIXME: Number of clients worked on
            for e in time_entries:
                # Sometimes a resource is no longer an employee
                if not employees.get(e['ResourceId']):
                  #print("No longer employee: ResourceId", e['ResourceId'])
                  continue

                c_id = employees[e['ResourceId']]['CompanyId']
                d_id = employees[e['ResourceId']]['DepartmentId']
                j_id = e['JobId']

                if jobs.get(j_id):
                    time_entries_data[c_id][d_id]['customer_ids'].add(jobs.get(j_id)['CustomerId'])

                h = e.get('Hours', 0)
                if e.get('Billable'):
                    time_entries_data[c_id][d_id]['billable'] += h
                time_entries_data[c_id][d_id]['total'] += h

                time_entries_data[c_id][d_id]['resource_ids'].add(e.get('ResourceId'))
                time_entries_data[c_id][d_id]['job_ids'].add(j_id)

            # Labels to use for the following metrics
            label_names = ['days','company_id', 'department_id']

            for c_id, c_data in time_entries_data.items():
                for d_id, d_data in c_data.items():
                    # Values for the labels
                    label_values = [
                        str(time_entry_days),
                        str(c_id),
                        str(d_id)]

                    # A list of IDs of all employees in this department
                    #dep_employee_ids = [e['Id'] for e in employees.values() if e['DepartmentId'] == d_id ]
                    #print(d_id,":",dep_emplyee_ids)
                    g = GaugeMetricFamily(
                      'workbook_time_entry_hours_total',
                      'Sum of hours entered by employees', labels=label_names)
                    g.add_metric(label_values, d_data['total'])
                    yield g

                    g = GaugeMetricFamily(
                      'workbook_time_entry_hours_billable',
                      'Number of billable hours', labels=label_names)
                    g.add_metric(label_values, d_data['billable'])
                    yield g

                    # No of employees in this dept expected to enter time
                    # FIXME: Only this department
                    no_of_employees_to_enter_time = len(
                      [e['Id'] for e in employees.values() if e['TimeRegistration'] and e['DepartmentId'] == d_id]
                      )
                    g = GaugeMetricFamily(
                      'workbook_time_entry_people_total',
                      'Number of people who must enter time', labels=label_names)
                    g.add_metric(label_values, no_of_employees_to_enter_time)
                    yield g

                    # Combined work hours for all employees
                    # FIXME: Only this department
                    sum_of_work_hours = sum(
                      [p['hours_week'] for p in capacity_profiles.values()]
                      )
                    g = GaugeMetricFamily(
                      'workbook_time_entry_hours_capacity_total',
                      'Sum of hours to be entered', labels=label_names)
                    g.add_metric(label_values, sum_of_work_hours)
                    yield g

                    g = GaugeMetricFamily(
                      'workbook_time_entry_people_with_time',
                      'Number of people having entered time entries', labels=label_names)
                    g.add_metric(label_values, len(d_data['resource_ids']))
                    yield g

                    g = GaugeMetricFamily(
                      'workbook_time_entry_jobs_total',
                      'Number of jobs with time entries', labels=label_names)
                    g.add_metric(label_values, len(d_data['job_ids']))
                    yield g

                    g = GaugeMetricFamily(
                      'workbook_time_entry_customers_total',
                      'Number of customers with time entries', labels=label_names)
                    g.add_metric(label_values, len(d_data['customer_ids']))
                    yield g


        # EMPLOYEE PRICES #
        try:
            # Get prices for active employees
            #prices = self.wb.get_employee_prices_hour(ActiveEmployees=True)
            pass
        except Exception as e:
            print("Could not get WB employees prices with error: {}".format(e))
            wb_error = True
        else:
            # A dict with company id as key for dicts with EmployeeId as key.
            # An employee can have more than 1 entry.
            # Only store the newest. They have ValidFrom date.
            # We don't know the company IDs  
            price_dict = {c_id:{} for c_id in companies.keys()}
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
              currency_id = companies[c_id]['CurrencyId']
              currency = self.currencies[currency_id]

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
              yield build_histogram(
                observations['Profit'],
                profit_buckets,
                'workbook_employees_profit_ratio',
                'Estimated sales price of 1 hours work',
                ['company_id'],
                [str(c_id)])

              # HOURS SALE #
              yield build_histogram(
                observations['HoursSale'],
                hours_sale_buckets,
                'workbook_employees_hours_sale',
                'Estimated sales price of 1 hours work',
                ['company_id', 'currency'],
                [str(c_id), currency])

              # HOURS COST #
              yield build_histogram(
                observations['HoursCost'],
                hours_cost_buckets,
                'workbook_employees_hours_cost',
                'Estimated cost of 1 hours work',
                ['company_id', 'currency'],
                [str(c_id), currency])

        # EMPLOYEES DAYS EMPLOYED #
        for company_id in companies.keys():
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
        for company_id in companies.keys():
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
                active_clients = {
                    'billable': set(),
                    'non_billable': set()
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
                        active_clients['billable'].add(j['CustomerId'])
                    else:
                        observations['non_billable'].append((date_end - datetime.today()).days)
                        active_clients['non_billable'].add(j['CustomerId'])

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

                cust_billable = GaugeMetricFamily(
                    'workbook_active_customers_billable_jobs',
                    'No of unique customers for billable active jobs',
                    labels=["company_id"])
                cust_billable.add_metric(
                    [str(company_id)],
                    len(active_clients['billable']))
                yield cust_billable

                cust_total = GaugeMetricFamily(
                    'workbook_active_customers_total_jobs',
                    'No of unique customers for all active jobs',
                    labels=["company_id"])
                cust_total.add_metric(
                  [str(company_id)],
                  len(active_clients['non_billable'].union(active_clients['billable']))
                  )
                yield cust_total

        # CREDIT #
        try:
            # Get all creditors accross companies
            #creditors = self.wb.get_creditors()
            pass
        except Exception as e:
            print("Error: {}".format(e))
            wb_error = True
        else:
            for company_id in companies.keys():
                # Get currency
                currency_id = companies[company_id]['CurrencyId']
                currency = self.currencies[currency_id]

                # Store credit observations here
                observations = {
                    'total': [],
                    'due': [],
                    }
                # Run through creditors for current company
                for c in creditors.values():
                    if c['CompanyId'] == company_id and c.get('CurrencyId') and c.get('RemainingAmountTotal'):

                        total = c.get('RemainingAmountTotal', None)
                        due = c.get('RemainingAmountDue', None)
                        c_id = c.get('CurrencyId')

                        if due:
                            observations['due'].append(due)

                        if total:
                            observations['total'].append(total)


                # Report metrics if no errors in WB
                if not wb_error:
                    # Credit total
                    yield build_histogram(
                       observations['total'],
                       credit_buckets,
                       'workbook_credit_total',
                       'Amount owed',
                       ['company_id', 'currency'],
                       [str(company_id), currency])

                    # Credit due
                    yield build_histogram(
                       observations['due'],
                       credit_buckets,
                       'workbook_credit_due',
                       'Amount owed',
                       ['company_id', 'currency'],
                       [str(company_id), currency])

        # DEBIT #
        for company_id in companies.keys():
            # Get currency
            currency_id = companies[company_id]['CurrencyId']
            currency = self.currencies[currency_id]
            try:
                debtors = self.wb.get_debtors_balance(company_id=company_id)
            except Exception as e:
                print("Error: {}".format(e))
                wb_error = True
            else:
                observations = {
                    'total': [],
                    'due': [],
                    }
                # Run through creditors for current company
                for d in debtors:
                    c_id = d.get('CurrencyId', False)
                    if c_id:
                        total = d.get('RemainingAmountTotal', None)
                        due = d.get('RemainingAmountDue', None)

                        if due:
                            observations['due'].append(due)

                        if total:
                            observations['total'].append(total)

                # Report metrics if no errors from WB
                if not wb_error:
                  # Debit total
                  yield build_histogram(
                     observations['total'],
                     debit_buckets,
                     'workbook_debit_total',
                     'Debit total',
                     ['company_id', 'currency'],
                     [str(company_id), currency])
  
                  # Debit due
                  yield build_histogram(
                     observations['due'],
                     debit_buckets,
                     'workbook_debit_due',
                     'Debit due',
                     ['company_id', currency],
                     [str(company_id), currency])

        
        # PROBLEMS WITH WORKBOOK? #

        if wb_error:
            workbook_up.add_metric([], 0)
        else:
            workbook_up.add_metric([], 1)
        yield workbook_up


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

    # Poprt to listen on
    parser.add_argument(
        '--port',
        type=int,
        required=False,
        help='Port to recieve request on. Defaults to 9701.',
        default=9701
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
        start_http_server(args.port)
        
        # Generate some requests.
        while True:
          pass
          process_request(random.random())

    except KeyboardInterrupt:
        print(" Interrupted by keyboard")
        exit(0)


if __name__ == '__main__':
    main()
