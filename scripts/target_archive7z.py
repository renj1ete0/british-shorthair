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

    folder_path = 'export'

    all_files = os.listdir(folder_path)
    check_files = [file for file in all_files if not file.endswith(".7z") and not file.endswith(".json")]
    current_date = dt.datetime.now().strftime("%Y-%m-%d")

    for folder_names in check_files:
        if folder_names != current_date:
        # file_path = os.path.join(folder_path, folder_names)

            if not os.path.exists(f'logs/logs_{folder_names}.json'): 
                return
            
            if not os.path.exists(f'export/{folder_names}'): 
                return

            shutil.copyfile(f'logs/logs_{folder_names}.json', f'export/{folder_names}/logs_{folder_names}.json')


            logging("Starting 7z compression")
            with py7zr.SevenZipFile(f"export/{folder_names}.7z", 'x') as archive:
                archive.writeall(f"export/{folder_names}/")
                logging("Completed 7z compression")
        
if __name__ == "__main__":
    main()