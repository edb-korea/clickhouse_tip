#!/usr/bin/env python3
"""
GeoJSON(WGS84/EPSG:4326) 한국 시군구 경계 → ClickHouse 적재.

두 가지 표현으로 적재:
  ① geospatial.sig_polygons : 전체 MultiPolygon  ([polygon][ring][point(lon,lat)])
       → Polygon Dictionary 소스. 리버스 지오코딩(정확한 분류)에 사용.
  ② geospatial.sig_map      : 외곽 ring 1개 = 1행 (coordinates = [[lon,lat],...] JSON)
       → Superset deck.gl Polygon 시각화용.

의존성: clickhouse-connect (HTTP 8123) + 표준 json/random 만 사용.
사용: python3 scripts/load_geo.py [geojson_path] [--host HOST] [--port PORT]
"""
import argparse
import json
import os
import random
import sys

import clickhouse_connect

# 속성 필드 자동 탐지 후보 (southkorea-maps: code/name)
CODE_KEYS = ["code", "SIG_CD", "sig_cd", "adm_cd", "ADM_CD", "C_SIG_CD"]
NAME_KEYS = ["name", "SIG_KOR_NM", "sig_kor_nm", "adm_nm", "ADM_NM", "SIG_ENG_NM"]


def pick(props, candidates):
    for k in candidates:
        if k in props and props[k] not in (None, ""):
            return str(props[k])
    return None


def geom_to_multipolygon(geom):
    """GeoJSON geometry → [polygon][ring][[lon,lat],...] (Polygon 은 한 번 감쌈)."""
    t = geom["type"]
    coords = geom["coordinates"]
    if t == "Polygon":
        return [coords]          # → [[ring,...]]  (polygon 1개)
    if t == "MultiPolygon":
        return coords            # 이미 [polygon][ring][point]
    raise ValueError(f"지원하지 않는 geometry type: {t}")


def to_tuples(multipoly):
    """좌표 [lon,lat] 리스트를 (lon,lat) 튜플 중첩으로 (드라이버 nested 전달용)."""
    return [
        [[(float(pt[0]), float(pt[1])) for pt in ring] for ring in poly]
        for poly in multipoly
    ]


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    default_geo = os.path.join(here, "..", "data", "sig_4326.geojson")
    ap = argparse.ArgumentParser()
    ap.add_argument("geojson", nargs="?", default=default_geo)
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=8123)
    ap.add_argument("--user", default="default")
    ap.add_argument("--password", default="")
    args = ap.parse_args()

    with open(args.geojson, encoding="utf-8") as f:
        gj = json.load(f)
    feats = gj["features"]
    print(f"[load] {len(feats)} features from {os.path.relpath(args.geojson)}")

    # 좌표계 안전장치: 첫 좌표 magnitude 확인 (4326 이면 |lon|<180)
    first = None
    for f in feats:
        mp = geom_to_multipolygon(f["geometry"])
        if mp and mp[0] and mp[0][0]:
            first = mp[0][0][0]
            break
    if first and abs(first[0]) > 180:
        sys.exit(
            f"[load][FATAL] 첫 좌표 {first} 가 4326 범위를 벗어남(5179 미터로 추정). "
            "ogr2ogr -t_srs EPSG:4326 로 변환 후 다시 적재하세요."
        )
    print(f"[load] 좌표계 OK (sample={first}) → WGS84/4326")

    poly_rows = []   # (key, code, name)
    map_rows = []    # (code, name, metric, coordinates)
    seen_codes = set()
    for f in feats:
        props = f["properties"]
        code = pick(props, CODE_KEYS)
        name = pick(props, NAME_KEYS)
        if code is None or name is None:
            print(f"[load][warn] code/name 못 찾음, skip: {props}")
            continue
        seen_codes.add(code)
        mp = geom_to_multipolygon(f["geometry"])

        # ① 딕셔너리: 전체 MultiPolygon
        poly_rows.append((to_tuples(mp), code, name))

        # ② 시각화: 시군구별 안정 metric (같은 code → 같은 값)
        rnd = random.Random(code)
        metric = float(rnd.randint(1, 100))
        for poly in mp:
            outer = poly[0]  # 외곽 ring
            coordinates = json.dumps([[float(p[0]), float(p[1])] for p in outer])
            map_rows.append((code, name, metric, coordinates))

    client = clickhouse_connect.get_client(
        host=args.host, port=args.port, username=args.user, password=args.password
    )
    client.command("TRUNCATE TABLE IF EXISTS geospatial.sig_polygons")
    client.command("TRUNCATE TABLE IF EXISTS geospatial.sig_map")

    client.insert(
        "geospatial.sig_polygons",
        poly_rows,
        column_names=["key", "code", "name"],
    )
    client.insert(
        "geospatial.sig_map",
        map_rows,
        column_names=["code", "name", "metric", "coordinates"],
    )

    print(f"[load] sig_polygons rows = {len(poly_rows)}")
    print(f"[load] sig_map rings     = {len(map_rows)}")
    print(f"[load] 고유 시군구 수     = {len(seen_codes)} (기대 ≈ 250)")
    print("[load] done.")


if __name__ == "__main__":
    main()
