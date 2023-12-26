from dotenv import dotenv_values
from multiprocessing import Pool
from model.api import API_LTA_BUS
import datetime as dt
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
    BUS_STOP_JSON = json.load(open("export/busstop_current.json"))
    BUS_STOPS = []
    for bs in BUS_STOP_JSON:
        BUS_STOPS.append(bs["BusStopCode"])

    return BUS_STOPS

def checkNetworkConnectivity():
    LTA_API = API_LTA_BUS()
    BUS_ROUTES = LTA_API.getAllBusRoute()
    return BUS_ROUTES

def main():
    pool = Pool(processes=10)  # Create a pool of 10 processes
    BUS_STOPS = getBusStop()
    proc_res = {}
    start_time = dt.datetime.now()
    cur_date = start_time.strftime("%Y-%m-%d")
    logging(f"async started: {start_time} in progress...")

    # Insert check for internet connectivity
    if len(checkNetworkConnectivity()) == 0:
        logging(f"=======================================")
        logging(f"Internet Connectivity is down!")
        logging(f"async ended with errors...")
        logging(f"=======================================")
        return

    logging(f"async started: {start_time} in progress...")
    temp_res = pool.map(getBusStopTiming, BUS_STOPS, chunksize=10)
    proc_res["BusArrival"] = temp_res
    proc_res["BusArrival_DateTime"] = str(dt.datetime.now())
    end_time = dt.datetime.now()
    json_object = json.dumps(proc_res, indent = 4) 

    if not os.path.exists(f'export/{cur_date}'): 
        os.makedirs(f'export/{cur_date}') 

    filename = f'export/{cur_date}/busarrival_{dt.datetime.now().strftime("%Y-%m-%d-%H-%M")}.json'
    with open(filename, "w") as outfile:
        outfile.write(json_object)
    logging(f"async started: {start_time} ended: {end_time}")

    
    
if __name__ == "__main__":
    main()