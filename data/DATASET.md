# Dataset overview (Superstore Sales)

## Source file
- `data/train.csv`

## Context (from `temp/About Dataset.txt`)
Retail dataset of a global superstore for 4 years. Common uses include EDA and time-series style analysis/forecasting.

## What’s in the data
Each row in `train.csv` represents an **order line item** (product on an order), with:
- **Order**: `Order ID`, `Order Date`, `Ship Date`, `Ship Mode`
- **Customer**: `Customer ID`, `Customer Name`, `Segment`
- **Geography**: `Country`, `City`, `State`, `Postal Code`, `Region`
- **Product**: `Product ID`, `Category`, `Sub-Category`, `Product Name`
- **Metric**: `Sales`

## Quick stats (computed from `train.csv`)
- **Rows (line items)**: 9,800
- **Unique orders**: 4,922
- **Unique customers**: 793
- **Order date range**: 2015-01-03 → 2018-12-30
- **Ship date range**: 2015-01-07 → 2019-01-05
- **Regions**: Central, East, South, West
- **Categories**: Furniture, Office Supplies, Technology
- **Sub-categories**: 17 distinct values

## How it’s stored in the local DB
The loader `data/load_data.py` imports `train.csv` into SQLite `enterprise.db` using a normalized schema:
- `orders` (one row per `order_id`)
- `order_items` (one row per `row_id`, linked to `orders.order_id`)

See `data/SCHEMA.md` for the database schema and indexes.

