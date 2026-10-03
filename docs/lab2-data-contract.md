## Data Contract: processed/customers

### Producer
Team / process: Glue ETL job `northstar-dev-transform` (Glue 4.0, Spark), running as role `northstar-dev-DataEngineer`. It reads the crawler-registered table `northstar_dev.customers` (source: `raw/customers/` CSV) and writes Snappy-compressed Parquet to `s3://northstar-dev-data-<account-id>/processed/customers/`.

### Consumers
- Feature engineering job `northstar-dev-feature-engineer`
- (Future) Direct model training in Lab 3

### Grain
One row per transaction. A customer appears on many rows. Duplicate `transaction_id` rows from ingestion retries are removed; nothing is aggregated to customer level in this dataset. (Reference delivery: 157,627 rows across 9,999 customers.)

### Schema
| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `transaction_id` | string | No | Natural key, format `TXN-` followed by 12 alphanumeric characters. Unique across the dataset. |
| `customer_id` | string | No | Customer key, format `CUST-` followed by 8 digits. Repeats across rows by design. Whitespace-trimmed. |
| `purchase_date` | date | No | Date of purchase, normalized to ISO 8601 (`yyyy-MM-dd`). Source rows in `MM/dd/yyyy` are converted. |
| `order_value` | double | No | Gross order value in USD. Missing source values are imputed with the column median. |
| `num_items` | int | No | Number of line items in the order. Missing source values are imputed with the rounded column median. |
| `payment_method` | string | No | One of `credit_card`, `debit_card`, `gift_card`, `cash`; `unknown` if missing in source. |
| `channel` | string | No | `store` or `online`; `unknown` if missing in source. |
| `store_id` | string | No | `STORE-` plus 3 digits for store orders, `ONLINE` for online orders; `unknown` if missing in source. |
| `product_category` | string | No | Primary category of the order (Apparel, Beauty, Electronics, Footwear, Grocery, Home, Outdoor, Toys); `unknown` if missing in source. |

### Quality Guarantees
- `customer_id` is never null and has no leading or trailing whitespace. Rows with no `customer_id` in the source are dropped (3,265 in the reference run).
- No duplicate `transaction_id` rows: `COUNT(DISTINCT transaction_id) = COUNT(*)` (a `customer_id` repeating across rows is expected, not a defect). The reference run removed 2,363 duplicate transactions.
- `purchase_date` is a valid ISO 8601 date in every row (0 nulls), and falls between 2025-04-01 and 2026-06-30 inclusive for the current data delivery.
- `order_value` is non-null and within 15.00 to 620.00 in the reference delivery; contract bound: greater than 0 and at most 1,000.00.
- `num_items` is a non-null integer within 1 to 9 in the reference delivery; contract bound: at least 1 and at most 20.
- No nulls in any column. Missing numeric values are imputed with the median and missing string values with the literal `unknown`.
- `channel` is in {`store`, `online`, `unknown`} and `payment_method` is in {`credit_card`, `debit_card`, `gift_card`, `cash`, `unknown`}.
- Row grain is preserved: the dataset has many rows per customer (reference run: about 15.8 rows per customer on average).

Known limitation: imputed values are not flagged. A consumer cannot distinguish a median-imputed `order_value` from a real one, and `unknown` categories are a placeholder, not a real category. Feature computations that count categories must exclude `unknown`.

These guarantees are enforced at the producer: the transform job asserts zero null `customer_id`, zero duplicate `transaction_id`, and zero null `purchase_date` before writing, and fails the run otherwise.

### SLA
- Data is available in `processed/customers/` within 2 hours of landing in `raw/customers/`.
- Refresh model: the job rewrites the whole prefix on each run (overwrite mode), so consumers always read a complete, consistent snapshot. Re-running the job on unchanged input produces identical output.

### Versioning
- Schema changes require a new S3 prefix (e.g., `processed/customers/v2/`)
- Breaking changes require consumer notification 5 business days in advance
- A change is breaking if it removes or renames a column, changes a column's type, changes the grain, or widens a quality bound that a consumer relies on. Adding a nullable column is non-breaking and still requires a changelog entry.
