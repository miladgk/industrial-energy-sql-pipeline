# Query Index Benchmark

This document records the query performance of the `readings` table with a single-column index, with the composite index `idx_readings_sensor_time (sensor_id, recorded_at)`, and after range partitioning by month.

*(Note: the absolute timings reflect one local run on Docker (PostgreSQL 15) and will vary by hardware. Each figure is the median of 7 warm runs (9 runs, the first two discarded). The meaningful finding is the relative difference, not the absolute latency.)*

**Dataset:** the full-year synthetic dataset, `python src/generate_data.py` (seed 42, 1 Jan – 31 Dec 2025, 60 sensors every 5 minutes, 6,307,200 rows).

## Query Under Test
The query represents a typical time-range filter for a single sensor's telemetry:
```sql
SELECT * FROM readings
WHERE sensor_id = 5 AND recorded_at BETWEEN '2025-06-01' AND '2025-06-07';
```

---

## 1. Without Composite Index (Single-Column Index Only)
When only the single-column index `idx_readings_sensor` is available, PostgreSQL must scan the index for all records matching `sensor_id = 5`, retrieve the rows, and then apply a filter on `recorded_at` in memory.

### EXPLAIN ANALYZE Output
```text
 Index Scan using idx_readings_sensor on readings  (cost=0.43..3501.61 rows=1776 width=27) (actual time=4.348..12.720 rows=1729 loops=1)
   Index Cond: (sensor_id = 5)
   Filter: ((recorded_at >= '2025-06-01 00:00:00+00'::timestamp with time zone) AND (recorded_at <= '2025-06-07 00:00:00+00'::timestamp with time zone))
   Rows Removed by Filter: 103391
 Planning Time: 0.099 ms
 Execution Time: 12.777 ms
```

---

## 2. With Composite Index
With the composite index `idx_readings_sensor_time (sensor_id, recorded_at)` present, PostgreSQL performs a direct lookup matching both criteria inside the index tree itself, avoiding the overhead of loading and filtering thousands of irrelevant rows.

### EXPLAIN ANALYZE Output
```text
 Index Scan using idx_readings_sensor_time on readings  (cost=0.43..3402.32 rows=1934 width=27) (actual time=0.008..0.181 rows=1729 loops=1)
   Index Cond: ((sensor_id = 5) AND (recorded_at >= '2025-06-01 00:00:00+00'::timestamp with time zone) AND (recorded_at <= '2025-06-07 00:00:00+00'::timestamp with time zone))
 Planning Time: 0.063 ms
 Execution Time: 0.219 ms
```

---

## Summary of Results
*   **Without Composite Index:** Execution time was **12.777 ms** (reading all 105,120 index entries for sensor 5 and discarding 103,391 rows via in-memory filter).
*   **With Composite Index:** Execution time was **0.219 ms** (direct index lookup of exactly the 1,729 matching records).

**Actual Performance Difference:** The composite index reduced the query execution time from **12.777 ms** to **0.219 ms**, about **58× faster** (a **98.3%** reduction).

---

## 3. With Range Partitioning (Monthly)
`python src/migrate_to_partitioned.py` converts the table to `PARTITION BY RANGE (recorded_at)` with 12 monthly partitions for 2025 plus January 2026. The composite index is defined on the parent table and created on every partition.

For a time-bounded query, PostgreSQL uses **partition pruning**: the plan below touches only `readings_2025_06` and never opens the other 12 partitions.

### EXPLAIN ANALYZE Output
```text
 Index Scan using readings_2025_06_sensor_id_recorded_at_idx on readings_2025_06 readings  (cost=0.42..2425.56 rows=1631 width=27) (actual time=0.008..0.157 rows=1729 loops=1)
   Index Cond: ((sensor_id = 5) AND (recorded_at >= '2025-06-01 00:00:00+00'::timestamp with time zone) AND (recorded_at <= '2025-06-07 00:00:00+00'::timestamp with time zone))
 Planning Time: 0.073 ms
 Execution Time: 0.194 ms
```

**Partitioning note:** on this single-sensor lookup the partitioned table is about as fast as the indexed one (0.194 ms vs 0.219 ms); the composite index already does most of the work. Partitioning pays off in pruning for time-bounded scans and in maintenance: vacuuming, archiving or dropping a whole month at once.
