SELECT count(*) AS row_count, count(DISTINCT timestamp_utc) AS distinct_hours,
  count_if(demand_mw IS NULL OR temperature_2m IS NULL) AS critical_nulls,
  min(timestamp_utc) AS first_hour, max(timestamp_utc) AS last_hour
FROM gridcast.hourly_demand_weather
WHERE region='DUK' AND year BETWEEN '2021' AND '2025'
