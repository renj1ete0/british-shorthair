from model.api import API_DATAMALL
from common import *

def logging(msg):
    print(msg)
    with open(f'logs/logs_{dt.datetime.now().strftime("%Y-%m-%d")}.json', "a") as f:
        f.write(f'{dt.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")}: {msg}\n')



def PVODTrain(datetime):
    DATAMALL_API = API_DATAMALL()
    resp = DATAMALL_API.getPVODTrain(datetime)

    try:
        if resp.status_code == 200:
            resp_link = resp.json()['value'][0]['Link']

            data = requests.get(resp_link)
            filename = f'export/PV_OD_TRAIN_{datetime}'
            open(filename + ".zip", "wb").write(data.content)            
            logging(f"PV_OD_TRAIN {datetime} success")

            return True
    except:
        logging(f"Error obtaining API data: PV_OD_TRAIN {datetime}")    
    

    return False

def PVODBus(datetime):
    DATAMALL_API = API_DATAMALL()
    resp = DATAMALL_API.getPVODBus(datetime)

    try:
        if resp.status_code == 200:
            resp_link = resp.json()['value'][0]['Link']

            data = requests.get(resp_link)
            filename = f'export/PV_OD_BUSSTOPS_{datetime}'
            open(filename + ".zip", "wb").write(data.content)            
            logging(f"PV_OD_BUSSTOPS {datetime} success")

            return True
    except:
        logging(f"Error obtaining API data: PV_OD_BUSSTOPS {datetime}")    

    return False

def PVBus(datetime):
    DATAMALL_API = API_DATAMALL()
    resp = DATAMALL_API.getPVBus(datetime)

    try:
        if resp.status_code == 200:
            resp_link = resp.json()['value'][0]['Link']

            data = requests.get(resp_link)
            filename = f'export/PV_BUSSTOPS_{datetime}'
            open(filename + ".zip", "wb").write(data.content)            
            logging(f"PV_BUSSTOPS {datetime} success")

            return True
    except:
        logging(f"Error obtaining API data: PV_BUSSTOPS {datetime}")    

    return False

def PVTrain(datetime):
    DATAMALL_API = API_DATAMALL()
    resp = DATAMALL_API.getPVTrain(datetime)

    try:
        if resp.status_code == 200:
            resp_link = resp.json()['value'][0]['Link']

            data = requests.get(resp_link)
            filename = f'export/PV_TRAINSTNS_{datetime}'
            open(filename + ".zip", "wb").write(data.content)            
            logging(f"PV_TRAINSTNS {datetime} success")

            return True
    except:
        logging(f"Error obtaining API data: PV_TRAINSTNS {datetime}")    

    return False

def PVODTrain(datetime):
    DATAMALL_API = API_DATAMALL()
    resp = DATAMALL_API.getPVODTrain(datetime)
    print(resp)

    try:
        if resp.status_code == 200:
            resp_link = resp.json()['value'][0]['Link']

            data = requests.get(resp_link)
            filename = f'export/PV_OD_TRAIN_{datetime}'
            open(filename + ".zip", "wb").write(data.content)            
            logging(f"PV_OD_TRAIN {datetime} success")

            return True
    except:
        logging(f"Error obtaining API data: PV_OD_TRAIN {datetime}")    
    

    return False

def PVODTrain(datetime):
    DATAMALL_API = API_DATAMALL()
    resp = DATAMALL_API.getPVODTrain(datetime)
    print(resp)

    try:
        if resp.status_code == 200:
            resp_link = resp.json()['value'][0]['Link']

            data = requests.get(resp_link)
            filename = f'export/PV_OD_TRAIN_{datetime}'
            open(filename + ".zip", "wb").write(data.content)            
            logging(f"PV_OD_TRAIN {datetime} success")

            return True
    except:
        logging(f"Error obtaining API data: PV_OD_TRAIN {datetime}")    
    

    return False

def main(datetime = None):
    
    year = dt.datetime.now().year
    month = dt.datetime.now().month 

    if month == 1:
        year = year - 1
        month = 12
    else:
        month = month - 1

    if len(str(month)) == 1:
        month = "0" + str(month)
        
    if datetime is None:
        datetime = str(year) + str(month)

    PVODTrain(datetime)
    PVODBus(datetime)
    PVBus(datetime)
    PVTrain(datetime)

if __name__ == "__main__":
    main()