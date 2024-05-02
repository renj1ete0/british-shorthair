import datetime as dt
from target_MSS import *

# this script batch pulls data from MSS API for the specified amount of days from the offset date

### OFFSET DATE ###
date = dt.datetime.now() - dt.timedelta(days=2) # from current date how many days to offset - generally don't recommend pulling current day data as not the entire day is available

for i in range(0, 120): # from the offset date above, how many days from that day and before to pull data
    datestr = (date - dt.timedelta(days=i)).strftime("%Y-%m-%d")
    getMSS(datestr)
