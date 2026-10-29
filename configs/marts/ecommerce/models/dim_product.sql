-- One row per product. product_category = English name when a translation exists, else the original
-- Portuguese name (e.g. pc_gamer has no translation), else 'unknown'.
select
    p.product_id,
    coalesce(p.product_category_name, 'unknown') as product_category_pt,
    coalesce(t.product_category_name_english, p.product_category_name, 'unknown') as product_category,
    t.product_category_name_english is null as category_untranslated,
    p.product_photos_qty,
    p.product_weight_g,
    p.product_length_cm,
    p.product_height_cm,
    p.product_width_cm
from {{ ref('stg_products') }} p
left join {{ ref('stg_category_translation') }} t using (product_category_name)
