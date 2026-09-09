import cdsapi

dataset = "seasonal-monthly-single-levels"
request = {
    "originating_centre": "bom",
    "system": "2",
    "variable": [
        "maximum_2m_temperature_in_the_last_24_hours",
        "minimum_2m_temperature_in_the_last_24_hours",
        "total_precipitation"
    ],
    "product_type": [
        "ensemble_mean",
	    "hindcast_climate_mean"
    ],
    "year": ["2026"],
    "month": ["08"],
    "leadtime_month": [
        "1",
        "2",
        "3",
        "4",
        "5",
        "6"
    ],
    "data_format": "netcdf",
    "area": [20, -110, -60, -20]
}

client = cdsapi.Client()
client.retrieve(dataset, request).download()
