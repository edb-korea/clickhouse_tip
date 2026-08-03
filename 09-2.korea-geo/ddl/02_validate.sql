-- ===========================================================================
-- 검증 쿼리 — 적재 정합성 + 좌표계 함정 재현
-- 실행: docker exec -i kg-clickhouse clickhouse-client --multiquery < ddl/02_validate.sql
-- ===========================================================================

-- 적재 확인 (외곽 ring 행 수 / 고유 시군구 수 ≈ 251)
SELECT count() AS rings, uniqExact(code) AS sigungu_cnt FROM geospatial.sig_map;
SELECT count() AS dict_source_rows FROM geospatial.sig_polygons;

-- ★ 리버스 지오코딩 (좌표계·적재 정합성 핵심 검증)
SELECT dictGet('geospatial.sig_dict', 'name', (127.289, 36.480))  AS sejong;  -- 기대: 세종
SELECT dictGet('geospatial.sig_dict', 'name', (126.9780, 37.5665)) AS seoul;  -- 기대: 종로구(서울 중심)
SELECT dictGet('geospatial.sig_dict', 'name', (129.0756, 35.1796)) AS busan;  -- 기대: 부산 인근(연제구)

-- geo 함수 스모크: WGS84 정상(1) vs 5179 미터 비정상(0)
SELECT
  geoToH3(127.289, 36.480, 7)                                                                AS sejong_h3,
  pointInPolygon((127.289, 36.480),    [(124.5,33.0),(132.0,33.0),(132.0,38.7),(124.5,38.7)]) AS wgs84_ok,   -- 기대 1
  pointInPolygon((612656.0, 1791892.0),[(124.5,33.0),(132.0,33.0),(132.0,38.7),(124.5,38.7)]) AS utmk_bad;   -- 기대 0
