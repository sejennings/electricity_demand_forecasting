CREATE OR REPLACE VIEW gridcast.v_hourly_features AS
SELECT f.*, r.region_name, r.local_timezone, c.day_of_week AS iso_day_of_week,
  c.is_weekend, hour(f.timestamp_utc) AS hour_utc
FROM gridcast.hourly_demand_weather f
JOIN gridcast.dim_region r ON r.region=f.region
JOIN gridcast.dim_calendar c ON c.calendar_date=CAST(f.timestamp_utc AS date)
