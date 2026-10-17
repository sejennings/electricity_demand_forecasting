CREATE OR REPLACE VIEW gridcast.v_weather_relationships AS
SELECT region, year, month, count(*) AS paired_hours,
  avg(demand_mw) AS average_demand_mw, avg(temperature_2m) AS average_temperature_c,
  corr(demand_mw, temperature_2m) AS demand_temperature_correlation,
  avg(greatest(18.0-temperature_2m, 0.0)) AS average_heating_degree_c,
  avg(greatest(temperature_2m-18.0, 0.0)) AS average_cooling_degree_c
FROM gridcast.hourly_demand_weather
GROUP BY region, year, month
