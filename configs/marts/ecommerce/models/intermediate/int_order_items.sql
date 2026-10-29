-- One row per order: item totals and the order's MAIN product category.
-- An order can mix categories; fact_orders has one product_category column, so we use the category of the
-- most expensive item (ties broken by order_item_id -> deterministic). Item-level analysis uses fact_order_items.
with items as (
    select i.order_id, i.order_item_id, i.price, i.freight_value, d.product_category
    from {{ ref('stg_order_items') }} i
    left join {{ ref('dim_product') }} d using (product_id)
),
ranked as (
    select *, row_number() over (partition by order_id order by price desc, order_item_id) as rn
    from items
)
select
    order_id,
    count(*)           as n_items,
    sum(price)         as items_value,
    sum(freight_value) as freight_value,
    max(case when rn = 1 then product_category end) as product_category
from ranked
group by order_id
