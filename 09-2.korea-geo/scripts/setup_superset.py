#!/usr/bin/env python3
"""
Superset 자동 구성: ClickHouse 연결 생성 + sig_map 데이터셋 등록.
표준 라이브러리(urllib)만 사용. 멱등(이미 있으면 재사용).
사용: python3 scripts/setup_superset.py
"""
import json
import urllib.request
import urllib.error
import http.cookiejar

BASE = "http://localhost:8088"
URI = "clickhousedb://default:@clickhouse:8123/geospatial"
DB_NAME = "clickhouse_geo"

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def req(method, path, token=None, csrf=None, body=None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
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


# 1) login
_, j = req("POST", "/api/v1/security/login",
           body={"username": "admin", "password": "admin",
                 "provider": "db", "refresh": True})
token = j["access_token"]
# 2) csrf (note trailing slash)
_, j = req("GET", "/api/v1/security/csrf_token/", token=token)
csrf = j["result"]
print("[setup] logged in, csrf acquired")

# 3) test connection (trailing slash!)
st, j = req("POST", "/api/v1/database/test_connection/", token, csrf,
            {"sqlalchemy_uri": URI, "database_name": DB_NAME})
print(f"[setup] test_connection -> {st} {j.get('message', j)}")

# 4) create (or find) database
st, j = req("POST", "/api/v1/database/", token, csrf,
            {"database_name": DB_NAME, "sqlalchemy_uri": URI,
             "expose_in_sqllab": True})
if st in (200, 201):
    db_id = j["id"]
    print(f"[setup] database created id={db_id}")
else:
    print(f"[setup] database create -> {st} {j.get('message', j)}; 기존 조회")
    flt = '(filters:!((col:database_name,opr:eq,value:%s)))' % DB_NAME
    st, j = req("GET", "/api/v1/database/?q=" + urllib.parse.quote(flt), token, csrf)
    db_id = j["result"][0]["id"]
    print(f"[setup] reuse database id={db_id}")

# 5) create dataset sig_map
for tbl in ["sig_map"]:
    st, j = req("POST", "/api/v1/dataset/", token, csrf,
                {"database": db_id, "schema": "geospatial", "table_name": tbl})
    if st in (200, 201):
        print(f"[setup] dataset {tbl} created id={j['id']}")
    else:
        print(f"[setup] dataset {tbl} -> {st} {j.get('message', j)} (이미 있을 수 있음)")

print("[setup] done. UI: http://localhost:8088  (admin/admin)")
