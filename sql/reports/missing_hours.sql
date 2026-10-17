SELECT * FROM gridcast.v_data_completeness
WHERE year BETWEEN '2021' AND '2025'
  AND (missing_demand_hours>0 OR missing_weather_hours>0 OR duplicate_demand_hours>0)
ORDER BY calendar_date
