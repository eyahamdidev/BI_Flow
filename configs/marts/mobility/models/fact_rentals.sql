-- One row per day. Decodes the UCI codes into readable labels and de-normalises the weather measures
-- (UCI codebook: temp = C / 41, hum = % / 100, windspeed = km/h / 67).
select
    instant                         as day_id,
    dteday::date                    as rental_date,
    case season when 1 then 'winter' when 2 then 'spring' when 3 then 'summer' when 4 then 'fall' else 'unknown' end as season,
    case weathersit when 1 then 'clear' when 2 then 'mist/cloudy' when 3 then 'light rain/snow' when 4 then 'heavy rain/snow'
         else 'unknown' end         as weather,
    workingday = 1                  as is_working_day,
    holiday = 1                     as is_holiday,
    round(temp * 41, 2)             as temperature_c,
    round(hum * 100, 1)             as humidity_pct,
    round(windspeed * 67, 1)        as wind_kmh,
    rentals
from {{ ref('stg_rentals') }}
