-- =====================================================================
-- RevOps Platform V16.0 Enterprise ClickHouse DDL
-- Решение проблемы лимита 10k строк Google Sheets: Cold Storage & Data Marts
-- =====================================================================

CREATE DATABASE IF NOT EXISTS revops_dwh;

-- 1. Реестр тенантов и клиентов платформы
CREATE TABLE IF NOT EXISTS revops_dwh.tenants (
    tenant_id String,
    tenant_name String,
    client_email String,
    spreadsheet_id String,
    deployment_mode LowCardinality(String) DEFAULT 'cloud_sheets',
    created_at DateTime DEFAULT now(),
    is_active UInt8 DEFAULT 1
) ENGINE = ReplacingMergeTree()
ORDER BY (tenant_id);

-- 2. Холодное хранилище исторических сделок (raw_deals Archive)
CREATE TABLE IF NOT EXISTS revops_dwh.deals_archive (
    tenant_id LowCardinality(String),
    deal_id String,
    client_name String,
    amount Float64,
    stage_id UInt8,
    stage_name LowCardinality(String),
    created_date Date,
    closed_date Nullable(Date),
    manager_name LowCardinality(String),
    branch_name LowCardinality(String),
    is_won UInt8,
    is_lost UInt8,
    days_in_stage UInt16,
    cycle_days UInt16,
    archived_at DateTime DEFAULT now()
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(created_date)
ORDER BY (tenant_id, stage_id, created_date, deal_id);

-- 3. Атрибуция мультиканальных касаний (raw_touchpoints Archive)
CREATE TABLE IF NOT EXISTS revops_dwh.touchpoints_archive (
    tenant_id LowCardinality(String),
    touch_id String,
    deal_id String,
    client_id String,
    touch_date Date,
    channel LowCardinality(String),
    campaign_id String,
    touch_stage LowCardinality(String),
    weight_pct Float32,
    deal_amount Float64,
    attributed_won_rev Float64,
    archived_at DateTime DEFAULT now()
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(touch_date)
ORDER BY (tenant_id, channel, touch_date, touch_id);

-- 4. Неизменяемый журнал аудита безопасности (raw_audit_log)
CREATE TABLE IF NOT EXISTS revops_dwh.audit_log_archive (
    tenant_id LowCardinality(String),
    event_id String,
    timestamp DateTime,
    user_email String,
    action_type LowCardinality(String),
    resource_accessed String,
    ip_address String,
    security_verdict LowCardinality(String)
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(timestamp)
ORDER BY (tenant_id, timestamp, event_id);
