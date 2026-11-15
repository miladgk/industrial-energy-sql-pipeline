-- =============================================================
-- 10_partition_readings.sql
-- Create partitioned version of readings table
-- =============================================================

-- The whole file is skipped once `readings` is itself partitioned (i.e. after
-- migrate_to_partitioned.py has swapped the tables). Without this guard, a
-- repeated `setup_db.py` would create a stray, partition-less readings_partitioned.
DO $partition_setup$
BEGIN
IF NOT EXISTS (SELECT 1 FROM pg_class
               WHERE relname = 'readings' AND relkind = 'p'
                 AND relnamespace = 'public'::regnamespace) THEN

CREATE TABLE IF NOT EXISTS readings_partitioned (
    reading_id   BIGSERIAL,
    sensor_id    INT          NOT NULL,
    recorded_at  TIMESTAMPTZ  NOT NULL,
    value        NUMERIC(10,4),
    is_anomaly   BOOLEAN      DEFAULT FALSE,
    PRIMARY KEY (reading_id, recorded_at),
    FOREIGN KEY (sensor_id) REFERENCES sensors(sensor_id)
) PARTITION BY RANGE (recorded_at);

-- Create 12 monthly partitions for 2025 (the synthetic data year), plus January 2026
-- for incremental loads (generate_data.py --incremental defaults to 2026-01-01)
CREATE TABLE IF NOT EXISTS readings_2025_01 PARTITION OF readings_partitioned
    FOR VALUES FROM ('2025-01-01 00:00:00+00') TO ('2025-02-01 00:00:00+00');
CREATE TABLE IF NOT EXISTS readings_2025_02 PARTITION OF readings_partitioned
    FOR VALUES FROM ('2025-02-01 00:00:00+00') TO ('2025-03-01 00:00:00+00');
CREATE TABLE IF NOT EXISTS readings_2025_03 PARTITION OF readings_partitioned
    FOR VALUES FROM ('2025-03-01 00:00:00+00') TO ('2025-04-01 00:00:00+00');
CREATE TABLE IF NOT EXISTS readings_2025_04 PARTITION OF readings_partitioned
    FOR VALUES FROM ('2025-04-01 00:00:00+00') TO ('2025-05-01 00:00:00+00');
CREATE TABLE IF NOT EXISTS readings_2025_05 PARTITION OF readings_partitioned
    FOR VALUES FROM ('2025-05-01 00:00:00+00') TO ('2025-06-01 00:00:00+00');
CREATE TABLE IF NOT EXISTS readings_2025_06 PARTITION OF readings_partitioned
    FOR VALUES FROM ('2025-06-01 00:00:00+00') TO ('2025-07-01 00:00:00+00');
CREATE TABLE IF NOT EXISTS readings_2025_07 PARTITION OF readings_partitioned
    FOR VALUES FROM ('2025-07-01 00:00:00+00') TO ('2025-08-01 00:00:00+00');
CREATE TABLE IF NOT EXISTS readings_2025_08 PARTITION OF readings_partitioned
    FOR VALUES FROM ('2025-08-01 00:00:00+00') TO ('2025-09-01 00:00:00+00');
CREATE TABLE IF NOT EXISTS readings_2025_09 PARTITION OF readings_partitioned
    FOR VALUES FROM ('2025-09-01 00:00:00+00') TO ('2025-10-01 00:00:00+00');
CREATE TABLE IF NOT EXISTS readings_2025_10 PARTITION OF readings_partitioned
    FOR VALUES FROM ('2025-10-01 00:00:00+00') TO ('2025-11-01 00:00:00+00');
CREATE TABLE IF NOT EXISTS readings_2025_11 PARTITION OF readings_partitioned
    FOR VALUES FROM ('2025-11-01 00:00:00+00') TO ('2025-12-01 00:00:00+00');
CREATE TABLE IF NOT EXISTS readings_2025_12 PARTITION OF readings_partitioned
    FOR VALUES FROM ('2025-12-01 00:00:00+00') TO ('2026-01-01 00:00:00+00');
CREATE TABLE IF NOT EXISTS readings_2026_01 PARTITION OF readings_partitioned
    FOR VALUES FROM ('2026-01-01 00:00:00+00') TO ('2026-02-01 00:00:00+00');

-- Recreate the composite index on the parent table
CREATE INDEX IF NOT EXISTS idx_readings_part_sensor_time ON readings_partitioned(sensor_id, recorded_at);

END IF;
END
$partition_setup$;
