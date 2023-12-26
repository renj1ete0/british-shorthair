import py7zr
import datetime as dt
import os
import shutil

if not os.path.exists("logs"): 
    os.makedirs("logs") 

def logging(msg):
    print(msg)
    with open(f'logs/7z_export.json', "a") as f:
        f.write(f'{dt.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")}: {msg}\n')
        
def main():

    date_formatted = dt.datetime.now().strftime("%Y-%m-%d")

    if not os.path.exists(f'logs/{date_formatted}.json'): 
        return
    
    if not os.path.exists(f'export/{date_formatted}'): 
        return

    shutil.copyfile('logs/{date_formatted}.json', 'export/{date_formatted}/logs_{date_formatted}.json')

    zip_var = True
    while zip_var:
        logging("Starting 7z compression")
        with py7zr.SevenZipFile("export/{date_formatted}.7z", 'w') as archive:
            archive.writeall("export/{date_formatted}/")
        logging("Completed 7z compression")
        if py7zr.SevenZipFile("export/{date_formatted}.7z", mode='r').test():
            logging("7z compression test success")
            zip_var = False
            os.remove("export/{date_formatted}")
            logging("Deleted export/{date_formatted}")
        else:
            os.remove("export/{date_formatted}.7z")
            logging("7z compression test failure, restarting...")

    
if __name__ == "__main__":
    main()