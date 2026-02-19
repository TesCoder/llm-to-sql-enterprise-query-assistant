# Database schema (`enterprise.db`)

This project uses a local **SQLite** database stored at `enterprise.db` (repo root), loaded from `data/train.csv` (Superstore) by `data/load_data.py`.

For dataset context and basic stats, see `data/DATASET.md`.

## Tables

### `orders`
One row per order (`order_id`).

| column | type | notes |
|---|---|---|
| `order_id` | `TEXT` | **Primary key**. Example: `CA-2017-152156` |
| `order_date` | `TEXT` | ISO date string (`YYYY-MM-DD`) |
| `ship_date` | `TEXT` | ISO date string (`YYYY-MM-DD`) |
| `ship_mode` | `TEXT` | Example: `Second Class` |
| `customer_id` | `TEXT` | Example: `CG-12520` |
| `customer_name` | `TEXT` | Example: `Claire Gute` |
| `segment` | `TEXT` | Example: `Consumer` |
| `country` | `TEXT` | Example: `United States` |
| `city` | `TEXT` |  |
| `state` | `TEXT` |  |
| `postal_code` | `TEXT` | Stored as text to preserve leading zeros |
| `region` | `TEXT` | Example: `South` |

**Indexes**
- `idx_orders_state` on `orders(state)`
- `idx_orders_order_date` on `orders(order_date)`

### `order_items`
One row per line item (identified by `row_id` from the CSV).

| column | type | notes |
|---|---|---|
| `row_id` | `INTEGER` | **Primary key** |
| `order_id` | `TEXT` | **Foreign key** → `orders(order_id)` (`ON DELETE CASCADE`) |
| `product_id` | `TEXT` | Example: `FUR-BO-10001798` |
| `category` | `TEXT` | Example: `Furniture` |
| `sub_category` | `TEXT` | Example: `Bookcases` |
| `product_name` | `TEXT` |  |
| `sales` | `REAL` | Sales amount |

**Indexes**
- `idx_items_category` on `order_items(category)`
- `idx_items_sub_category` on `order_items(sub_category)`

## Relationship summary
- `orders` 1 → N `order_items` (join on `order_id`)

## Quick query examples

```sql
SELECT COUNT(*) AS orders_count FROM orders;
```

```sql
SELECT region, SUM(oi.sales) AS total_sales
FROM order_items oi
JOIN orders o ON o.order_id = oi.order_id
GROUP BY region
ORDER BY total_sales DESC;
```

