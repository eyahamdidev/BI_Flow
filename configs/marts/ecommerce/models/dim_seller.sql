-- One row per seller, with coordinates by zip prefix (averaged: the join cannot duplicate sellers).
with geo as (
    select geolocation_zip_code_prefix, avg(geolocation_lat) as lat, avg(geolocation_lng) as lng
    from {{ ref('stg_geolocation') }}
    group by geolocation_zip_code_prefix
)
select
    s.seller_id,
    s.seller_zip_code_prefix,
    s.seller_city,
    s.seller_state,
    g.lat,
    g.lng
from {{ ref('stg_sellers') }} s
left join geo g on g.geolocation_zip_code_prefix = s.seller_zip_code_prefix
