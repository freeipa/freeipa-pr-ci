#!/usr/bin/python3

import getpass
import github3
from datetime import datetime

# github = github3.login(token='')
github = github3.login('tomaskrizek', getpass.getpass())

rate_limit = github.rate_limit()['rate']
reset = rate_limit['reset']
remaining = rate_limit['remaining']
limit = rate_limit['limit']

reset_date = datetime.utcfromtimestamp(reset).strftime('%Y-%m-%d %H:%M')

print("Remaining {} out of {}. Will be reset on {} UTC"
      "".format(remaining, limit, reset_date))
