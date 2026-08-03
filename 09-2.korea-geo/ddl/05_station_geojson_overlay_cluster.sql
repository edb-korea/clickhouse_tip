-- ===========================================================================
-- 기존 관측소/시군구 집계 테이블로 GeoJSON overlay 테이블만 생성/갱신
-- AWS 3-replica ClickHouse 클러스터용. 클러스터 이름: my_cluster
-- 실행: clickhouse-client --password "$CLICKHOUSE_PASSWORD" --multiquery < ddl/05_station_geojson_overlay_cluster.sql
-- ===========================================================================

DROP TABLE IF EXISTS geospatial.station_geojson_overlay ON CLUSTER my_cluster;

CREATE TABLE geospatial.station_geojson_overlay ON CLUSTER my_cluster
(
    layer   String,
    name    String,
    metric  Float64,
    feature String
)
ENGINE = ReplicatedMergeTree(
    '/clickhouse/tables/{shard}/geospatial/station_geojson_overlay',
    '{replica}'
)
ORDER BY (layer, name);

INSERT INTO geospatial.station_geojson_overlay
SELECT
    'district' AS layer,
    name,
    station_count AS metric,
    concat(
        '{"type":"Feature","geometry":{"type":"Polygon","coordinates":[',
        coordinates,
        ']},"properties":{"layer":"district","name":',
        toJSONString(name),
        ',"station_count":',
        toString(station_count),
        ',"avg_temp":',
        toString(avg_temp),
        '}}'
    ) AS feature
FROM geospatial.sig_station_map
UNION ALL
SELECT
    'station' AS layer,
    name,
    temp_c AS metric,
    concat(
        '{"type":"Feature","geometry":{"type":"Point","coordinates":[',
        toString(lon),
        ',',
        toString(lat),
        ']},"properties":{"layer":"station","name":',
        toJSONString(name),
        ',"sigungu_name":',
        toJSONString(sigungu_name),
        ',"temp_c":',
        toString(temp_c),
        ',"elevation_m":',
        toString(elevation_m),
        '}}'
    ) AS feature
FROM geospatial.weather_stations;

SELECT layer, count() AS features
FROM geospatial.station_geojson_overlay
GROUP BY layer
ORDER BY layer;
