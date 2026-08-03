# ClickHouse (OSS) + Superset — Korean Administrative-Boundary (Sigungu) Map Lab / 한국 행정구역(시군구) 지도 랩

[English](#english) | [한국어](#한국어)

---

## English

A hands-on lab that implements **coordinate → district reverse geocoding** (ClickHouse Polygon Dictionary) and a **deck.gl Polygon choropleth** (Superset) entirely on local Docker. It demonstrates the full pipeline where **ClickHouse classifies & aggregates** and **Superset visualizes**, and ends with a weather-station dashboard that overlays 3,000 points on per-district aggregates.

> **Key trap:** ClickHouse geo functions (`pointInPolygon`, `geoToH3`, polygon dictionary) assume **WGS84 longitude/latitude in degrees (EPSG:4326)**. Feeding EPSG:5179 (UTM-K, meters) coordinates produces a **silently wrong result with no error**. So data must be loaded in 4326.

Author: Ken Lee (ClickHouse SA) · License: MIT

### Stack

| Service | Image | Port (host) | Notes |
|---|---|---|---|
| ClickHouse | `clickhouse/clickhouse-server:25.5` | 8123 (HTTP), 9000 (native) | `default` user, no password (local lab) |
| Superset | `apache/superset:4.1.1` + `clickhouse-connect` | 8088 | SQLite metadata (volume-persisted), admin/admin |

```
korea-geo/
├── docker-compose.yml          # clickhouse + superset stack (network: korea-geo)
├── superset/
│   ├── Dockerfile              # official image + clickhouse-connect
│   ├── requirements-local.txt  # clickhouse-connect
│   ├── superset_config.py      # SECRET_KEY / MAPBOX_API_KEY / SQLite metadata
│   └── bootstrap.sh            # db upgrade → create-admin → init → gunicorn
├── data/sig_4326.geojson       # 251 sigungu boundaries (WGS84) — southkorea/southkorea-maps
├── ddl/
│   ├── 01_schema.sql              # DB + 2 tables + Polygon Dictionary
│   ├── 02_validate.sql            # load / reverse-geocoding / coordinate-trap checks
│   ├── 03_points_choropleth.sql   # random points → classify → aggregate → update metric
│   └── 04_weather_stations.sql    # 3,000 stations + per-district aggregates + choropleth join
├── scripts/
│   ├── load_geo.py                # geojson → ClickHouse (clickhouse-connect)
│   ├── setup_superset.py          # Superset DB connection + sig_map dataset (auto)
│   └── setup_dashboard.py         # station datasets + 4 charts + dashboard (auto, idempotent)
└── README.md
```

Two data representations are kept separate because each tool needs a different format:
- `geospatial.sig_polygons` — full MultiPolygon `[polygon][ring][point]` → Polygon Dictionary source (accurate classification)
- `geospatial.sig_map` — one outer ring per row, `coordinates` as `[[lon,lat],...]` JSON → deck.gl visualization

### Run order (reproduce)

```bash
cd usecase/korea-geo

# 0) (optional) Mapbox token for deck.gl basemap tiles. Without it, only polygons render.
export MAPBOX_API_KEY="pk.xxxxx"

# 1) Bring up the stack (superset image builds on first run)
docker compose up -d --build

# 2) Health checks
curl 'http://localhost:8123/?query=SELECT%20version()'      # -> 25.5.x
curl -I http://localhost:8088/health                         # -> HTTP/1.1 200 OK

# 3) Schema + dictionary
docker exec -i kg-clickhouse clickhouse-client --multiquery < ddl/01_schema.sql

# 4) Load data (host python; install driver)
python3 -m pip install --user clickhouse-connect
python3 scripts/load_geo.py
docker exec kg-clickhouse clickhouse-client --query "SYSTEM RELOAD DICTIONARY geospatial.sig_dict"

# 5) Validate
docker exec -i kg-clickhouse clickhouse-client --multiquery < ddl/02_validate.sql

# 6) (optional) points → classify → aggregate → update choropleth metric
docker exec -i kg-clickhouse clickhouse-client --multiquery < ddl/03_points_choropleth.sql

# 7) Register the ClickHouse connection + sig_map dataset in Superset
python3 scripts/setup_superset.py
```

Inside the ClickHouse container `localhost:9000` is a self-reference, so the dictionary `SOURCE` HOST is `localhost`. From the Superset container, ClickHouse is reached by the compose service name `clickhouse:8123` (see URI below).

### Verified results (measured — ClickHouse 25.5.11.15 / Superset 4.1.1)

- [x] `curl SELECT version()` → `25.5.11.15`
- [x] Superset `/health` → `HTTP 200`, admin (admin/admin) login works
- [x] `sig_map` rows / distinct sigungu → **rings=325, sigungu=251**
- [x] `sig_polygons` (dictionary source) = **251**
- [x] `sig_dict` reverse geocoding correct (table below)
- [x] `utmk_bad = 0`, `wgs84_ok = 1` — coordinate-system trap reproduced
- [x] Superset ClickHouse connection test → **200 OK**
- [x] deck.gl Polygon chart-data query → **325 rows** (`coordinates` JSON + `name` + `MAX(metric)`)

**Reverse geocoding** (`dictGet('geospatial.sig_dict','name',(lon,lat))`):

| Input (lon, lat) | Result | Expected |
|---|---|---|
| `(127.289, 36.480)` | **세종시 (Sejong)** | Sejong (admin capital) ✓ |
| `(126.9780, 37.5665)` | **종로구 (Jongno-gu)** | central Seoul ✓ |
| `(129.0756, 35.1796)` | **연제구 (Yeonje-gu)** | near Busan ✓ |

**Coordinate-system trap** (geo-function smoke test):

```
geoToH3(127.289, 36.480, 7)                       = 608482148894113791
pointInPolygon((127.289, 36.480), Korea bbox)     = 1   ← WGS84 OK
pointInPolygon((612656, 1791892), Korea bbox)     = 0   ← 5179 meters = silently wrong
```

The same Sejong location is inside the box (1) in 4326 (degrees) but outside (0) in 5179 (meters) — proof that **skipping reprojection yields a wrong result with no error**.

### Weather-station dashboard — point visualization + per-district aggregation

Place **3,000 random weather stations** nationwide and build a dashboard that ① visualizes the points, ② aggregates per district, and ③ overlays both. Swap `weather_stations` for real station/sensor/store lon·lat and it becomes a production dashboard as-is.

```bash
docker exec -i kg-clickhouse clickhouse-client --multiquery < ddl/04_weather_stations.sql
python3 scripts/setup_dashboard.py
```

- `geospatial.weather_stations` — 3,000 stations. Only bbox-random points that the dictionary classifies into a sigungu (= on land) are kept. Each gets a synthetic `temp_c` (colder as latitude rises + noise), `elevation_m`, and `sigungu_code`/`sigungu_name` (the classification result).
- `geospatial.sig_station_agg` — per-district `station_count` / `avg_temp` / `avg_elev`.
- `geospatial.sig_station_map` — `sig_map` (polygon rings) ⨝ aggregates → for the deck.gl Polygon choropleth (zero-station districts kept via LEFT JOIN).

**Measured:** 3,000 stations across **217** districts; temperature range **-0.7 ~ 17.9 °C** (≈3 °C in northern Gangwon, ≈9 °C in the south). Top districts (large rural counties — natural under uniform random): 인제군 53 · 홍천군 49 · 안동시 48 · 의성군 44 · 평창군 41 … All 4 Superset charts + dashboard auto-created; every chart-data API call returned 200/data.

**Endpoints (admin/admin):**

| Item | URL |
|---|---|
| **Dashboard "전국 관측소 현황"** | http://localhost:8088/superset/dashboard/1/ |
| Overlay map (deck.gl Multi: choropleth + station points) | http://localhost:8088/explore/?slice_id=3 |
| Station distribution (deck.gl Scatter) | http://localhost:8088/explore/?slice_id=1 |
| Stations per district (deck.gl Polygon choropleth) | http://localhost:8088/explore/?slice_id=2 |
| Per-district TOP (Table) | http://localhost:8088/explore/?slice_id=4 |

> Layout: **overlay map** on top (station points + district shading), **choropleth + TOP table** below.
> Points/polygons render without a token; basemap tiles appear only when `MAPBOX_API_KEY` is set.

`setup_dashboard.py` is **idempotent** — re-running after re-generating stations (`04_weather_stations.sql`) or swapping in real data updates the same charts/dashboard instead of duplicating them.

### Build a deck.gl Polygon chart manually (UI)

1. http://localhost:8088 → log in **admin / admin**.
2. Charts → + Chart → dataset `sig_map` (or `sig_station_map`) → **deck.gl Polygon**:
   - **Polygon Column**: `coordinates`
   - **line_type / Polygon Encoding**: `json`
   - **Metric**: `MAX(metric)` (or `MAX(station_count)`)
   - pick a linear color scheme + opacity → **Run**.
3. **Visual check:** districts shaded over the peninsula, with the **Sejong polygon centered in Chungcheong** — visual proof the coordinate system is right.

Superset DB connection URI (uses the service name):
```
clickhousedb://default:@clickhouse:8123/geospatial
```

### Troubleshooting (including issues actually hit during this build)

- **Superset can't find the `clickhousedb` dialect** → `clickhouse-connect` not installed. Add to `superset/requirements-local.txt`, then `docker compose build superset`.
- **Connects but host not found** → set the URI host to the compose service name `clickhouse`, not `localhost`.
- **`test_connection` returns an HTML redirect** → the endpoint needs a **trailing slash** (`/api/v1/database/test_connection/`). Handled in `setup_superset.py`.
- **`ALTER ... UPDATE` errors with UNKNOWN_IDENTIFIER** → ClickHouse mutations don't support correlated subqueries. `03_points_choropleth.sql` works around it with a flat dictionary (`sig_counts_dict`) + `dictGetOrDefault`.
- **Dictionary empty / lookup fails** → run `SYSTEM RELOAD DICTIONARY geospatial.sig_dict` **after** loading data. `LIFETIME(0)` never auto-reloads.
- **Reverse geocoding all wrong/blank** → suspect un-reprojected (5179) data. `load_geo.py` blocks this by checking the first coordinate's magnitude before loading.
- **Superset REST filter returns 400 "Not a valid rison" / duplicate charts on re-run** → names containing parentheses break the rison filter. `setup_dashboard.py` wraps filter values in single quotes (`find_id()`) so lookups match and re-runs update in place.
- **Dashboard panel says "no chart definition associated with this component"** → charts created via API must be explicitly linked to the dashboard; `setup_dashboard.py` PUTs `dashboards:[id]` on each chart.

### If your source needs reprojection (EPSG:5179 → 4326)

This lab's data (`southkorea/southkorea-maps`) is already WGS84, so no conversion is needed. For a 5179 (meters) source, convert **before** loading:

```bash
ogr2ogr -t_srs EPSG:4326 data/sig_4326.geojson sig_5179.shp
# or
python -c "import geopandas as gpd; gpd.read_file('sig_5179.shp').to_crs(4326).to_file('data/sig_4326.geojson', driver='GeoJSON')"
```

### Teardown / scope

```bash
docker compose down            # containers only
docker compose down -v         # also drop volumes (ClickHouse data + Superset metadata)
```

- This lab works at the **sigungu (251)** level. Eup/myeon/dong (thousands, vertex explosion → needs simplification) is out of scope for the first pass.
- Data source: [`southkorea/southkorea-maps`](https://github.com/southkorea/southkorea-maps) `kostat/2013` sigungu GeoJSON (WGS84, simplified).

---

## 한국어

좌표 → 시군구 **리버스 지오코딩**(ClickHouse Polygon Dictionary)과 **deck.gl Polygon choropleth**(Superset)를 전부 로컬 Docker에서 구현한 핸즈온 랩. **ClickHouse가 분류·집계**하고 **Superset이 시각화**하는 풀 파이프라인을 보여주며, 마지막엔 관측소 3,000개 포인트를 시군구별 집계 위에 오버레이한 대시보드까지 만든다.

> **핵심 함정:** ClickHouse geo 함수(`pointInPolygon`, `geoToH3`, polygon dictionary)는 **WGS84 경위도(degree, EPSG:4326)** 를 전제한다. EPSG:5179(UTM-K, 미터) 좌표를 넣으면 **에러 없이 조용히 틀린 결과**를 낸다. 따라서 데이터는 반드시 4326 상태로 적재한다.

작성자: Ken Lee (ClickHouse SA) · 라이선스: MIT

### 구성

| 서비스 | 이미지 | 포트(호스트) | 비고 |
|---|---|---|---|
| ClickHouse | `clickhouse/clickhouse-server:25.5` | 8123(HTTP), 9000(native) | `default` 유저, 패스워드 없음(로컬 랩) |
| Superset | `apache/superset:4.1.1` + `clickhouse-connect` | 8088 | 메타DB는 SQLite(볼륨 영속), admin/admin |

```
korea-geo/
├── docker-compose.yml          # clickhouse + superset 스택 (network: korea-geo)
├── superset/
│   ├── Dockerfile              # 공식 이미지 + clickhouse-connect
│   ├── requirements-local.txt  # clickhouse-connect
│   ├── superset_config.py      # SECRET_KEY / MAPBOX_API_KEY / SQLite 메타DB
│   └── bootstrap.sh            # db upgrade → create-admin → init → gunicorn
├── data/sig_4326.geojson       # 시군구 251개 경계 (WGS84) — southkorea/southkorea-maps
├── ddl/
│   ├── 01_schema.sql              # DB + 테이블 2종 + Polygon Dictionary
│   ├── 02_validate.sql            # 적재/리버스지오코딩/좌표계 함정 검증
│   ├── 03_points_choropleth.sql   # 랜덤 포인트 → 분류 → 집계 → metric 갱신
│   └── 04_weather_stations.sql    # 관측소 3,000개 + 시군구별 집계 + choropleth 조인
├── scripts/
│   ├── load_geo.py                # geojson → ClickHouse (clickhouse-connect)
│   ├── setup_superset.py          # Superset DB연결 + sig_map 데이터셋 자동 생성
│   └── setup_dashboard.py         # 관측소 데이터셋 + 차트 4종 + 대시보드 자동 생성(멱등)
└── README.md
```

데이터 표현 2종 분리 — 도구별 요구 포맷이 다르기 때문:
- `geospatial.sig_polygons` : 전체 MultiPolygon `[polygon][ring][point]` → Polygon Dictionary 소스(정확한 분류)
- `geospatial.sig_map` : 외곽 ring 1개 = 1행, `coordinates`는 `[[lon,lat],...]` JSON → deck.gl 시각화

### 실행 순서 (재현)

```bash
cd usecase/korea-geo

# 0) (선택) deck.gl 베이스맵 타일용 Mapbox 토큰. 없으면 폴리곤만 렌더된다.
export MAPBOX_API_KEY="pk.xxxxx"

# 1) 스택 기동 (superset 이미지는 최초 1회 빌드)
docker compose up -d --build

# 2) 헬스 확인
curl 'http://localhost:8123/?query=SELECT%20version()'      # -> 25.5.x
curl -I http://localhost:8088/health                         # -> HTTP/1.1 200 OK

# 3) 스키마 + 딕셔너리 생성
docker exec -i kg-clickhouse clickhouse-client --multiquery < ddl/01_schema.sql

# 4) 데이터 적재 (호스트 python; 드라이버 설치)
python3 -m pip install --user clickhouse-connect
python3 scripts/load_geo.py
docker exec kg-clickhouse clickhouse-client --query "SYSTEM RELOAD DICTIONARY geospatial.sig_dict"

# 5) 검증
docker exec -i kg-clickhouse clickhouse-client --multiquery < ddl/02_validate.sql

# 6) (선택) 포인트 → 분류 → 집계 → choropleth metric 갱신
docker exec -i kg-clickhouse clickhouse-client --multiquery < ddl/03_points_choropleth.sql

# 7) Superset에 ClickHouse 연결 + 데이터셋 자동 등록
python3 scripts/setup_superset.py
```

ClickHouse 컨테이너 안에서 `localhost:9000`을 self-reference 하므로 딕셔너리 `SOURCE`의 HOST는 `localhost`로 둔다. Superset 컨테이너에서는 ClickHouse를 compose 서비스명 `clickhouse:8123`으로 접근한다(아래 URI).

### 검증 결과 (실측, ClickHouse 25.5.11.15 / Superset 4.1.1)

- [x] `curl SELECT version()` → `25.5.11.15`
- [x] Superset `/health` → `HTTP 200`, admin(admin/admin) 로그인됨
- [x] `sig_map` 행 수 / 고유 시군구 → **rings=325, 시군구=251**
- [x] `sig_polygons` (딕셔너리 소스) = **251**
- [x] `sig_dict` 리버스 지오코딩 정상 (아래 표)
- [x] `utmk_bad = 0`, `wgs84_ok = 1` — 좌표계 함정 재현
- [x] Superset ClickHouse 연결 Test → **200 OK**
- [x] deck.gl Polygon chart-data 쿼리 → **325행** (`coordinates` JSON + `name` + `MAX(metric)`)

**리버스 지오코딩** (`dictGet('geospatial.sig_dict','name',(lon,lat))`):

| 입력 좌표 (lon, lat) | 결과 | 기대 |
|---|---|---|
| `(127.289, 36.480)` | **세종시** | 세종(행정수도) ✓ |
| `(126.9780, 37.5665)` | **종로구** | 서울 중심 ✓ |
| `(129.0756, 35.1796)` | **연제구** | 부산 인근 ✓ |

**좌표계 함정** (geo 함수 스모크):

```
geoToH3(127.289, 36.480, 7)                  = 608482148894113791
pointInPolygon((127.289, 36.480), 한반도bbox)  = 1   ← WGS84 정상
pointInPolygon((612656, 1791892), 한반도bbox)  = 0   ← 5179 미터값 = 조용히 틀림
```

세종을 가리키는 동일 지점이라도 4326(degree)은 박스 안(1), 5179(미터)는 박스 밖(0)으로 판정 → **좌표계 미변환 시 에러 없이 틀린 결과**가 난다는 증거.

### 관측소(weather stations) 대시보드 — 포인트 시각화 + 시군구별 집계

전국에 임의 관측소 **3,000개**를 찍어 ① 포인트 시각화 ② 행정구역별 집계 ③ 둘을 오버레이한 대시보드를 만든다. 실제 관측소/센서/매장 lon·lat 데이터로 `weather_stations`만 바꾸면 그대로 운영용 대시보드가 된다.

```bash
docker exec -i kg-clickhouse clickhouse-client --multiquery < ddl/04_weather_stations.sql
python3 scripts/setup_dashboard.py
```

- `geospatial.weather_stations` — 관측소 3,000개. bbox 랜덤 점 중 **딕셔너리로 시군구에 분류된(=육지)** 점만 채택. 각 점에 합성 `temp_c`(위도↑ → 기온↓ + 노이즈), `elevation_m`, 그리고 `sigungu_code`/`sigungu_name`(분류 결과) 부여.
- `geospatial.sig_station_agg` — 시군구별 `station_count` / `avg_temp` / `avg_elev` 집계.
- `geospatial.sig_station_map` — `sig_map`(폴리곤 ring) ⨝ 집계 → deck.gl Polygon choropleth용(관측소 0개 시군구도 LEFT JOIN 포함).

**실측:** 관측소 3,000개, **217개** 시군구에 분포. 기온 범위 **-0.7 ~ 17.9 °C**(북부 강원 ~3 °C, 남부 ~9 °C). 상위 시군구(면적 큰 군 지역, 균등 랜덤이라 자연스러움): 인제군 53 · 홍천군 49 · 안동시 48 · 의성군 44 · 평창군 41 … Superset 4개 차트 + 대시보드 자동 생성, chart-data API 전부 200/데이터 반환 확인.

**엔드포인트 (admin/admin):**

| 항목 | URL |
|---|---|
| **대시보드 "전국 관측소 현황"** | http://localhost:8088/superset/dashboard/1/ |
| 오버레이 지도 (deck.gl Multi: choropleth + 관측소 포인트) | http://localhost:8088/explore/?slice_id=3 |
| 관측소 분포 (deck.gl Scatter) | http://localhost:8088/explore/?slice_id=1 |
| 시군구별 관측소 수 (deck.gl Polygon choropleth) | http://localhost:8088/explore/?slice_id=2 |
| 시군구별 TOP (Table) | http://localhost:8088/explore/?slice_id=4 |

> 레이아웃: 상단에 **오버레이 지도**(관측소 점 + 시군구별 색칠), 하단에 **choropleth + TOP 테이블**.
> 점/폴리곤은 토큰 없이도 렌더되지만, 배경 지도 타일은 `MAPBOX_API_KEY` 설정 시 표시된다.

`setup_dashboard.py`는 **멱등**이다. 관측소 데이터를 다시 뽑거나(`04_weather_stations.sql` 재실행) 실데이터로 교체한 뒤 스크립트를 다시 돌리면 중복 없이 같은 차트/대시보드가 갱신된다.

### deck.gl Polygon 차트 수동 구성 (UI)

1. http://localhost:8088 → **admin / admin** 로그인.
2. Charts → + Chart → dataset `sig_map`(또는 `sig_station_map`) → **deck.gl Polygon**:
   - **Polygon Column**: `coordinates`
   - **line_type / Polygon Encoding**: `json`
   - **Metric**: `MAX(metric)` (또는 `MAX(station_count)`)
   - linear color scheme + opacity 지정 → **Run**.
3. **눈 검증:** 시군구 경계가 한반도 위에 색칠되고, **세종 폴리곤이 충청 중앙**에 정확히 위치하면 좌표계가 시각적으로도 맞다는 증거.

Superset DB 연결 URI (서비스명 사용):
```
clickhousedb://default:@clickhouse:8123/geospatial
```

### 트러블슈팅 (이번 구축 중 실제로 만난 것 포함)

- **Superset가 `clickhousedb` dialect 못 찾음** → `clickhouse-connect` 미설치. `superset/requirements-local.txt` 반영 후 `docker compose build superset`.
- **연결되는데 host 못 찾음** → URI host를 `localhost`가 아닌 compose 서비스명 `clickhouse`로.
- **`test_connection`이 HTML redirect 반환** → 엔드포인트 끝에 **트레일링 슬래시** 필요(`/api/v1/database/test_connection/`). `setup_superset.py`에 반영됨.
- **`ALTER ... UPDATE`가 상관 서브쿼리 에러(UNKNOWN_IDENTIFIER)** → ClickHouse mutation은 상관 서브쿼리 미지원. `03_points_choropleth.sql`은 flat dictionary(`sig_counts_dict`) + `dictGetOrDefault`로 우회.
- **딕셔너리 비어 있음/조회 실패** → 데이터 적재 **후** `SYSTEM RELOAD DICTIONARY geospatial.sig_dict`. `LIFETIME(0)`은 자동 reload 안 함.
- **리버스 지오코딩 전부 틀림/공백** → 좌표계 미변환(5179) 의심. `load_geo.py`가 적재 전 첫 좌표 magnitude로 자동 차단함.
- **Superset REST 필터가 400 "Not a valid rison" / 재실행 시 차트 중복 생성** → 이름에 괄호가 있으면 rison 필터가 깨진다. `setup_dashboard.py`는 필터 값을 작은따옴표로 감싸(`find_id()`) 조회가 매칭되고 재실행이 제자리 갱신되도록 처리.
- **대시보드 패널에 "no chart definition associated with this component"** → API로 만든 차트는 대시보드에 명시적으로 연결해야 한다. `setup_dashboard.py`가 각 차트에 `dashboards:[id]`를 PUT 한다.

### 좌표계 변환이 필요한 소스를 받았다면 (EPSG:5179 → 4326)

이 랩 데이터(`southkorea/southkorea-maps`)는 이미 WGS84라 변환 불필요. 5179(미터) 소스를 쓸 경우 **적재 전**에 변환:

```bash
ogr2ogr -t_srs EPSG:4326 data/sig_4326.geojson sig_5179.shp
# 또는
python -c "import geopandas as gpd; gpd.read_file('sig_5179.shp').to_crs(4326).to_file('data/sig_4326.geojson', driver='GeoJSON')"
```

### 정리 / 범위

```bash
docker compose down            # 컨테이너만
docker compose down -v         # 볼륨(ClickHouse 데이터 + Superset 메타DB)까지 삭제
```

- 이번 랩은 **시군구(251개)** 단위. 읍면동(수천 개, vertex 폭증 → 단순화 필요)은 1차 범위에서 제외.
- 데이터 출처: [`southkorea/southkorea-maps`](https://github.com/southkorea/southkorea-maps) `kostat/2013` 시군구 GeoJSON(WGS84, 단순화본).
