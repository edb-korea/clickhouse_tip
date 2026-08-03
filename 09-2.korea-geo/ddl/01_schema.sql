CREATE DATABASE IF NOT EXISTS geospatial ON CLUSTER my_cluster;

CREATE TABLE IF NOT EXISTS geospatial.sig_polygons ON CLUSTER my_cluster
(
    key  Array(Array(Array(Tuple(Float64, Float64)))),
    code String,
    name String
)
ENGINE = ReplicatedMergeTree(
    '/clickhouse/tables/{shard}/geospatial/sig_polygons',
    '{replica}'
)
ORDER BY code;

CREATE TABLE IF NOT EXISTS geospatial.sig_map ON CLUSTER my_cluster
(
    code        String,
    name        String,
    metric      Float64,
    coordinates String
)
ENGINE = ReplicatedMergeTree(
    '/clickhouse/tables/{shard}/geospatial/sig_map',
    '{replica}'
)
ORDER BY code;

CREATE DICTIONARY IF NOT EXISTS geospatial.sig_dict ON CLUSTER my_cluster
(
    key  Array(Array(Array(Tuple(Float64, Float64)))),
    code String,
    name String
)
PRIMARY KEY key
SOURCE(CLICKHOUSE(
    HOST 'localhost'
    PORT 9000
    DB 'geospatial'
    TABLE 'sig_polygons'
    USER 'default'
))
LAYOUT(POLYGON(STORE_POLYGON_KEY_COLUMN 1))
LIFETIME(0);
