from dotenv import dotenv_values
from multiprocessing import Pool
from model.api import API_LTA_BUS
import datetime as dt
import time
import json
import random
import os 

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

def getBusStopTiming(bus_stop, api_key = API_KEYS, LTA_API = API_LTA_BUS()):
    temp_res = {}
    res = LTA_API.getBusStopTiming(bus_stop, api_key = api_key[random.randint(0, len(api_key) - 1)])
    if "Services" in res:
        temp_res[res["BusStopCode"]] = res["Services"]
    else:
        try:
            if hasattr(res, "status_code"):
                logging(f"Error obtaining API data: {bus_stop}, status_code: {res.status_code} response: {res.text}")
                temp_res[bus_stop] = [{"Error": res.text}]
            else:
                logging(f"Error obtaining API data: {bus_stop}, response: {res}")
                temp_res[bus_stop] = [{"Error": res}]
        except:
            logging(f"Error with: {bus_stop}, response: unknown")        
    return temp_res

def getBusStop():
    LTA_API = API_LTA_BUS()
    BUS_STOP_JSON = LTA_API.getAllBusStops()

    BUS_STOPS = []
    for bs in BUS_STOP_JSON:
        BUS_STOPS.append(bs["BusStopCode"])

    cur_date = dt.datetime.now().strftime("%Y-%m-%d")
    if not os.path.exists(f'export/{cur_date}'): 
        os.makedirs(f'export/{cur_date}') 

    filename = f'export/{cur_date}/busstop_{dt.datetime.now().strftime("%Y-%m-%d")}.json'
    with open(filename, "w") as outfile:
        json.dump(BUS_STOP_JSON, outfile)

    logging(f"Bus Stop Dataset Exported! {filename}")

    return BUS_STOPS, dt.datetime.now().strftime("%Y-%m-%d")

def getBusRoute():
    LTA_API = API_LTA_BUS()
    BUS_ROUTES = LTA_API.getAllBusRoute()

    cur_date = dt.datetime.now().strftime("%Y-%m-%d")
    if not os.path.exists(f'export/{cur_date}'): 
        os.makedirs(f'export/{cur_date}') 

    filename = f'export/{cur_date}/busroute_{dt.datetime.now().strftime("%Y-%m-%d")}.json'
    with open(filename, "w") as outfile:
        json.dump(BUS_ROUTES, outfile)

    logging(f"Bus Routes Dataset Exported! {filename}")

    return dt.datetime.now().strftime("%Y-%m-%d")

def getBusService():
    LTA_API = API_LTA_BUS()
    BUS_SERVICE = LTA_API.getAllBusService()

    cur_date = dt.datetime.now().strftime("%Y-%m-%d")
    if not os.path.exists(f'export/{cur_date}'): 
        os.makedirs(f'export/{cur_date}') 

    filename = f'export/{cur_date}/busservice_{dt.datetime.now().strftime("%Y-%m-%d")}.json'
    with open(filename, "w") as outfile:
        json.dump(BUS_SERVICE, outfile)

    logging(f"Bus Service Dataset Exported! {filename}")

    return dt.datetime.now().strftime("%Y-%m-%d")

def main():
    pool = Pool(processes=10)  # Create a pool of 10 processes
    BUS_STOPS = []
    BUS_STOPS_DATE_TIME = dt.datetime.now().strftime("%Y-%m-%d-%H-%M")
    BUS_STOPS_DATE = ""
    BUS_ROUTES_DATE = ""
    BUS_SERVICES_DATE = ""
    cur_datetime = dt.datetime.now().strftime("%Y-%m-%d-%H-%M")

    while True:
        while BUS_STOPS_DATE_TIME == cur_datetime:
            cur_date = dt.datetime.now().strftime("%Y-%m-%d")
            cur_datetime = dt.datetime.now().strftime("%Y-%m-%d-%H-%M")
            if len(BUS_STOPS) == 0 or cur_date != BUS_STOPS_DATE:
                BUS_STOPS, BUS_STOPS_DATE = getBusStop()
            if cur_date != BUS_ROUTES_DATE:
                BUS_ROUTES_DATE = getBusRoute()
            if cur_date != BUS_SERVICES_DATE:
                BUS_SERVICES_DATE = getBusService()
            time.sleep(0.01)

        cur_date = dt.datetime.now().strftime("%Y-%m-%d") # refresh current date for new day 0000hrs case
        proc_res = {}
        start_time = dt.datetime.now()
        temp_res = pool.map(getBusStopTiming, BUS_STOPS, chunksize=10)
        proc_res["BusArrival"] = temp_res
        proc_res["BusArrival_DateTime"] = str(dt.datetime.now())
        end_time = dt.datetime.now()
        logging(f"async started: {start_time} ended: {end_time}")
        json_object = json.dumps(proc_res, indent = 4) 

        if not os.path.exists(f'export/{cur_date}'): 
            os.makedirs(f'export/{cur_date}') 

        filename = f'export/{cur_date}/busarrival_{dt.datetime.now().strftime("%Y-%m-%d-%H-%M")}.json'
        with open(filename, "w") as outfile:
            outfile.write(json_object)

        BUS_STOPS_DATE_TIME = dt.datetime.now().strftime("%Y-%m-%d-%H-%M")

if __name__ == "__main__":
    main()