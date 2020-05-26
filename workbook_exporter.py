#!/usr/bin/env python3

import argparse
from datetime import datetime, timedelta
import logging
import os
import random
import time

from prometheus_client import start_http_server, Summary
from prometheus_client.core import GaugeMetricFamily, HistogramMetricFamily, REGISTRY
import workbook_api
import yaml

# The string to use when converting times in Workbook
# Example: 2020-08-17T09:02:23.677Z
TIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"

# The field with the reported balance metric
FINANCE_ACCOUNT_BALANCE_FIELD = 'AmountBeginning'

# Create a metric to track time spent and requests made.
#REQUEST_TIME = Summary('request_processing_seconds', 'Time spent processing request')

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

# Decorate function with metric.
#@REQUEST_TIME.time()
#def process_request(t):
#    """A dummy function that takes some time."""
#    time.sleep(t)


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

        logging.info("Getting data from Workbook.")

        scrape_start_time = datetime.now()

        # Metric for status on getting data from WB
        workbook_up = GaugeMetricFamily(
            'workbook_up', 'Is data beeing pulled from Workbook')

        # Assume no problems with getting data from Workbook
        wb_error = False

        # How many requests were made to workbook?
        no_of_wb_requests = 0

        # Get all the data from WB
        try:

            # A dictionary mapping id to ISO name
            self.currencies = {c['Id']:c['Iso4127'] for c in self.wb.get_currencies()}
            no_of_wb_requests += 1

            # A dictionary mapping id to company name
            companies = {c['Id']:c for c in self.wb.get_companies(active=True)}
            no_of_wb_requests += 1

            # Delete any companies not in list in config file
            if COMPANIES_TO_GET:
              companies_to_delete = []
              # Register company IDs to delete
              for c_id in companies.keys():
                if c_id not in COMPANIES_TO_GET:
                  companies_to_delete.append(c_id)

              # Delete the company IDs from the companies dict
              for c_id in companies_to_delete:
                companies.pop(c_id, None)

            # Warn if companies in COMPANIES_TO_GET are not found in WB
            only_in_config = set(COMPANIES_TO_GET) - set(companies.keys())
            if only_in_config:
              logging.warning(("Company IDs {} not in Workbook. Likely a wrong" + \
                " ID in config 'companies'.").format(only_in_config))


            # Add currency_id to companies
            for c_id, c_data in companies.items():
              # Get full company info from WB
              c_info = self.wb.get_company(CompanyId=c_id)
              no_of_wb_requests += 1
              # Add currency to company dict
              c_data['CurrencyId'] = c_info['CurrencyID']


            # A dictionary mapping IDs to employees
            employees = {}
            # Get employees for all companies
            for c_id in companies.keys():
              for e in self.wb.get_employees(Active=True, CompanyId=c_id):
                employees[e['Id']] = e
              no_of_wb_requests += 1


            # Capacity profiles (Hours pr/week for employees)
            # EMployee ID is key
            capacity_profiles = {}
            for e in employees.values():
              
              # We should only see an employee ID once
              assert not e['Id'] in capacity_profiles.keys()

              # Get all profiles for employee
              try:
                profiles = self.wb.get_capacity_profiles(e['Id'])
                no_of_wb_requests += 1
              except Exception as e:
                logging.error("Could not get capacity profiles for employee '{}' with error: {}"
                  .format(e['Id'], e))
                # Abort this iteration
                continue

              logging.debug("No of capacity profiles for user '{}': {}"
                .format(e['EmployeeName'], len(profiles)))

              # Pick 1st profile in list
              p = profiles[-1]

              # Is there a newer profile in in list?
              for x in profiles:
                # Abort if profile is in the future
                if parse_date(x['ValidFrom']) > datetime.now():
                  continue
                # Use this profile, if valid from is more recent than current
                if parse_date(x['ValidFrom']) > parse_date(p['ValidFrom']):
                  p = x

              logging.debug("Using capacity profile valid from {} for user '{}'"
                .format(p['ValidFrom'], e['EmployeeName']))

              # Add calculated sum of work hours pr. week to profile
              p['hours_week'] = 0
              for key in p.keys():
                if key in EMPLOYEE_HOURS_CAPACITY_FIELDS:
                  p['hours_week'] += p[key]

              # Add the profile to the profiles dict 
              capacity_profiles[e['Id']] = p


            # A dictionary mapping IDs to departments
            departments = {d['Id']:d for d in self.wb.get_departments()}
            no_of_wb_requests += 1

            # A dictionary mapping Job IDs to jobs
            jobs = {}
            # Get jobs for all companies
            for c_id in companies.keys():
              for j in self.wb.get_jobs(Status=ACTIVE_JOBS,CompanyId=c_id):
                jobs[j['Id']] = j
                no_of_wb_requests += 1


            # A dictionary mapping IDs to creditors
            creditors = {c['Id']:c for c in self.wb.get_creditors()}
            no_of_wb_requests += 1


            # Employee prices
            prices = self.wb.get_employee_prices_hour(ActiveEmployees=True)
            no_of_wb_requests += 1


            # Get a list of finance accounts
            accounts = self.wb.get_finance_accounts(
              TypeIds=FINANCE_ACCOUNT_TYPES,
              Companies=companies.keys())
            no_of_wb_requests += 1


            # Add balance to accounts
            for a in accounts:
              balance_list = self.wb.get_finance_account_balance(
                CompanyId=a['CompanyId'],
                AccountId=a['Id'],
                )
              no_of_wb_requests += 1

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
            logging.error("Could not get data from Workbook: {}".format(e))
            # Report no data from Workbook
            workbook_up.add_metric([], 0)
            yield workbook_up
            return
        else:
          logging.info("Done getting data from Workbook")


        # FINANCE ACCOUNTS

        for a in accounts:
          # Some account types (2?) has no balance
          # It's only used cosmetically in Workbook
          if a.get('balance'):

            # Get the currency to use
            currency_id = companies[a['CompanyId']]['CurrencyId']
            g = GaugeMetricFamily(
              'workbook_finance_account_balance',
              'Balance of finance account',
              labels=[
                'company_id',
                'currency',
                'account_id',
                'account_description',
                'account_number'
                ]
              )
            g.add_metric(
                [str(a['CompanyId']),
                str(self.currencies[currency_id]),
                str(a['Id']), str(a['AccountDescription']),
                str(a['AccountNumber'])],
                a['balance']
              )
            yield g

        # Buckets for histograms
        # Add Buckets to config
        days_employed_buckets = [3*30, 5*30, 2*12*30+9*30, 5*12*30+8*30, 8*12*30+7*30]
        profit_buckets = [0.2, 0.4, 0.6, 0.8]
        hours_sale_buckets = [500, 1000, 1500, 2000]
        hours_cost_buckets = [250, 500, 750, 1000]

        # FIXME: Credit/Debit buckets should probably be currency dependant
        credit_buckets = [-50000, -25000, -10000, 0, 10000, 25000, 50000]
        debit_buckets = [-50000, -25000, -10000, 0, 10000, 25000, 50000, 100000]

        # FIXME: Add list of company ids to look for
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
        # Add departments
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
          no_of_wb_requests += 1
        except Exception as e:
            print("Could not get WB time entries with error: {}".format(e))
            wb_error = True
        else:
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
            label_names = [
              'days',
              'company_id',
              'department_id',
              'department_name'
              ]

            # Run through the time entries
            for c_id, c_data in time_entries_data.items():
                for d_id, d_data in c_data.items():
                    # Values for the labels
                    label_values = [
                        str(time_entry_days),
                        str(c_id),
                        str(d_id),
                        departments[d_id]['Name'].strip()
                        ]

                    # A list of IDs of all employees in this department
                    d_employees = [
                      e['Id'] for e in employees.values() if \
                      e['TimeRegistration'] and e['DepartmentId'] == d_id
                      ]

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

                    g = GaugeMetricFamily(
                      'workbook_time_entry_people_total',
                      'Number of people who must enter time', labels=label_names)
                    g.add_metric(label_values, len(d_employees))
                    yield g

                    # Sum of work hours for all employees in department
                    sum_of_work_hours = sum([
                      p['hours_week'] for p in capacity_profiles.values() if \
                       p['ResourceId'] in d_employees])
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

                # company list
                try:
                  # The employee
                  e = employees[p['EmployeeId']]
                  # Employee's company
                  c_id = e['CompanyId']
                  # Employees's department
                  d_id = e['DepartmentId']
                except KeyError:
                  # Abort because employee ID from price is not
                  # in employees (Not employed at company we report for)
                  # (Can not filter on companies for prices)
                  continue

                # Don't process users not registering time
                if not e['TimeRegistration']:
                  logging.debug("Ignoring user {} when reporting employee prices"
                    .format(e['EmployeeName']))
                  continue

                # Add department dict if needed
                if d_id not in price_dict[c_id]:
                  price_dict[c_id][d_id] = {}

                # If we allready have data on the current employee
                # We may need to update the price
                if price_dict[c_id][d_id].get(p['EmployeeId']):
                    # Date for currently known data
                    existing_date = parse_date(
                      price_dict[c_id][d_id][p['EmployeeId']]['ValidFrom'])

                    # Dato for this price
                    new_date = parse_date(p['ValidFrom'])
                    # Update data if this entry is newer than existing
                    # date, but not in the future
                    if new_date > existing_date and new_date <= datetime.now():
                        price_dict[c_id][d_id][p['EmployeeId']] = p
                else:
                    # Add missing date
                    price_dict[c_id][d_id][p['EmployeeId']] = p

            # Loop through company price dicts
            for c_id, c_prices in price_dict.items():
                for d_id, d_prices in c_prices.items():
                    currency_id = companies[c_id]['CurrencyId']
                    currency = self.currencies[currency_id]
                    d_name = departments[d_id]['Name']

                    # Store observations for company here
                    observations = {
                      'Profit': [],
                      'HoursCost': [],
                      'HoursSale': []
                      }

                    # Loop price data, and add to observations dicts
                    for e_id, p in d_prices.items():
                      for field in observations.keys():
                        # Add observation if present
                        try:
                          observations[field].append(p[field])
                        except KeyError as e:
                          observations[field].append(0.0)
                          logging.warning("Missing key {} for employee '{}'. Inserted 0.0"
                            .format(e, employees[p['EmployeeId']]['EmployeeName']))

                    # PROFIT #
                    yield build_histogram(
                      observations['Profit'],
                      profit_buckets,
                      'workbook_employees_profit_ratio',
                      'Estimated sales price of 1 hours work',
                      ['company_id', 'department_id', 'department_name'],
                      [str(c_id), str(d_id), d_name])

                    # HOURS SALE #
                    yield build_histogram(
                      observations['HoursSale'],
                      hours_sale_buckets,
                      'workbook_employees_hours_sale',
                      'Estimated sales price of 1 hours work',
                      ['company_id', 'department_id', 'department_name', 'currency'],
                      [str(c_id), str(d_id), d_name, currency])

                    # HOURS COST #
                    yield build_histogram(
                      observations['HoursCost'],
                      hours_cost_buckets,
                      'workbook_employees_hours_cost',
                      'Estimated cost of 1 hours work',
                      ['company_id', 'department_id', 'department_name', 'currency'],
                      [str(c_id), str(d_id), d_name, currency])


        # EMPLOYEES DAYS EMPLOYED #
        for company_id in companies.keys():
            try:
                # Get active employees
                employees = self.wb.get_employees(Active=True,CompanyId=company_id)
                no_of_wb_requests += 1
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


        # FIXME: Add config with costumers to ignore (Pseudo costumers)
        # FIXME: Active clients pr. department
        # JOBS #
        for company_id in companies.keys():
            try:
                # Get active jobs
                jobs = self.wb.get_jobs(Status=ACTIVE_JOBS, CompanyId=company_id)
                no_of_wb_requests += 1
            except Exception as e:
                logging.error("Could not get WB jobs with error: {}".format(e))
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
                    # Days since job was created
                    job_age = (datetime.today() - date_created).days
                    if j.get('Billable'):
                        observations['billable'].append(job_age)
                        active_clients['billable'].add(j['CustomerId'])
                    else:
                        observations['non_billable'].append(job_age)
                        active_clients['non_billable'].add(j['CustomerId'])

                # Job age histogram (billable)
                yield build_histogram(
                   observations['billable'],
                   JOB_AGE_BUCKETS,
                   'workbook_jobs_age_days',
                   'Days since job was created',
                   ['company_id', 'billable'],
                   [str(company_id), '1'])

                # Job age histogram (Non billable)
                yield build_histogram(
                   observations['non_billable'],
                   JOB_AGE_BUCKETS,
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

                # Active client age
                # Billable
                client_age_billable = []
                for c_id in list(active_clients['billable']):
                  c = self.wb.get_costumers(costumer_id=c_id)
                  no_of_wb_requests += 1
                  # Observe WonDate
                  if c.get('WonDate'):
                    won_date = parse_date(c.get('WonDate'))
                    client_age_billable.append((datetime.today() - won_date).days)
                  else:
                    # Client has no WonDate?
                    logging.warning("Customer {} with billable job has no 'WonDate' in Workbook".format(c['Name']))

                # Client age histogram (billable)
                yield build_histogram(
                   client_age_billable,
                   CLIENT_AGE_BUCKETS,
                   'workbook_active_customers_age_days',
                   'Days since client was created',
                   ['company_id', 'billable'],
                   [str(company_id), '1'])

                # Non billable
                client_age_non_billable = []
                for c_id in list(active_clients['non_billable']):
                  c = self.wb.get_costumers(costumer_id=c_id)
                  no_of_wb_requests += 1
                  # Observe WonDate
                  if c.get('WonDate'):
                    won_date = parse_date(c.get('WonDate'))
                    client_age_non_billable.append((datetime.today() - won_date).days)
                  else:
                    # Client has no WonDate?
                    logging.warning("Customer {} with non billable job has no 'WonDate' in Workbook".format(c['Name']))

                # Client age histogram (Non billable)
                yield build_histogram(
                   client_age_non_billable,
                   CLIENT_AGE_BUCKETS,
                   'workbook_active_customers_age_days',
                   'Days since client was created',
                   ['company_id', 'billable'],
                   [str(company_id), '0'])

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
                no_of_wb_requests += 1
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
                     ['company_id', 'currency'],
                     [str(company_id), currency])

        # How many requests did we make to the Workbook API?
        g = GaugeMetricFamily(
            'workbook_no_of_api_requests',
            'Number of requests to Workbook performed during scrape')
        g.add_metric([], no_of_wb_requests)
        yield g

        scrape_time_seconds = (datetime.now()-scrape_start_time).seconds
        # How long did the scape take?
        g = GaugeMetricFamily(
            'workbook_scrape_duration_seconds',
            'Number of seconds it took to perform scrape')
        g.add_metric([], scrape_time_seconds)
        yield g


        # Problems getting data from workbook?
        if wb_error:
            workbook_up.add_metric([], 0)
        else:
            workbook_up.add_metric([], 1)
        yield workbook_up



        if wb_error:
          logging.error("Error exporting data from workbook")
        else:
          logging.info("Scrape finished in {} seconds with {} requests to Workbook API"
            .format(scrape_time_seconds, no_of_wb_requests))


def parse_args():
    '''
    Parse the command line arguments
    '''

    # Defaults
    default_port = 9701
    default_log = '/var/log/workbook_exporter.log'
    default_level = 'INFO'
    default_config = '/etc/workbook_exporter.yml'

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
        default=os.environ.get('WORKBOOK_URL', None)
    )

    # The Workbook user
    parser.add_argument(
        '--workbook-user',
        required=False,
        help='User name for logging in to Workbook',
        default=os.environ.get('WORKBOOK_USER', None)
    )

    # The Workbook password
    parser.add_argument(
        '--workbook-password',
        required=False,
        help='Password for logging in to Workbook',
        default=os.environ.get('WORKBOOK_PASSWORD', None)
    )

    # Port to listen on
    parser.add_argument(
        '--port',
        metavar=default_port,
        required=False,
        type=int,
        help='Port to recieve request on.',
        default=default_port
    )

    # Location of log file
    parser.add_argument(
        '--log-file',
        metavar=default_log,
        required=False,
        help='Location of log file.',
        default=default_log
    )

    # Log level
    parser.add_argument(
      "--log-level",
      metavar=default_level,
      choices=['DEBUG', 'INFO', 'WARNING', 'ALL'],
      default=default_level,
      help="Set log level to one of: DEBUG, INFO, WARNING , ALL."
      )

    # Location of config file
    parser.add_argument(
        '--conf-file',
        metavar=default_config,
        required=False,
        help='Location of config file in YAML format.',
        default=default_config
    )

    # Disable log to stdout. Default false
    parser.add_argument(
        "--disable-log-stdout",
        # True if specified, False otherwise
        action='store_true',
        help="Specify to disable logging to stdout (Print in terminal)."
    )

    # Disable log to file. Default false
    parser.add_argument(
        "--disable-log-file",
        # True if specified, False otherwise
        action='store_true',
        help="Specify to disable logging to file."
    )

    return parser.parse_args()


def parse_config(config_file):
  '''Parse content of YAML configuration file to dict'''

  # Open file stream
  stream = open(config_file, 'r')

  # Get at dictionary of the data
  config_dict = yaml.load(stream, Loader=yaml.FullLoader)

  # Close file
  stream.close()

  return config_dict


def main():
    
    try:
        # Parse the command line arguments
        args = parse_args()

        # A list of logging handlers
        logging_handlers = []

        # Handler for logging to file
        if not args.disable_log_file:
          logging_handlers.append(logging.FileHandler(args.log_file))

        # Log to stdout if not disabled
        if not args.disable_log_stdout:
          logging_handlers.append(logging.StreamHandler())

        # Abort if all logging disabled by user
        if logging_handlers == []:
          print("Error: Can not run with all logging disabled.")
          exit(1)

        # Configure logging
        logging.basicConfig(
          level = eval("logging." + args.log_level),
          format='%(asctime)s:%(levelname)s:%(message)s',
          handlers = logging_handlers
          )

        logging.info("Starting workbook_exporter")

        # Get credentials from CLI (Including environment vars)
        wb_url = args.workbook_url
        wb_user = args.workbook_user
        wb_password = args.workbook_password

        # Get configuration in YAML file
        config = parse_config(args.conf_file)

        # Fall back to credentials in config file
        if not wb_url:
          wb_url = config['workbook']['url']
          wb_user = config['workbook']['user']
          wb_password = config['workbook']['password']

        # Jobs with these states are considered active
        global ACTIVE_JOBS
        ACTIVE_JOBS = config['workbook'].get('active_jobs', [0,1,2,3])
        if not isinstance(ACTIVE_JOBS, list):
          raise ValueError("Active job states is not a list")

        # Only get data on these companies. If empty list,
        # get data for all companies in Workbook
        global COMPANIES_TO_GET
        COMPANIES_TO_GET = config['workbook'].get('companies', [])
        if not isinstance(COMPANIES_TO_GET, list):
          raise ValueError("Value companies is not a list in config file")

        global FINANCE_ACCOUNT_TYPES
        FINANCE_ACCOUNT_TYPES = config['workbook'].get('finance_account_types', [3])
        if not isinstance(FINANCE_ACCOUNT_TYPES, list):
          raise ValueError("Value finance_account_types is not a list in config file")

        global JOB_AGE_BUCKETS
        JOB_AGE_BUCKETS = config['data'].get('job_age_buckets')
        if not isinstance(JOB_AGE_BUCKETS, list):
          raise ValueError("Value job_age_buckets is not a list in config file")

        global CLIENT_AGE_BUCKETS
        CLIENT_AGE_BUCKETS = config['data'].get('client_age_buckets')
        if not isinstance(CLIENT_AGE_BUCKETS, list):
          raise ValueError("Value client_age_buckets is not a list in config file")


        # Instantiate collector
        REGISTRY.register(
            WorkbookCollector(
                wb_url,
                wb_user,
                wb_password
                )
            )

        # Listen for scrape requests.
        start_http_server(args.port)

        # Run forever
        while True:
          time.sleep(1)
          #pass
        #  #process_request(random.random())

    except KeyboardInterrupt:
        print(" Interrupted by keyboard")
        exit(0)


if __name__ == '__main__':
    main()
