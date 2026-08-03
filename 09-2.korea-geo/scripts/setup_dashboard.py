#!/usr/bin/env python3
"""
Superset 대시보드 자동 구성 — "전국 관측소 현황".
구성:
  - deck.gl Scatter   : 관측소 3,000개 포인트 (weather_stations)
  - deck.gl Polygon   : 시군구별 관측소 수 choropleth (sig_station_map)
  - deck.gl Multi     : 위 둘을 한 지도에 오버레이 (포인트 + 행정구역 집계)
  - Table             : 시군구별 관측소 수 · 평균기온 TOP (sig_station_agg)
표준 라이브러리(urllib)만 사용. 멱등(이미 있으면 재사용).
사용: python3 scripts/setup_dashboard.py
"""
import json
import urllib.request
import urllib.error
import urllib.parse
import http.cookiejar

BASE = "http://localhost:8088"
URI = "clickhousedb://superset_user:data12!%40@localhost:8123/geospatial"
DB_NAME = "ClickHouse Connect (Superset)"
VIEWPORT = {"longitude": 127.8, "latitude": 36.3, "zoom": 6.3,
            "bearing": 0, "pitch": 0}
MAP_STYLE = "mapbox://styles/mapbox/light-v9"

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def req(method, path, token=None, csrf=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    if csrf:
        r.add_header("X-CSRFToken", csrf)
        r.add_header("Referer", BASE)
    try:
        with opener.open(r) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def find_id(kind, col, val, token, csrf):
    """rison eq 필터로 단건 조회 → id (없으면 None).
    값에 괄호/공백/한글이 들어가도 깨지지 않게 작은따옴표로 감싸고 안전하게 인코딩."""
    rison = "(filters:!((col:%s,opr:eq,value:'%s')))" % (col, val.replace("'", "\\'"))
    q = urllib.parse.quote(rison, safe="():!,'")
    st, j = req("GET", f"/api/v1/{kind}/?q={q}", token, csrf)
    res = j.get("result") if st == 200 else None
    return res[0]["id"] if res else None


def login():
    _, j = req("POST", "/api/v1/security/login",
               body={"username": "admin", "password": "admin",
                     "provider": "db", "refresh": True})
    token = j["access_token"]
    _, j = req("GET", "/api/v1/security/csrf_token/", token=token)
    return token, j["result"]


def get_db_id(token, csrf):
    db_id = find_id("database", "database_name", DB_NAME, token, csrf)
    if db_id:
        return db_id

    st, j = req("POST", "/api/v1/database/", token, csrf,
                {"database_name": DB_NAME, "sqlalchemy_uri": URI,
                 "expose_in_sqllab": True})
    if st not in (200, 201):
        raise RuntimeError(f"database create failed: status={st}, response={j}")
    return j["id"]


def ensure_dataset(token, csrf, db_id, table):
    st, j = req("POST", "/api/v1/dataset/", token, csrf,
                {"database": db_id, "schema": "geospatial", "table_name": table})
    if st in (200, 201):
        print(f"[dash] dataset {table} created id={j['id']}")
        return j["id"]
    # 이미 있으면 조회
    ds_id = find_id("dataset", "table_name", table, token, csrf)
    print(f"[dash] dataset {table} reuse id={ds_id}")
    return ds_id


def ensure_chart(token, csrf, name, viz_type, ds_id, params):
    params = dict(params, datasource=f"{ds_id}__table", viz_type=viz_type)
    body = {"slice_name": name, "viz_type": viz_type,
            "datasource_id": ds_id, "datasource_type": "table",
            "params": json.dumps(params)}
    # 동명 차트 있으면 갱신
    cid = find_id("chart", "slice_name", name, token, csrf)
    if cid:
        req("PUT", f"/api/v1/chart/{cid}", token, csrf, body)
        print(f"[dash] chart '{name}' updated id={cid}")
        return cid
    st, j = req("POST", "/api/v1/chart/", token, csrf, body)
    print(f"[dash] chart '{name}' created id={j.get('id', j)}")
    return j["id"]


def metric(agg, col, typ="Float64"):
    return {"aggregate": agg, "column": {"column_name": col, "type": typ},
            "expressionType": "SIMPLE", "label": f"{agg}({col})"}


def main():
    token, csrf = login()
    db_id = get_db_id(token, csrf)
    print(f"[dash] db_id={db_id}")

    ds_ws = ensure_dataset(token, csrf, db_id, "weather_stations")
    ds_map = ensure_dataset(token, csrf, db_id, "sig_station_map")
    ds_agg = ensure_dataset(token, csrf, db_id, "sig_station_agg")

    # 1) deck.gl Scatter — 관측소 포인트
    scatter = ensure_chart(
        token, csrf, "전국 관측소 분포 (deck.gl Scatter)", "deck_scatter", ds_ws, {
            "spatial": {"type": "latlong", "lonCol": "lon", "latCol": "lat"},
            "adhoc_filters": [], "row_limit": 5000,
            "point_radius_fixed": {"type": "fix", "value": 2500},
            "point_unit": "radius_m", "min_radius": 2, "max_radius": 30,
            "multiplier": 1, "color_picker": {"r": 220, "g": 30, "b": 30, "a": 1},
            "viewport": VIEWPORT, "autozoom": False, "mapbox_style": MAP_STYLE,
            "js_columns": [],
        })

    # 2) deck.gl Polygon — 시군구별 관측소 수 choropleth
    polygon = ensure_chart(
        token, csrf, "시군구별 관측소 수 (choropleth)", "deck_polygon", ds_map, {
            "line_column": "coordinates", "line_type": "json",
            "reverse_long_lat": False, "adhoc_filters": [], "row_limit": 10000,
            "metric": metric("MAX", "station_count"),
            "point_radius_fixed": {"type": "metric", "value": metric("MAX", "station_count")},
            "filled": True, "stroked": True, "extruded": False, "multiplier": 1,
            "line_width": 1, "fill_color_picker": {"r": 3, "g": 65, "b": 73, "a": 1},
            "stroke_color_picker": {"r": 255, "g": 255, "b": 255, "a": 1},
            "linear_color_scheme": "blue_white_yellow", "opacity": 70,
            "num_buckets": 10, "viewport": VIEWPORT, "autozoom": False,
            "mapbox_style": MAP_STYLE, "js_columns": [],
        })

    # 3) deck.gl Multi — 오버레이 (choropleth + 관측소 포인트)
    multi = ensure_chart(
        token, csrf, "전국 관측소 + 시군구 집계 오버레이 (deck.gl Multi)", "deck_multi", ds_map, {
            "deck_slices": [polygon, scatter], "adhoc_filters": [],
            "viewport": VIEWPORT, "mapbox_style": MAP_STYLE, 
        })

    # 4) Table — 시군구별 TOP
    table = ensure_chart(
        token, csrf, "시군구별 관측소 수 · 평균기온 TOP", "table", ds_agg, {
            "query_mode": "aggregate", "groupby": ["sigungu_name"],
            "metrics": [metric("MAX", "station_count", "UInt64"),
                        metric("AVG", "avg_temp")],
            "adhoc_filters": [], "row_limit": 25, "order_desc": True,
            "timeseries_limit_metric": metric("MAX", "station_count", "UInt64"),
        })

    # 5) 대시보드 (position_json 으로 레이아웃 배치)
    def chart_node(nid, chart_id, name, w, h):
        return {"type": "CHART", "id": nid, "children": [],
                "meta": {"chartId": chart_id, "width": w, "height": h,
                         "sliceName": name},
                "parents": ["ROOT_ID", "GRID_ID", nid.replace("CHART", "ROW")]}

    pos = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID": {"type": "GRID", "id": "GRID_ID",
                    "children": ["ROW-A", "ROW-B"], "parents": ["ROOT_ID"]},
        "HEADER_ID": {"type": "HEADER", "id": "HEADER_ID",
                      "meta": {"text": "전국 관측소 현황"}},
        "ROW-A": {"type": "ROW", "id": "ROW-A", "children": ["CHART-multi"],
                  "parents": ["ROOT_ID", "GRID_ID"],
                  "meta": {"background": "BACKGROUND_TRANSPARENT"}},
        "CHART-multi": chart_node("CHART-multi", multi,
                                  "관측소 + 시군구 집계 오버레이", 12, 70),
        "ROW-B": {"type": "ROW", "id": "ROW-B",
                  "children": ["CHART-poly", "CHART-tbl"],
                  "parents": ["ROOT_ID", "GRID_ID"],
                  "meta": {"background": "BACKGROUND_TRANSPARENT"}},
        "CHART-poly": chart_node("CHART-poly", polygon,
                                 "시군구별 관측소 수", 7, 60),
        "CHART-tbl": chart_node("CHART-tbl", table,
                                "시군구별 TOP", 5, 60),
    }

    title = "전국 관측소 현황 (Korea Weather Stations)"
    body = {"dashboard_title": title, "published": True,
            "position_json": json.dumps(pos),
            "css": "", "json_metadata": json.dumps({"refresh_frequency": 0})}
    did = find_id("dashboard", "dashboard_title", title, token, csrf)
    if did:
        req("PUT", f"/api/v1/dashboard/{did}", token, csrf, body)
        print(f"[dash] dashboard updated id={did}")
    else:
        st, j = req("POST", "/api/v1/dashboard/", token, csrf, body)
        did = j["id"]
        print(f"[dash] dashboard created id={did}")

    # position_json 의 차트들을 대시보드에 명시적으로 연관(이걸 안 하면
    # "no chart definition associated with this component" 로 빈 화면이 뜬다).
    for cid in (polygon, multi, table):
        req("PUT", f"/api/v1/chart/{cid}", token, csrf, {"dashboards": [did]})
    print(f"[dash] linked charts {scatter},{polygon},{multi},{table} -> dashboard {did}")

    print(f"\n[dash] 완료 → http://localhost:8088/superset/dashboard/{did}/")
    print(f"[dash] 오버레이 지도 단독: http://localhost:8088/explore/?slice_id={multi}")


if __name__ == "__main__":
    main()
