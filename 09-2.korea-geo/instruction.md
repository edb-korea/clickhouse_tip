# Claude Code 작업 지시서 — ClickHouse(OSS) + Superset 한국 행정구역 지도 랩

## 0. 목표 (이 작업이 끝나면 되어 있어야 하는 상태)

1. 로컬 Docker에 **ClickHouse OSS**와 **Superset**가 같은 네트워크에서 떠 있다.
2. ClickHouse에 `geospatial` 데이터베이스가 있고, **한국 시군구 경계(WGS84/EPSG:4326)** 가 적재되어 있다.
3. ClickHouse에 **Polygon Dictionary**가 만들어져 있어, 좌표 → 시군구 **리버스 지오코딩**이 동작한다.
   - 검증 기준점: `(127.289, 36.480)` → **세종특별자치시**(행정수도)가 나와야 한다.
4. Superset에서 ClickHouse를 데이터소스로 연결하고, **deck.gl Polygon** 차트로 시군구 경계가 지도 위에 색칠되어 보인다.

> ⚠️ 핵심 원칙: ClickHouse의 geo 함수(`pointInPolygon`, `geoToH3`, polygon dictionary)는 **WGS84 경위도(degree)** 를 전제한다. EPSG:5179(UTM-K, 미터) 좌표를 넣으면 **에러 없이 조용히 틀린 결과**를 낸다. 따라서 데이터는 반드시 4326 상태로 적재한다.

---

## 1. 범위 / 비범위

- **범위:** 시군구(약 250개) 단위. 합리적 vertex 수로 빠르게 동작.
- **비범위(이번엔 제외):** 읍면동(수천 개, vertex 폭증 → 단순화 단계 필요). 1차 랩 성공 후 별도로 확장.
- **인프라:** 전부 로컬 Docker. 클라우드/실데이터 연동 없음.

---

## 2. 작업 디렉토리 구조 (생성할 것)

```
korea-geo/
├── docker-compose.yml          # clickhouse + superset 스택
├── superset/
│   └── requirements-local.txt  # clickhouse-connect 드라이버 추가용
├── data/
│   └── (다운로드한 geojson)
├── ddl/
│   ├── 01_schema.sql           # database + tables + dictionary
│   └── 02_validate.sql         # 검증 쿼리
├── scripts/
│   └── load_geo.py             # geojson → clickhouse 적재
└── README.md                   # 실행 순서 + 검증 결과 기록
```

---

## 3. 단계별 작업

### Step 1 — Docker 스택 기동

`docker-compose.yml`을 작성한다. ClickHouse OSS와 Superset를 **같은 compose / 같은 네트워크**에 둬서 Superset가 `clickhouse:8123`으로 접근 가능하게 한다.

요구사항:
- ClickHouse: `clickhouse/clickhouse-server` 최신 안정 태그. 포트 `8123`(HTTP), `9000`(native) 노출. `default` 유저, 패스워드 없음(로컬 랩). `ulimits nofile` 설정.
- Superset: `apache/superset` 이미지. 메타DB(SQLite도 로컬 랩엔 충분하나 공식 compose는 postgres+redis 사용) — **간단함 우선**으로 가되, 드라이버 설치와 init이 누락되지 않게 한다.
- Superset에 **`clickhouse-connect`** 파이썬 패키지를 반드시 설치한다 (Superset 공식 ClickHouse 드라이버).

> 구현 노트: 가장 안정적인 경로는 Apache Superset 공식 레포의 `docker-compose-non-dev.yml`을 받아서
> (a) `docker/requirements-local.txt`에 `clickhouse-connect` 한 줄 추가하고
> (b) 같은 compose에 `clickhouse` 서비스 블록을 추가하는 것이다.
> 다만 버전에 따라 서비스 구성이 바뀌므로, **떠 있는지 직접 확인(curl/healthcheck)** 하고 안 되면 적응적으로 수정할 것.

기동 후 검증:
```bash
# ClickHouse 살아있나
curl 'http://localhost:8123/?query=SELECT%20version()'
# Superset UI 접근되나 (기본 8088)
curl -I http://localhost:8088/health
```
Superset admin 계정 생성 + `superset db upgrade` + `superset init`이 필요하면 수행한다(이미지/compose에 따라 자동일 수 있음).

---

### Step 2 — 행정구역 경계 데이터 확보 (WGS84)

**기본 경로 (변환 불필요):** 이미 WGS84(EPSG:4326)인 시군구 GeoJSON을 받는다. 후보(접근 가능한 것을 사용):
- `southkorea/southkorea-maps` (GitHub) — `kostat/...` 하위에 시군구(municipalities) / 시도(provinces) GeoJSON, WGS84.
- `vuski/admdongkor` (GitHub) — 읍면동 GeoJSON(WGS84). 시군구가 필요하면 `SIG_CD` 앞 5자리로 dissolve 하거나, 위 southkorea 소스를 우선 사용.

**★ 좌표계 자동 판별 (반드시 수행):** 다운로드한 GeoJSON의 첫 좌표값을 확인한다.
- 경도 약 `124~132`, 위도 약 `33~39` 범위 → **이미 EPSG:4326. 그대로 진행.**
- 값이 `1,000,000` 단위의 큰 숫자 → **EPSG:5179(미터). 아래 변환 필수.**

**변환이 필요한 경우 (5179 소스를 받았을 때):** ClickHouse는 좌표계 재투영을 못 하므로 **적재 전에** 변환한다.
```bash
# GDAL 사용 (ogr2ogr). SHP/GeoJSON 모두 가능
ogr2ogr -t_srs EPSG:4326 sig_4326.geojson sig_5179.shp
# 또는 GeoPandas
python -c "import geopandas as gpd; gpd.read_file('sig_5179.shp').to_crs(4326).to_file('sig_4326.geojson', driver='GeoJSON')"
```

다운로드/변환한 최종 파일을 `data/sig_4326.geojson`으로 둔다. 속성에서 **시군구 코드(보통 `SIG_CD` 5자리 또는 행안부/통계청 코드)** 와 **이름 필드**를 확인해 둔다(스크립트에서 사용).

---

### Step 3 — ClickHouse 스키마 (`ddl/01_schema.sql`)

두 가지 표현을 만든다. ① 딕셔너리용 전체 MultiPolygon, ② Superset 시각화용 ring 단위 행.

```sql
CREATE DATABASE IF NOT EXISTS geospatial;

-- ① Polygon Dictionary 소스 테이블 (전체 MultiPolygon)
CREATE TABLE IF NOT EXISTS geospatial.sig_polygons
(
    key  Array(Array(Array(Tuple(Float64, Float64)))),  -- [polygon][ring][point(lon,lat)]
    code String,
    name String
)
ENGINE = MergeTree ORDER BY code;

-- ② Superset deck.gl Polygon 시각화용 (외곽 ring 1개 = 1행)
CREATE TABLE IF NOT EXISTS geospatial.sig_map
(
    code        String,
    name        String,
    metric      Float64,      -- 색칠용 값 (랩: 합성값 / 후엔 실데이터 조인)
    coordinates String        -- JSON: [[lon,lat],[lon,lat],...] (외곽 ring)
)
ENGINE = MergeTree ORDER BY code;
```

```sql
-- Polygon Dictionary (리버스 지오코딩)
CREATE DICTIONARY IF NOT EXISTS geospatial.sig_dict
(
    key  Array(Array(Array(Tuple(Float64, Float64)))),
    code String,
    name String
)
PRIMARY KEY key
SOURCE(CLICKHOUSE(HOST 'localhost' PORT 9000 DB 'geospatial' TABLE 'sig_polygons' USER 'default'))
LAYOUT(POLYGON(STORE_POLYGON_KEY_COLUMN 1))
LIFETIME(0);
```

> 노트: OSS 로컬이라 dictionary SOURCE는 localhost:9000(native)로 self-reference. 컨테이너 내부에서 실행하면 host는 `localhost` 또는 컨테이너명. 작동 안 하면 HOST를 ClickHouse 서비스명으로 바꿔 시도.

---

### Step 4 — 적재 스크립트 (`scripts/load_geo.py`)

`clickhouse-connect`(HTTP 8123) + 표준 `json`만 사용(무거운 의존성 회피). 로직:

1. `data/sig_4326.geojson` 로드.
2. 각 feature에서 `code`, `name` 추출(속성 필드명은 Step 2에서 확인한 실제 키 사용).
3. geometry 처리:
   - **딕셔너리용(`sig_polygons`)**: GeoJSON `Polygon` → `[coords]`로 한 번 감싸고, `MultiPolygon` → coords 그대로. 각 점 `[lon,lat]`을 튜플로. (구조 = `[polygon][ring][point]`)
   - **시각화용(`sig_map`)**: 각 polygon part의 **외곽 ring(첫 ring)** 만 뽑아 `[[lon,lat],...]`를 JSON 문자열로. MultiPolygon이면 part마다 1행(code/name/metric 공유).
4. `metric`: 합성값 — 시군구별 `random.randint(1,100)` 같은 안정값(같은 시군구의 여러 ring은 동일 metric).
5. `clickhouse-connect`로 두 테이블에 insert. 좌표는 중첩 리스트/튜플 그대로 전달(드라이버가 nested 처리).

검증 출력: 적재 행 수, 고유 시군구 수(약 250 기대) 로그.

> 의존성: `pip install clickhouse-connect` (로컬 파이썬 또는 별도 컨테이너에서 실행). geopandas는 굳이 불필요(변환 단계에서만 선택적).

---

### Step 5 — 검증 (`ddl/02_validate.sql`, ClickHouse)

```sql
-- 적재 확인
SELECT count() AS rings, uniqExact(code) AS sigungu_cnt FROM geospatial.sig_map;
SELECT count() FROM geospatial.sig_polygons;

-- ★ 리버스 지오코딩: 세종 = 행정수도 (변환 정합성 핵심 검증)
SELECT dictGet('geospatial.sig_dict', 'name', (127.289, 36.480)) AS sejong;     -- 기대: 세종 관련
SELECT dictGet('geospatial.sig_dict', 'name', (126.9780, 37.5665)) AS seoul;    -- 기대: 서울 중구/종로 인근
SELECT dictGet('geospatial.sig_dict', 'name', (129.0756, 35.1796)) AS busan;    -- 기대: 부산 인근

-- geo 함수 스모크 (WGS84 정상 / 5179 미터 비정상 대비)
SELECT
  geoToH3(127.289, 36.480, 7)                                              AS sejong_h3,
  pointInPolygon((127.289,36.480), [(124.5,33.0),(132.0,33.0),(132.0,38.7),(124.5,38.7)]) AS wgs84_ok,   -- 기대 1
  pointInPolygon((612656.0,1791892.0), [(124.5,33.0),(132.0,33.0),(132.0,38.7),(124.5,38.7)]) AS utmk_bad; -- 기대 0 (변환 안 하면 틀림)
```

세 리버스 지오코딩이 올바른 행정구역을 반환하면 좌표계·적재가 정상이다. 결과를 `README.md`에 기록.

---

### Step 6 — Superset 연결

1. Superset UI(`http://localhost:8088`) 로그인 → Settings → Database Connections → + Database.
2. ClickHouse(`clickhouse-connect`) 선택 또는 SQLAlchemy URI 직접 입력:
   ```
   clickhousedb://default:@clickhouse:8123/geospatial
   ```
   - host는 compose 서비스명(`clickhouse`). 드라이버 미설치 시 dialect를 못 찾으니 Step 1의 `clickhouse-connect` 설치 확인.
3. Test Connection → 성공 확인.
4. Datasets → + Dataset → database `geospatial`, table `sig_map` 등록.

---

### Step 7 — deck.gl Polygon 지도 차트

1. Charts → + Chart → dataset `sig_map` → 차트 타입 **deck.gl Polygon**.
2. 설정:
   - **Polygon Column**: `coordinates`
   - **Polygon Encoding / line_type**: `json` (좌표가 `[[lon,lat],...]` JSON 배열이므로)
   - **Metric**: `AVG(metric)` 또는 `MAX(metric)` (색상 인코딩)
   - **Point Radius/Color**: metric 기준 컬러 스킴 지정
3. Run → 시군구 경계가 한반도 위에 색칠되어 표시되는지 확인.

> ⚠️ **베이스맵 토큰:** deck.gl 차트의 지도 배경 타일은 보통 `MAPBOX_API_KEY`가 필요하다. `superset_config.py`(또는 compose env)에 무료 Mapbox 토큰을 넣으면 지도 위에 깔끔히 표시된다. 토큰 없이도 폴리곤 자체는 렌더되지만 지도 배경이 빈/제한된 형태일 수 있다. 안 보이면 토큰부터 의심.

검증: **세종 위치(충청 중앙)에 세종 폴리곤이 정확히** 찍히는지 눈으로 확인 → 좌표계 변환이 시각적으로도 맞다는 증거.

---

### Step 8 — (선택/스트레치) 포인트 → 리버스 지오코딩 → 카운트 → choropleth

진짜 가치 데모. ClickHouse가 분류·집계, Superset가 시각화하는 풀 파이프라인.

1. 한반도 bbox 안 랜덤 포인트 N개 테이블 생성(`geospatial.points`, lon/lat).
2. 딕셔너리로 각 점의 시군구 분류 후 카운트:
   ```sql
   CREATE TABLE geospatial.sig_counts ENGINE=MergeTree ORDER BY code AS
   SELECT dictGet('geospatial.sig_dict','code',(lon,lat)) AS code, count() AS cnt
   FROM geospatial.points GROUP BY code;
   ```
3. `sig_map`의 `metric`을 이 `cnt`로 갱신(조인/뷰)하여 choropleth가 **실제 분포**를 보여주게.
   - Ken 실데이터(예: 사용자 행동 로그의 lon/lat)로 바꾸면 그대로 "시군구별 사용자 분포 맵"이 된다.

---

## 4. 완료 체크리스트 (README.md에 결과 기록)

- [ ] `curl SELECT version()` 응답 OK
- [ ] Superset `/health` OK + admin 로그인됨
- [ ] `sig_map` 행 수 / 고유 시군구 ≈ 250 확인
- [ ] `sig_dict`로 세종/서울/부산 리버스 지오코딩 정상
- [ ] `utmk_bad = 0`, `wgs84_ok = 1` 확인 (좌표계 함정 재현)
- [ ] Superset ClickHouse 연결 Test 성공
- [ ] deck.gl Polygon에서 시군구 경계가 지도에 렌더됨
- [ ] 세종 폴리곤이 충청 중앙에 정확히 위치 (시각 검증)

---

## 5. 트러블슈팅 메모

- **Superset가 clickhouse dialect 못 찾음** → `clickhouse-connect` 미설치. requirements-local.txt 반영 후 컨테이너 재빌드/재기동.
- **연결은 되는데 host 못 찾음** → URI host를 compose 서비스명(`clickhouse`)으로. `localhost`는 Superset 컨테이너 내부를 가리킨다.
- **dictionary 생성/조회 실패** → SOURCE의 HOST를 `localhost`↔서비스명으로 바꿔 시도. `SYSTEM RELOAD DICTIONARY geospatial.sig_dict` 후 재조회.
- **deck.gl 지도 배경 안 보임** → `MAPBOX_API_KEY` 설정.
- **리버스 지오코딩이 전부 틀림/공백** → 좌표계 미변환(5179) 의심. 좌표 magnitude 재확인 후 ogr2ogr 변환.
- **세종이 안 나옴** → 사용한 경계 파일 vintage가 세종시 분리(2012) 이전이거나 코드 체계 불일치. 최신 파일 사용 + 코드 필드 재확인.

---

## 6. 사용한 결정사항 요약 (왜 이렇게 했는지)

- ClickHouse OSS Docker: 클라우드 불필요, 로컬에서 폴리곤 딕셔너리까지 전부 검증 가능.
- WGS84 소스 우선: ClickHouse는 좌표 재투영을 못 하므로, 변환 단계를 아예 없애는 게 가장 단순.
- 표현 2종 분리: 딕셔너리(정확 분류)는 전체 MultiPolygon, 시각화(deck.gl)는 ring 단위 — 도구별 요구 포맷이 다르기 때문.
- Superset deck.gl Polygon: 오픈소스에서 한국 시군구 choropleth를 네이티브로 그릴 수 있는 가장 균형 잡힌 선택(H3 헥사곤이 hard requirement면 kepler.gl/커스텀 deck.gl로 별도 확장).