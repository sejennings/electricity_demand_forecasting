CREATE OR REPLACE VIEW gridcast.v_seasonality AS
SELECT region, year, month, hour(timestamp_utc) AS hour_utc,
  day_of_week(timestamp_utc) AS iso_day_of_week,
  CASE WHEN month IN ('12','01','02') THEN 'winter'
       WHEN month IN ('03','04','05') THEN 'spring'
       WHEN month IN ('06','07','08') THEN 'summer' ELSE 'fall' END AS season,
  count(*) AS observed_hours, avg(demand_mw) AS average_demand_mw,
  max(demand_mw) AS maximum_demand_mw
FROM gridcast.hourly_demand
GROUP BY region, year, month, hour(timestamp_utc), day_of_week(timestamp_utc)
