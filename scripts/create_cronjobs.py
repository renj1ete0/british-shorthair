from crontab import CronTab
from dotenv import dotenv_values

config = dotenv_values(".env")  

allcronjobs = CronTab(user=config["USER"])
allcronjobs.remove_all() # Assuming server is only for this project

# Bus Stop Essentials CRON - Bus Svc, Bus Stops, Bus Route JSON (Run at 3am daily)
job = allcronjobs.new(command= 'cd ~/british-shorthair/scripts/ && python3 target_BSEssentials.py', comment='BS_Essentials_reboot')
job.every_reboot()
job.run()   
allcronjobs.write()

# Bus Stop Essentials CRON - Bus Svc, Bus Stops, Bus Route JSON (Run at 3am daily)
job = allcronjobs.new(command= 'cd ~/british-shorthair/scripts/ && python3 target_BSEssentials.py', comment='BS_Essentials_sched')
job.setall("0 4 * * *")
allcronjobs.write()

# Bus Stop Arrival CRON - Bus Arrival JSON (Run every 1min)
job = allcronjobs.new(command='cd ~/british-shorthair/scripts/ && python3 target_BSArrival.py', comment='BS_Arrival')
job.minute.every(1)
allcronjobs.write()

# DataMall Passenger Volume (Run every 16th of each month)
job = allcronjobs.new(command='cd ~/british-shorthair/scripts/ && python3 target_datamall_pv.py', comment='DataMall_PV')
job.setall("0 0 16 * *")
allcronjobs.write()

# 7z Archival CRON - 7z Archive JSON (Run at 4am daily)
job = allcronjobs.new(command= 'cd ~/british-shorthair/scripts/ && chmod +x target_7zarchive.sh && ./target_7zarchive.sh', comment='BS_7z_Archive')
job.setall("0 3 * * *")
allcronjobs.write()

# Start ngrok forwarding on startup
job = allcronjobs.new(command= 'cd ~/british-shorthair/scripts/ && chmod +x start_ngrok.sh && ./start_ngrok.sh', comment='ngrok_ssh')
job.every_reboot()
job.run()   
allcronjobs.write()