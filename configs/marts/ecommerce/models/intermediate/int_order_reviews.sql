-- One row per order. Some Olist orders have several reviews: keep the most recently answered one
-- (ties broken by review_id -> deterministic) and count how many there were.
select order_id, review_id, review_score, n_reviews
from (
    select
        order_id, review_id, review_score,
        count(*) over (partition by order_id) as n_reviews,
        row_number() over (
            partition by order_id
            order by review_answer_timestamp desc nulls last, review_id
        ) as rn
    from {{ ref('stg_order_reviews') }}
)
where rn = 1
