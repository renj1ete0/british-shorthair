import os
from dotenv import dotenv_values
import datetime as dt
import json
import requests

if not os.path.exists("export"): 
    os.makedirs("export") 

if not os.path.exists("logs"): 
    os.makedirs("logs") 

config = dotenv_values(".env")  
API_KEYS = json.loads(config["API_KEYS"])

def logging(msg):
    print(msg)
    with open(f'logs/logs_{dt.datetime.now().strftime("%Y-%m-%d")}.json', "a") as f:
        f.write(f'{dt.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")}: {msg}\n')
