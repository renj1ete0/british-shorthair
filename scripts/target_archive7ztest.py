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
    sevenz_files = [file for file in all_files if file.endswith(".7z")]

    for file_name in sevenz_files:
        file_path = os.path.join(folder_path, file_name)
        
        with py7zr.SevenZipFile(f"{file_path}", 'r') as archive:
            result = archive.test()
        
            if result:
                logging("7z compression test success")
                zip_var = False
                os.remove(f"export/{file_name.split('.7z')[0]}")
                logging(f"Deleted export/{file_name.split('.7z')[0]}")
            else:
                os.remove(f"{file_path}")
                logging("7z compression test failure, deleting...")

    
if __name__ == "__main__":
    main()