#!/usr/bin/env python3
"""
실시간 흉내용 관측소 데이터 producer.

주기적으로 geospatial.weather_stations에 새 관측소 row를 insert하고,
Superset 대시보드가 보는 집계 테이블(sig_station_agg, sig_station_map)을 갱신한다.

사용 예:
  python3 scripts/stream_weather.py --password 'data12!@'
"""
import argparse
import time

import clickhouse_connect


def insert_batch(client, batch_size):
    start_id = int(client.query(
        "SELECT ifNull(max(station_id), 0) FROM geospatial.weather_stations"
    ).result_rows[0][0])

    sql = f"""
    INSERT INTO geospatial.weather_stations
    SELECT
        {start_id} + rn AS station_id,
        concat('LIVE-', leftPad(toString({start_id} + rn), 6, '0')) AS name,
        lon,
        lat,
        code AS sigungu_code,
        sname AS sigungu_name,
        round(16.0 - (lat - 33.0) * 2.6 + (rand() / 4294967295.0 - 0.5) * 6, 1) AS temp_c,
        round((rand() / 4294967295.0) * 800, 0) AS elevation_m
    FROM
    (
        SELECT
            rowNumberInAllBlocks() + 1 AS rn,
            lon,
            lat,
            code,
            sname
        FROM
        (
            SELECT
                lon,
                lat,
                dictGet('geospatial.sig_dict', 'code', (lon, lat)) AS code,
                dictGet('geospatial.sig_dict', 'name', (lon, lat)) AS sname
            FROM
            (
                SELECT
                    124.6 + (rand()  / 4294967295.0) * (130.9 - 124.6) AS lon,
                    33.2  + (rand(1) / 4294967295.0) * (38.6  - 33.2)  AS lat
                FROM numbers({batch_size * 30})
            )
            WHERE code != ''
            LIMIT {batch_size}
        )
    )
    """
    client.command(sql)
    return start_id + 1, start_id + batch_size


def refresh_rollups(client):
    client.command("TRUNCATE TABLE geospatial.sig_station_agg")
    client.command("""
    INSERT INTO geospatial.sig_station_agg
    SELECT
        sigungu_code,
        any(sigungu_name)       AS sigungu_name,
        count()                 AS station_count,
        round(avg(temp_c), 1)   AS avg_temp,
        round(avg(elevation_m)) AS avg_elev
    FROM geospatial.weather_stations
    GROUP BY sigungu_code
    """)

    client.command("TRUNCATE TABLE geospatial.sig_station_map")
    client.command("""
    INSERT INTO geospatial.sig_station_map
    SELECT
        m.code                                AS code,
        m.name                                AS name,
        m.coordinates                         AS coordinates,
        toFloat64(ifNull(a.station_count, 0)) AS station_count,
        ifNull(a.avg_temp, 0)                 AS avg_temp
    FROM geospatial.sig_map AS m
    LEFT JOIN geospatial.sig_station_agg AS a ON a.sigungu_code = m.code
    """)


def summary(client):
    row = client.query("""
        SELECT
            count() AS stations,
            uniqExact(sigungu_code) AS covered_sigungu,
            round(avg(temp_c), 1) AS avg_temp
        FROM geospatial.weather_stations
    """).result_rows[0]
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=8123)
    ap.add_argument("--user", default="default")
    ap.add_argument("--password", default="")
    ap.add_argument("--batch-size", type=int, default=50)
    ap.add_argument("--interval", type=float, default=5.0)
    ap.add_argument("--refresh-every", type=int, default=1,
                    help="몇 batch마다 Superset용 집계 테이블을 갱신할지")
    ap.add_argument("--max-batches", type=int, default=0,
                    help="0이면 Ctrl-C 전까지 계속 실행")
    args = ap.parse_args()

    client = clickhouse_connect.get_client(
        host=args.host,
        port=args.port,
        username=args.user,
        password=args.password,
    )

    print(
        "[stream] start "
        f"host={args.host}:{args.port} batch_size={args.batch_size} interval={args.interval}s"
    )
    print("[stream] stop: Ctrl-C")

    batch_no = 0
    try:
        while True:
            batch_no += 1
            first_id, last_id = insert_batch(client, args.batch_size)
            if batch_no % args.refresh_every == 0:
                refresh_rollups(client)
            stations, covered, avg_temp = summary(client)
            print(
                f"[stream] batch={batch_no} inserted={first_id}-{last_id} "
                f"stations={stations} covered_sigungu={covered} avg_temp={avg_temp}"
            )
            if args.max_batches and batch_no >= args.max_batches:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n[stream] stopped")


if __name__ == "__main__":
    main()

