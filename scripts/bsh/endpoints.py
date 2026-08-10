"""API endpoints.

URLs verified against the LTA DataMall API User Guide v6.9 (3 Aug 2026). The guide
documents every endpoint as https; there are no plain-http URLs in it, so none appear
here either.
"""

LTA_ROOT = "https://datamall2.mytransport.sg/ltaodataservice"

# Real-time. Guide section 2.1; refreshes every 20 seconds.
BUS_ARRIVAL = f"{LTA_ROOT}/v3/BusArrival"

# Reference datasets, 500 records per page via $skip. Sections 2.2-2.4.
BUS_SERVICES = f"{LTA_ROOT}/BusServices"
BUS_ROUTES = f"{LTA_ROOT}/BusRoutes"
BUS_STOPS = f"{LTA_ROOT}/BusStops"

# Section 2.27. Ad hoc updates; data appears only on/after its EffectiveDate.
PLANNED_BUS_ROUTES = f"{LTA_ROOT}/PlannedBusRoutes"

# --- Real-time feeds (sections 2.11, 2.12, 2.24, 2.25, 2.29, 2.32, 2.33) ---
#
# None of these accept a date parameter: they report "now" and keep no history, so
# unlike the NEA datasets a missed poll is lost permanently. That is why they are
# polled at their stated update frequency and appended to hourly NDJSON, rather than
# collected nightly.

CARPARK_AVAILABILITY = f"{LTA_ROOT}/CarParkAvailabilityv2"   # 1 minute, paginated
TRAIN_SERVICE_ALERTS = f"{LTA_ROOT}/TrainServiceAlerts"      # ad hoc
PCD_REALTIME = f"{LTA_ROOT}/PCDRealTime"                     # 10 minutes, per line
PCD_FORECAST = f"{LTA_ROOT}/PCDForecast"                     # 24 hours, per line

# These return a short-lived download link rather than the data itself.
EVC_BATCH = f"{LTA_ROOT}/EVCBatch"                           # 5 minutes, JSON file
GTFS_TRAIN_TRIP_UPDATES = f"{LTA_ROOT}/GTFSRealtimeTrainTripUpdates"  # ad hoc, protobuf
GTFS_SCHEDULE_TRAIN = f"{LTA_ROOT}/GTFSScheduleTrain"        # static feed, zip

# Not collected: GTFSRealTimeTrainServiceAlerts reports the same disruptions as
# TRAIN_SERVICE_ALERTS above, but as protobuf and without LTA's free-bus/shuttle
# fields. Add it here if standards-compatible alert output is ever needed.
GTFS_TRAIN_ALERTS = f"{LTA_ROOT}/GTFSRealTimeTrainServiceAlerts"

# Train lines accepted by PCDRealTime and PCDForecast (guide sections 2.24/2.25).
TRAIN_LINES = (
    "CCL", "CEL", "CGL", "DTL", "EWL", "NEL", "NSL", "BPL", "SLRT", "PLRT", "TEL",
)

# Passenger volume, sections 2.5-2.8. Date=YYYYMM, previous month published by the
# 10th, and the returned S3 link expires 15 minutes after issue.
PV_BUS = f"{LTA_ROOT}/PV/Bus"
PV_OD_BUS = f"{LTA_ROOT}/PV/ODBus"
PV_TRAIN = f"{LTA_ROOT}/PV/Train"
PV_OD_TRAIN = f"{LTA_ROOT}/PV/ODTrain"

PV_DATASETS = {
    "PV_BUSSTOPS": PV_BUS,
    "PV_OD_BUSSTOPS": PV_OD_BUS,
    "PV_TRAINSTNS": PV_TRAIN,
    "PV_OD_TRAIN": PV_OD_TRAIN,
}

# data.gov.sg real-time environment APIs (no key required).
#
# NEA publishes 13 real-time services. The 11 below are openly reachable; Lightning
# and WBGT return HTTP 403 on both the v1 and v2 endpoints (checked 2026-08-09) and
# would need authorised access, so they are not collected.
#
# v1 is used rather than v2 (api-open.data.gov.sg/v2/real-time/api/...) because v1
# serves a full past day for ?date=YYYY-MM-DD, which is what allows nightly batch
# collection and retrospective gap-filling. v2 also rate-limits noticeably harder.
MSS_ROOT = "https://api.data.gov.sg/v1/environment"

MSS_DATASETS = {
    "rainfall": f"{MSS_ROOT}/rainfall",
    "winddir": f"{MSS_ROOT}/wind-direction",
    # Wind speed completes NEA's five station-based weather datasets (air temperature,
    # rainfall, relative humidity, wind direction, wind speed). It was absent from the
    # original collector, so there is no history for it before 2026-08-09.
    "windspeed": f"{MSS_ROOT}/wind-speed",
    "uvidx": f"{MSS_ROOT}/uv-index",
    "psi": f"{MSS_ROOT}/psi",
    "pm25": f"{MSS_ROOT}/pm25",
    "24hrforecast": f"{MSS_ROOT}/24-hour-weather-forecast",
    "2hrforecast": f"{MSS_ROOT}/2-hour-weather-forecast",
    "4dayoutlook": f"{MSS_ROOT}/4-day-weather-forecast",
    "airtemp": f"{MSS_ROOT}/air-temperature",
    "rh": f"{MSS_ROOT}/relative-humidity",
}

# Published by NEA but not reachable without authorisation (HTTP 403 on v1 and v2).
UNAVAILABLE_MSS_DATASETS = {
    "lightning": f"{MSS_ROOT}/lightning",
    "wbgt": f"{MSS_ROOT}/wbgt",
}
