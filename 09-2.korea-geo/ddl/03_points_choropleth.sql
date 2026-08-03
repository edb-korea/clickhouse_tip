-- ===========================================================================
-- (선택/스트레치) 포인트 → 리버스 지오코딩 → 카운트 → choropleth
-- ClickHouse 가 분류·집계, Superset 가 시각화하는 풀 파이프라인.
-- 실행: docker exec -i kg-clickhouse clickhouse-client --multiquery < ddl/03_points_choropleth.sql
-- ===========================================================================

-- 1) 한반도 bbox 안 랜덤 포인트 N개 (인구 밀집과 무관한 균등 분포 데모)
CREATE TABLE IF NOT EXISTS geospatial.points
(
    lon Float64,
    lat Float64
)
ENGINE = MergeTree ORDER BY (lon, lat);

INSERT INTO geospatial.points
SELECT
    124.6 + rand() / 4294967295.0 * (130.9 - 124.6) AS lon,
    33.2  + rand() / 4294967295.0 * (38.6  - 33.2)  AS lat
FROM numbers(200000);

-- 2) 딕셔너리로 각 점의 시군구 분류 후 카운트
CREATE OR REPLACE TABLE geospatial.sig_counts
ENGINE = MergeTree ORDER BY code AS
SELECT
    dictGet('geospatial.sig_dict', 'code', (lon, lat)) AS code,
    count() AS cnt
FROM geospatial.points
GROUP BY code;

-- 3) sig_map.metric 을 실제 분포(cnt)로 갱신.
--    ClickHouse mutation 은 상관 서브쿼리를 못 쓰므로 flat dictionary 로 룩업한다.
CREATE DICTIONARY IF NOT EXISTS geospatial.sig_counts_dict
(
    code String,
    cnt  UInt64
)
PRIMARY KEY code
SOURCE(CLICKHOUSE(HOST 'localhost' PORT 9000 DB 'geospatial' TABLE 'sig_counts' USER 'default'))
LAYOUT(COMPLEX_KEY_HASHED())
LIFETIME(0);

SYSTEM RELOAD DICTIONARY geospatial.sig_counts_dict;

ALTER TABLE geospatial.sig_map
UPDATE metric = toFloat64(dictGetOrDefault('geospatial.sig_counts_dict', 'cnt', tuple(code), toUInt64(metric)))
WHERE 1
SETTINGS mutations_sync = 2;

-- 확인: 분류된 점 수 / 상위 시군구
SELECT sum(cnt) AS classified_points FROM geospatial.sig_counts WHERE code != '';
SELECT s.name, c.cnt
FROM geospatial.sig_counts c
JOIN (SELECT DISTINCT code, name FROM geospatial.sig_map) s ON s.code = c.code
WHERE c.code != ''
ORDER BY c.cnt DESC
LIMIT 10;
