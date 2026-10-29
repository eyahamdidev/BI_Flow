-- One row per customer_id (Olist creates a new customer_id per order; customer_unique_id is the person).
-- Coordinates come from geolocation by zip prefix, averaged so the join can never duplicate customers
-- even if geolocation was not de-duplicated upstream.
with geo as (
    select geolocation_zip_code_prefix, avg(geolocation_lat) as lat, avg(geolocation_lng) as lng
    from {{ ref('stg_geolocation') }}
    group by geolocation_zip_code_prefix
)
select
    c.customer_id,
    c.customer_unique_id,
    c.customer_zip_code_prefix,
    c.customer_city,
    c.customer_state,
    g.lat,
    g.lng
from {{ ref('stg_customers') }} c
left join geo g on g.geolocation_zip_code_prefix = c.customer_zip_code_prefix
