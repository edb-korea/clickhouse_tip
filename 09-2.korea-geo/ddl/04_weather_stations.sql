-- ===========================================================================
-- 전국 임의 관측소(weather stations) 3,000개 + 시군구별 집계 + choropleth 조인
-- 실행: docker exec -i kg-clickhouse clickhouse-client --multiquery < ddl/04_weather_stations.sql
--
-- 포인트는 bbox 안에 랜덤으로 찍되, Polygon Dictionary 로 시군구에 분류되는(=육지) 점만 채택.
-- 각 점에 합성 기온/고도 부여 → 실데이터(실제 관측소 lon/lat)로 바꾸면 그대로 동작.
-- ===========================================================================

-- 1) 관측소 테이블
CREATE TABLE IF NOT EXISTS geospatial.weather_stations
(
    station_id   UInt32,
    name         String,
    lon          Float64,
    lat          Float64,
    sigungu_code String,
    sigungu_name String,
    temp_c       Float64,   -- 합성 기온(위도 높을수록 낮게 + 노이즈)
    elevation_m  Float64
)
ENGINE = MergeTree ORDER BY station_id;

TRUNCATE TABLE geospatial.weather_stations;

-- 2) 3,000개 적재 (bbox 랜덤 → 딕셔너리로 시군구 분류된 점만 LIMIT 3000)
INSERT INTO geospatial.weather_stations
SELECT
    rowNumberInAllBlocks() + 1                                              AS station_id,
    concat('KMA-', leftPad(toString(rowNumberInAllBlocks() + 1), 4, '0'))   AS name,
    lon, lat, code AS sigungu_code, sname AS sigungu_name,
    round(16.0 - (lat - 33.0) * 2.6 + (rand() / 4294967295.0 - 0.5) * 6, 1) AS temp_c,
    round((rand() / 4294967295.0) * 800, 0)                                 AS elevation_m
FROM
(
    SELECT
        lon, lat,
        dictGet('geospatial.sig_dict', 'code', (lon, lat)) AS code,
        dictGet('geospatial.sig_dict', 'name', (lon, lat)) AS sname
    FROM
    (
        SELECT
            124.6 + (rand()  / 4294967295.0) * (130.9 - 124.6) AS lon,
            33.2  + (rand(1) / 4294967295.0) * (38.6  - 33.2)  AS lat
        FROM numbers(60000)
    )
    WHERE code != ''
    LIMIT 3000
);

-- 3) 시군구별 집계 (관측소 수 / 평균기온 / 평균고도)
CREATE OR REPLACE TABLE geospatial.sig_station_agg
ENGINE = MergeTree ORDER BY sigungu_code AS
SELECT
    sigungu_code,
    any(sigungu_name)      AS sigungu_name,
    count()                AS station_count,
    round(avg(temp_c), 1)  AS avg_temp,
    round(avg(elevation_m))AS avg_elev
FROM geospatial.weather_stations
GROUP BY sigungu_code;

-- 4) deck.gl Polygon choropleth 용 조인 테이블 (관측소 0개 시군구도 LEFT JOIN 으로 포함)
CREATE OR REPLACE TABLE geospatial.sig_station_map
ENGINE = MergeTree ORDER BY code AS
SELECT
    m.code                              AS code,
    m.name                              AS name,
    m.coordinates                       AS coordinates,
    toFloat64(ifNull(a.station_count, 0)) AS station_count,
    ifNull(a.avg_temp, 0)               AS avg_temp
FROM geospatial.sig_map AS m
LEFT JOIN geospatial.sig_station_agg AS a ON a.sigungu_code = m.code;

-- 5) 확인
SELECT count() AS stations, uniqExact(sigungu_code) AS covered_sigungu FROM geospatial.weather_stations;
SELECT sigungu_name, station_count, avg_temp
FROM geospatial.sig_station_agg
ORDER BY station_count DESC
LIMIT 10;
