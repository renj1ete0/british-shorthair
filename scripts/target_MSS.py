from model.api import API_DATAGOV_MSS
import time
from common import *
import json
import requests

def outputCSV(data, filename, count):
    try:
        with open(filename, "a") as outfile:
            outfile.write(data + "\n")
    except:
        count += 1
    
    return count

def handleResp(resp):
    if resp.status_code == 200:
        return resp.json()
    return False

def getRainfall(API, date = None, datetime = None):
    if date is not None:
        resp = API.getMSSRainfall(date = date)
        resp = handleResp(resp)
        if 'metadata' in resp and 'api_info' in resp:
            if resp['api_info']['status'] == 'healthy':

                # Export stations to JSON
                count = 0
                for stns in resp['metadata']['stations']:
                    count = outputCSV(f"{stns['id']}, {stns['device_id']},{stns['name']},{stns['location']['latitude']},{stns['location']['longitude']}", f"export_mss/{date}/rainfall_stations_{date}.csv", count)
                if count == 0:
                    logging(f"=======================================")
                    logging(f"MSS Rainfall Stations: Exported {date}")
                    logging(f"=======================================")

                #   Export readings to JSON
                count = 0
                for stns in resp['items']:
                    for reading in stns['readings']:
                        count = outputCSV(f"{stns['timestamp']},{reading['station_id']},{reading['value']}", f"export_mss/{date}/rainfall_readings_{date}.csv", count)
                if count == 0:
                    logging(f"=======================================")
                    logging(f"MSS Rainfall Readings: Exported {date}")
                    logging(f"=======================================")

def getWindDir(API, date = None, datetime = None):
    if date is not None:
        resp = API.getMSSWindDir(date = date)
        resp = handleResp(resp)
        if 'metadata' in resp and 'api_info' in resp:
            if resp['api_info']['status'] == 'healthy':

                # Export stations to JSON
                count = 0
                for stns in resp['metadata']['stations']:
                    count = outputCSV(f"{stns['device_id']},{stns['name']},{stns['location']['latitude']},{stns['location']['longitude']}", f"export_mss/{date}/winddir_stations_{date}.csv", count)
                if count == 0:
                    logging(f"=======================================")
                    logging(f"MSS WindDir Stations: Exported {date}")
                    logging(f"=======================================")

                #   Export readings to JSON
                count = 0
                for stns in resp['items']:
                    for reading in stns['readings']:
                        count = outputCSV(f"{stns['timestamp']},{reading['station_id']},{reading['value']}", f"export_mss/{date}/winddir_readings_{date}.csv", count)
                if count == 0:
                    logging(f"=======================================")
                    logging(f"MSS WindDir Readings: Exported {date}")
                    logging(f"=======================================")

def getUVIdx(API, date = None, datetime = None):
    if date is not None:
        resp = API.getMSSUVIdx(date = date)
        resp = handleResp(resp)
        if 'items' in resp and 'api_info' in resp:
            if resp['api_info']['status'] == 'healthy':

                # export readings
                count = 0
                for stns in resp['items']:
                    for reading in stns['index']:
                        count = outputCSV(f"{stns['timestamp']},{stns['update_timestamp']}, {reading['timestamp']}, {reading['value']}", f"export_mss/{date}/uvidx_readings_{date}.csv", count)
                if count == 0:
                    logging(f"=======================================")
                    logging(f"MSS UV Index Stations: Exported {date}")
                    logging(f"=======================================")

def getPSI(API, date = None, datetime = None):
    if date is not None:
        resp = API.getMSSPSI(date = date)
        resp = handleResp(resp)
        if 'region_metadata' in resp and 'api_info' in resp:
            if resp['api_info']['status'] == 'healthy':

                # export regions
                count = 0 
                for regions in resp['region_metadata']:
                    count = outputCSV(f"{regions['name']},{regions['label_location']['latitude']},{regions['label_location']['longitude']}", f"export_mss/{date}/psi_regions_{date}.csv", count)

                # export readings
                count = 0
                for item in resp['items']:
                    for reading in item['readings']:
                        count = outputCSV(f"{item['timestamp']}, {item['update_timestamp']}, {item['readings'][reading]['west']}, {item['readings'][reading]['east']}, {item['readings'][reading]['central']}, {item['readings'][reading]['south']}, {item['readings'][reading]['north']}", f"export_mss/{date}/psi_{reading}_readings_{date}.csv", count)

                if count == 0:
                    logging(f"=======================================")
                    logging(f"MSS PSI Readings: Exported {date}")
                    logging(f"=======================================")

def get24HrForecast(API, date = None, datetime = None):
    if date is not None:
        resp = API.getMSS24HrFCast(date = date)
        resp = handleResp(resp)
        if 'items' in resp and 'api_info' in resp:
            if resp['api_info']['status'] == 'healthy':

                # export regions
                count = 0 
                for item in resp['items']:
                    count = outputCSV(f"{item['update_timestamp']}, {item['timestamp']}, {item['valid_period']['start']}, {item['valid_period']['end']}, {item['general']['forecast']}, {item['general']['relative_humidity']['low']}, {item['general']['relative_humidity']['high']}, {item['general']['temperature']['low']}, {item['general']['temperature']['high']}, {item['general']['wind']['speed']['low']}, {item['general']['wind']['speed']['high']}, {item['general']['wind']['direction']}", f"export_mss/{date}/24hrforecast_general_{date}.csv", count)
                    for period in item['periods']:
                        count = outputCSV(f"{item['update_timestamp']}, {item['timestamp']}, {item['valid_period']['start']}, {item['valid_period']['end']}, {period['time']['start']}, {period['time']['end']}, {period['regions']['west']}, {period['regions']['east']}, {period['regions']['central']}, {period['regions']['south']}, {period['regions']['north']}", f"export_mss/{date}/24hrforecast_periods_{date}.csv", count)
                if count == 0:
                    logging(f"=======================================")
                    logging(f"MSS 24Hr Forecast: Exported {date}")
                    logging(f"=======================================")
                
def getAirTemp(API, date = None, datetime = None):
    if date is not None:
        resp = API.getMSSAirTemp(date = date)
        resp = handleResp(resp)
        if 'metadata' in resp and 'api_info' in resp:
            if resp['api_info']['status'] == 'healthy':

                # Export stations to JSON
                count = 0
                for stns in resp['metadata']['stations']:
                    count = outputCSV(f"{stns['id']}, {stns['device_id']},{stns['name']},{stns['location']['latitude']},{stns['location']['longitude']}", f"export_mss/{date}/airtemp_stations_{date}.csv", count)
                if count == 0:
                    logging(f"=======================================")
                    logging(f"MSS Air Temp Stations: Exported {date}")
                    logging(f"=======================================")

                #   Export readings to JSON
                count = 0
                for stns in resp['items']:
                    for reading in stns['readings']:
                        count = outputCSV(f"{stns['timestamp']},{reading['station_id']},{reading['value']}", f"export_mss/{date}/airtemp_readings_{date}.csv", count)
                if count == 0:
                    logging(f"=======================================")
                    logging(f"MSS Air Temp Readings: Exported {date}")
                    logging(f"=======================================")

def getRelHumidity(API, date = None, datetime = None):
    if date is not None:
        resp = API.getMSSRelHumidity(date = date)
        resp = handleResp(resp)
        if 'metadata' in resp and 'api_info' in resp:
            if resp['api_info']['status'] == 'healthy':

                # Export stations to JSON
                count = 0
                for stns in resp['metadata']['stations']:
                    count = outputCSV(f"{stns['id']}, {stns['device_id']},{stns['name']},{stns['location']['latitude']},{stns['location']['longitude']}", f"export_mss/{date}/rh_stations_{date}.csv", count)
                if count == 0:
                    logging(f"=======================================")
                    logging(f"MSS Rel Humidity Stations: Exported {date}")
                    logging(f"=======================================")

                #   Export readings to JSON
                count = 0
                for stns in resp['items']:
                    for reading in stns['readings']:
                        count = outputCSV(f"{stns['timestamp']},{reading['station_id']},{reading['value']}", f"export_mss/{date}/rh_readings_{date}.csv", count)
                if count == 0:
                    logging(f"=======================================")
                    logging(f"MSS Rel Humidity Readings: Exported {date}")
                    logging(f"=======================================")


def getMSS(date = None):
    API = API_DATAGOV_MSS()
    if date == None:
        cur_date = (dt.datetime.now() - dt.timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        cur_date = date

    if not os.path.exists(f'export_mss/{cur_date}'): 
        os.makedirs(f'export_mss/{cur_date}') 

    logging(f"***Getting MSS Data {cur_date}***")
    getRainfall(API, date = cur_date)
    getWindDir(API, date = cur_date)
    getUVIdx(API, date = cur_date)
    getPSI(API, date = cur_date)
    get24HrForecast(API, date = cur_date)
    getAirTemp(API, date = cur_date)
    getRelHumidity(API, date = cur_date)

def checkNetworkConnectivity():
    API = API_DATAGOV_MSS()

    while True:
        for LINK in API.APILST:
            if API.APICALL(LINK).status_code == 200:
                return True
        return False

def main():
    while checkNetworkConnectivity():
        logging(f"=======================================")
        logging(f"Internet Connectivity is down!")
        logging(f"=======================================")
        time.sleep(60)
        
    getMSS()

    
if __name__ == "__main__":
    main()