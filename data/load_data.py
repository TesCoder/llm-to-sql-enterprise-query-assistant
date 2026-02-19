"""Load the Superstore dataset into a local SQLite database."""

from __future__ import annotations

import csv
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "enterprise.db"
CSV_PATH = Path(__file__).resolve().parent / "train.csv"


def parse_date(value: str) -> str:
    """Parse dates like '27/08/2015' into ISO format."""
    for fmt in ("%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"Unrecognized date format: {value}")


def create_schema(conn: sqlite3.Connection) -> None:
    """Create normalized tables for orders and order line items."""
    conn.executescript("""
        PRAGMA foreign_keys = ON;

        DROP TABLE IF EXISTS order_items;
        DROP TABLE IF EXISTS orders;

        CREATE TABLE orders (
            order_id TEXT PRIMARY KEY,
            order_date TEXT NOT NULL,
            ship_date TEXT NOT NULL,
            ship_mode TEXT,
            customer_id TEXT NOT NULL,
            customer_name TEXT NOT NULL,
            segment TEXT,
            country TEXT,
            city TEXT,
            state TEXT,
            postal_code TEXT,
            region TEXT
        );

        CREATE TABLE order_items (
            row_id INTEGER PRIMARY KEY,
            order_id TEXT NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
            product_id TEXT NOT NULL,
            category TEXT,
            sub_category TEXT,
            product_name TEXT,
            sales REAL NOT NULL
        );

        CREATE INDEX idx_orders_state ON orders(state);
        CREATE INDEX idx_orders_order_date ON orders(order_date);
        CREATE INDEX idx_items_category ON order_items(category);
        CREATE INDEX idx_items_sub_category ON order_items(sub_category);
        """)
    conn.commit()


def load_dataset(conn: sqlite3.Connection) -> Tuple[int, int]:
    """Load the CSV into the SQLite database."""
    orders: Dict[str, Tuple] = {}
    items_buffer: List[Tuple] = []

    with CSV_PATH.open(newline="", encoding="utf-8") as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            order_id = row["Order ID"]
            if order_id not in orders:
                orders[order_id] = (
                    order_id,
                    parse_date(row["Order Date"]),
                    parse_date(row["Ship Date"]),
                    row.get("Ship Mode"),
                    row["Customer ID"],
                    row["Customer Name"],
                    row.get("Segment"),
                    row.get("Country"),
                    row.get("City"),
                    row.get("State"),
                    row.get("Postal Code"),
                    row.get("Region"),
                )

            items_buffer.append(
                (
                    int(row["Row ID"]),
                    order_id,
                    row["Product ID"],
                    row.get("Category"),
                    row.get("Sub-Category"),
                    row.get("Product Name"),
                    float(row["Sales"]),
                )
            )

    with conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO orders (
                order_id, order_date, ship_date, ship_mode, customer_id,
                customer_name, segment, country, city, state, postal_code, region
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            orders.values(),
        )
        conn.executemany(
            """
            INSERT OR REPLACE INTO order_items (
                row_id, order_id, product_id, category, sub_category, product_name, sales
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            items_buffer,
        )

    return len(orders), len(items_buffer)


def main() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        create_schema(conn)
        order_count, item_count = load_dataset(conn)
        print(
            f"Loaded {order_count} orders and {item_count} order items into {DB_PATH}"
        )


if __name__ == "__main__":
    main()
