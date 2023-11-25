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

config = dotenv_values(".env")  
API_KEYS = json.loads(config["API_KEYS"])

def getBusStopTiming(bus_stop, api_key = API_KEYS, LTA_API = API_LTA_BUS()):
    temp_res = {}
    res = LTA_API.getBusStopTiming(bus_stop, api_key = api_key[random.randint(0, len(api_key) - 1)])
    if len(res["Services"]) > 0:
        temp_res["BusArrival"] = {
            res["BusStopCode"]: res["Services"]
        }
    return temp_res

def getBusStop():
    LTA_API = API_LTA_BUS()
    BUS_STOP_JSON = LTA_API.getAllBusStops()

    BUS_STOPS = []
    for bs in BUS_STOP_JSON:
        BUS_STOPS.append(bs["BusStopCode"])

    filename = f'export/busstop_{dt.datetime.now().strftime("%Y-%m-%d-%H-%M")}.json'
    with open(filename, "w") as outfile:
        json.dump(BUS_STOP_JSON, outfile)

    print("Bus Stop Dataset Exported!")

    return BUS_STOPS, dt.datetime.now().strftime("%Y-%m-%d")

def main():
    pool = Pool(processes=10)  # Create a pool of 10 processes
    BUS_STOPS = []
    BUS_STOPS_DATE = ""

    while True:
        while dt.datetime.now().second:
            if len(BUS_STOPS) == 0 or dt.datetime.now().strftime("%Y-%m-%d") != BUS_STOPS_DATE:
                BUS_STOPS, BUS_STOPS_DATE = getBusStop()
            time.sleep(0.01)

        start_time = dt.datetime.now()
        temp_res = pool.map(getBusStopTiming, BUS_STOPS, chunksize=10)[0]
        temp_res["Bus_Arrival_DateTime"] = str(start_time)
        end_time = dt.datetime.now()
        print(f"async started: {start_time} ended: {end_time}")
        json_object = json.dumps(temp_res, indent = 4) 
            
        filename = f'export/busarrival_{dt.datetime.now().strftime("%Y-%m-%d-%H-%M")}.json'
        with open(filename, "w") as outfile:
            outfile.write(json_object)

if __name__ == "__main__":
    main()