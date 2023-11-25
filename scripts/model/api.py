from dotenv import dotenv_values
import requests
import json

class API_LTA_BUS:
    def __init__(self):
        config = dotenv_values(".env") # env is in scripts folder

        self.apikey = json.loads(config["API_KEYS"])[0]

        self.URLBUSARRIVAL = "http://datamall2.mytransport.sg/ltaodataservice/BusArrivalv2"
        self.URLBUSSTOP = "http://datamall2.mytransport.sg/ltaodataservice/BusStops?$skip="

    def APICALL(self, url, header, parameters):
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
        
        header = {
        'AccountKey' : api_key,  
        'accept' : 'application/json',
        }
        
        parameters = {
            'BusStopCode' : bs_code,
            'ServiceNo': svc_no
        }
        
        response = self.APICALL(self.URLBUSARRIVAL, header, parameters)

        if response.status_code == 200:
            return response.json()
        
        return {"error": f"An error occured for {bs_code}", "status_code": response.status_code}
    

    def getBusStops(self, records):
        
        link = self.URLBUSSTOP + str(records)
        
        header = {
        'AccountKey' : self.apikey,  
        'accept' : 'application/json'
        }
        
        response = requests.get(link, headers = header)
    
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
        
if __name__ == '__main__':
    print(__package__)