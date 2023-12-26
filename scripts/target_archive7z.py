import py7zr
import datetime as dt
from datetime import timedelta
import os
import shutil

if not os.path.exists("logs"): 
    os.makedirs("logs") 

def logging(msg):
    print(msg)
    with open(f'logs/7z_export.json', "a") as f:
        f.write(f'{dt.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")}: {msg}\n')
        
def main():

    previous_date = dt.datetime.now() - timedelta(days = 1)

    date_formatted = previous_date.strftime("%Y-%m-%d")

    if not os.path.exists(f'logs/logs_{date_formatted}.json'): 
        return
    
    if not os.path.exists(f'export/{date_formatted}'): 
        return

    shutil.copyfile(f'logs/logs_{date_formatted}.json', f'export/{date_formatted}/logs_{date_formatted}.json')

    zip_var = True
    while zip_var:
        logging("Starting 7z compression")
        with py7zr.SevenZipFile(f"export/{date_formatted}.7z", 'w') as archive:
            archive.writeall(f"export/{date_formatted}/")
        logging("Completed 7z compression")
        if py7zr.SevenZipFile(f"export/{date_formatted}.7z", mode='r').test():
            logging("7z compression test success")
            zip_var = False
            os.remove(f"export/{date_formatted}")
            logging("Deleted export/{date_formatted}")
        else:
            os.remove(f"export/{date_formatted}.7z")
            logging("7z compression test failure, restarting...")

    
if __name__ == "__main__":
    main()