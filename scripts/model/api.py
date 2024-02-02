from dotenv import dotenv_values
import requests
import json

class API_LTA_BUS:
    def __init__(self):
        config = dotenv_values(".env") # env is in scripts folder

        self.apikey = json.loads(config["API_KEYS"])[0]

        self.URLBUSARRIVAL = "http://datamall2.mytransport.sg/ltaodataservice/BusArrivalv2"
        self.URLBUSSTOP = "http://datamall2.mytransport.sg/ltaodataservice/BusStops?$skip="
        self.URLBUSROUTES = "http://datamall2.mytransport.sg/ltaodataservice/BusRoutes?$skip="
        self.URLBUSSERVICES = "http://datamall2.mytransport.sg/ltaodataservice/BusServices?$skip="

    def APICALL(self, url, header, parameters = {}):
        response = None
        try:
            response = requests.get(url, headers = header, params = parameters)
        except:
            if response is not None:
                return {"error": "An error occured", "error_resp_obj": response, "status_code": response.status_code}
            else:
                return {"error": "An error occured", "status_code": 0}
        return response

    def getBusStopTiming(self, bs_code, api_key, svc_no = ""):
        rejected = True
        tries = 0
        header = {
        'AccountKey' : api_key,  
        'accept' : 'application/json',
        }
        
        parameters = {
            'BusStopCode' : bs_code,
            'ServiceNo': svc_no
        }
        
        response = self.APICALL(self.URLBUSARRIVAL, header, parameters)

        if hasattr(response, "status_code"):
            if response.status_code == 200:
                rejected = False
                return response.json()

        while tries < 2 and rejected:
            tries += 1
            response = self.APICALL(self.URLBUSARRIVAL, header, parameters)
            if hasattr(response, "status_code"):
                if response.status_code == 200:
                    rejected = False
                    return response.json()

        
        if response is None:
            return {"error": f"An error occured for {bs_code}", "status_code": response.status_code}
        else:
            return response
    

    def getBusStops(self, records):
        
        link = self.URLBUSSTOP + str(records)
        
        header = {
        'AccountKey' : self.apikey,  
        'accept' : 'application/json'
        }
        
        response = self.APICALL(link, header)
    
        return response


    def getAllBusStops(self):

        all_busstop = []
        not_complete = True
        record = 0

        while(not_complete):
            
            ret_busstop = self.getBusStops(record)

            try:
                json_response = ret_busstop.json()
                json_dict = json_response['value']

                if len(json_dict) > 0:
                    all_busstop += json_dict
                else:
                    not_complete = False
            except:
                not_complete = False
            
            record += 500

        return all_busstop
    
    def getBusRoutes(self, records):
        
        link = self.URLBUSROUTES + str(records)
        
        header = {
        'AccountKey' : self.apikey,  
        'accept' : 'application/json'
        }

        response = self.APICALL(link, header)

        return response

    
    def getAllBusRoute(self):
            
        all_busstop = []
        not_complete = True
        record = 0

        while(not_complete):
            
            ret_busstop = self.getBusRoutes(record)

            try:
                json_response = ret_busstop.json()
                json_dict = json_response['value']

                if len(json_dict) > 0:
                    all_busstop += json_dict
                else:
                    not_complete = False
            except:
                not_complete = False
            
            record += 500

        return all_busstop

    def getBusService(self, records):
        
        link = self.URLBUSSERVICES + str(records)
        
        header = {
        'AccountKey' : self.apikey,  
        'accept' : 'application/json'
        }
        
        response = self.APICALL(link, header)

        return response

    
    def getAllBusService(self):
            
        all_busstop = []
        not_complete = True
        record = 0

        while(not_complete):
            
            ret_busstop = self.getBusService(record)

            try:
                json_response = ret_busstop.json()
                json_dict = json_response['value']

                if len(json_dict) > 0:
                    all_busstop += json_dict
                else:
                    not_complete = False
            except:
                not_complete = False
            
            record += 500

        return all_busstop
    
class API_LTA_OTHERS:

    def __init__(self):
        config = dotenv_values(".env") # env is in scripts folder

        self.apikey = json.loads(config["API_KEYS"])[1]

        self.URLCARPARK = "http://datamall2.mytransport.sg/ltaodataservice/CarParkAvailabilityv2"

    def getLTACarpark(self):
        header = {
        'AccountKey' : self.api_key,  
        'accept' : 'application/json',
        }

        response = self.APICALL(self.URLCARPARK, header)

class API_URA:
    def __init__(self):
        config = dotenv_values(".env") # env is in scripts folder

        self.apikey = json.loads(config["API_KEYS"])[1]

        self.URLCARPARK = "http://datamall2.mytransport.sg/ltaodataservice/CarParkAvailabilityv2"

    def APICALL(self, url, header, parameters = {}):
        response = None
        try:
            response = requests.get(url, headers = header, params = parameters)
        except:
            if response is not None:
                return {"error": "An error occured", "error_resp_obj": response, "status_code": response.status_code}
            else:
                return {"error": "An error occured", "status_code": 0}
        return response


class API_DATAMALL:
    def __init__(self):
        config = dotenv_values(".env") # env is in scripts folder

        self.apikey = json.loads(config["API_KEYS"])[1]

        # self.URLCARPARK = "https://api.data.gov.sg/v1/transport/carpark-availability"
        self.URLPVODTRAIN = "http://datamall2.mytransport.sg/ltaodataservice/PV/ODTrain"
        self.URLPVTRAINSTN = "http://datamall2.mytransport.sg/ltaodataservice/PV/Train"
        self.URLPVODBUSSTOPS = "http://datamall2.mytransport.sg/ltaodataservice/PV/ODBus"
        self.URLPVBUSSTOPS = "http://datamall2.mytransport.sg/ltaodataservice/PV/Bus"

    def APICALL(self, url, header, parameters = {}):
        response = None
        try:
            response = requests.get(url, headers = header, params = parameters)
        except:
            if response is not None:
                return {"error": "An error occured", "error_resp_obj": response, "status_code": response.status_code}
            else:
                return {"error": "An error occured", "status_code": 0}
        return response
    
    def getPVODTrain(self, datetime):
        header = {
        'AccountKey' : self.apikey,  
        'accept' : 'application/json',
        }
        
        parameters = {
            'Date' : datetime #YYYYMM format
        }

        resp = self.APICALL(self.URLPVODTRAIN, header, parameters)

        return resp

    def getPVODBus(self, datetime):
        header = {
        'AccountKey' : self.apikey,  
        'accept' : 'application/json',
        }
        
        parameters = {
            'Date' : datetime #YYYYMM format
        }

        resp = self.APICALL(self.URLPVODBUSSTOPS, header, parameters)

        return resp
    
    def getPVBus(self, datetime):
        header = {
        'AccountKey' : self.apikey,  
        'accept' : 'application/json',
        }
        
        parameters = {
            'Date' : datetime #YYYYMM format
        }

        resp = self.APICALL(self.URLPVBUSSTOPS, header, parameters)

        return resp

    def getPVTrain(self, datetime):
        header = {
        'AccountKey' : self.apikey,  
        'accept' : 'application/json',
        }
        
        parameters = {
            'Date' : datetime #YYYYMM format
        }

        resp = self.APICALL(self.URLPVTRAINSTN, header, parameters)

        return resp

class API_DATAGOVSG:
    def __init__(self):
        config = dotenv_values(".env") # env is in scripts folder

        self.apikey = json.loads(config["API_KEYS"])[1]

        self.weatherRainfall = "https://api.data.gov.sg/v1/environment/rainfall"
        self.weatherWindDirection = "https://api.data.gov.sg/v1/environment/wind-direction"
        self.weatherUVIndex = "https://api.data.gov.sg/v1/environment/uv-index"
        self.weatherUVIndex = "https://api.data.gov.sg/v1/environment/psi"
        self.weather24WeatherForecast = "https://api.data.gov.sg/v1/environment/24-hour-weather-forecast"
        self.weatherAirTemperature = "https://api.data.gov.sg/v1/environment/air-temperature"
        self.weatherRelHumidity = "https://api.data.gov.sg/v1/environment/relative-humidity"

    def APICALL(self, url, header, parameters = {}):
        response = None
        try:
            response = requests.get(url, headers = header, params = parameters)
        except:
            if response is not None:
                return {"error": "An error occured", "error_resp_obj": response, "status_code": response.status_code}
            else:
                return {"error": "An error occured", "status_code": 0}
        return response





        
if __name__ == '__main__':
    print(__package__)