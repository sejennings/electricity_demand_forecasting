CREATE OR REPLACE VIEW gridcast.v_data_completeness AS
WITH d AS (
  SELECT region, CAST(timestamp_utc AS date) AS observation_date,
    count(DISTINCT timestamp_utc) AS hours, count(*)-count(DISTINCT timestamp_utc) AS duplicate_hours
  FROM gridcast.hourly_demand GROUP BY region, CAST(timestamp_utc AS date)
), w AS (
  SELECT region, CAST(timestamp_utc AS date) AS observation_date,
    count(DISTINCT timestamp_utc) AS hours
  FROM gridcast.hourly_weather GROUP BY region, CAST(timestamp_utc AS date)
)
SELECT r.region, c.calendar_date, CAST(c.year_number AS varchar) AS year,
  lpad(CAST(c.month_number AS varchar),2,'0') AS month,
  24 AS expected_hours, coalesce(d.hours,0) AS demand_hours,
  coalesce(w.hours,0) AS weather_hours, 24-coalesce(d.hours,0) AS missing_demand_hours,
  24-coalesce(w.hours,0) AS missing_weather_hours,
  coalesce(d.duplicate_hours,0) AS duplicate_demand_hours
FROM gridcast.dim_calendar c CROSS JOIN gridcast.dim_region r
LEFT JOIN d ON d.region=r.region AND d.observation_date=c.calendar_date
LEFT JOIN w ON w.region=r.region AND w.observation_date=c.calendar_date
