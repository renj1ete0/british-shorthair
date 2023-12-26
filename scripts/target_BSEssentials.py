from model.api import API_LTA_BUS
import datetime as dt
import json
import os 
import time

if not os.path.exists("export"): 
    os.makedirs("export") 

if not os.path.exists("logs"): 
    os.makedirs("logs") 

def logging(msg):
    print(msg)
    with open(f'logs/logs_{dt.datetime.now().strftime("%Y-%m-%d")}.json', "a") as f:
        f.write(f'{dt.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")}: {msg}\n')

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
    logging(f"=======================================")
    logging(f"Bus Stop Dataset Exported! {filename}")
    logging(f"=======================================")

    filename = f'export/busstop_current.json'
    with open(filename, "w") as outfile:
        json.dump(BUS_STOP_JSON, outfile)
    logging(f"=======================================")
    logging(f"Bus Stop Dataset Exported! {filename}")
    logging(f"=======================================")

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
    logging(f"=======================================")
    logging(f"Bus Routes Dataset Exported! {filename}")
    logging(f"=======================================")

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
    logging(f"=======================================")
    logging(f"Bus Service Dataset Exported! {filename}")
    logging(f"=======================================")

    return dt.datetime.now().strftime("%Y-%m-%d")

def checkNetworkConnectivity():
    LTA_API = API_LTA_BUS()
    BUS_ROUTES = LTA_API.getBusRoutes(0)
    return BUS_ROUTES.status_code != 200


def main():
    while checkNetworkConnectivity():
        logging(f"=======================================")
        logging(f"Internet Connectivity is down!")
        logging(f"=======================================")
        time.sleep(60)
        
    getBusStop()
    getBusRoute()
    getBusService()

    
if __name__ == "__main__":
    main()