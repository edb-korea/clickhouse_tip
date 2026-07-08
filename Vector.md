# Vector로 ClickHouse 연동하기

[Vector](https://vector.dev)는 로그, 메트릭, 트레이스를 수집·변환하여 다양한 목적지(sink)로 라우팅하는 데이터 파이프라인 도구이며, ClickHouse도 기본 지원 대상 중 하나입니다.

## 1. Vector 설치

```bash
bash -c "$(curl -L https://setup.vector.dev)"
sudo apt install vector
```

## 2. ClickHouse에 대상 테이블 생성

먼저 데이터를 받을 테이블을 ClickHouse에 만들어둡니다.

```sql
CREATE TABLE IF NOT EXISTS nginxdb.access_logs
(
    message String
)
ENGINE = MergeTree()
ORDER BY tuple()
```

## 3. vector.toml 설정

설정 파일(`/etc/vector/vector.toml`)에는 크게 **source**(입력), **transform**(가공, 선택), **sink**(출력) 세 블록을 정의합니다.

### 예시 1 — 파일(nginx 로그) → ClickHouse

```toml
[sources.nginx_logs]
type = "file"
include = ["/var/log/nginx/my_access.log"]
read_from = "end"

[sinks.clickhouse]
type = "clickhouse"
inputs = ["nginx_logs"]
endpoint = "http://clickhouse-server:8123"
database = "nginxdb"
table = "access_logs"
skip_unknown_fields = true
```

### 예시 2 — Kafka → ClickHouse

```toml
[sources.kafka_messages]
type = "kafka"
auto_offset_reset = "beginning"
bootstrap_servers = "kafka:9092"
group_id = "test_1"
topics = ["test_topic"]
decoding.codec = "json"

[sinks.clickhouse]
type = "clickhouse"
inputs = ["kafka_messages"]
endpoint = "http://clickhouse:8123"
database = "default"
table = "vectors_table"
auth.strategy = "basic"
auth.user = "default"
auth.password = "your_password"
```

## 4. 인증 및 TLS (ClickHouse Cloud 등 보안 연결 시)

```toml
[sinks.clickhouse]
type = "clickhouse"
inputs = ["<your_vector_source>"]
endpoint = "https://<clickhouse_host>:8443"
database = "<database_name>"
table = "<table_name>"
auth.strategy = "basic"
auth.user = "username"
auth.password = "password"
```

## 5. 주요 설정 옵션

| 옵션 | 설명 |
|---|---|
| `endpoint` | ClickHouse HTTP 인터페이스 주소 (보통 8123, TLS는 8443) |
| `database` / `table` | 삽입 대상 DB/테이블 |
| `skip_unknown_fields` | 테이블 스키마에 없는 필드를 무시하도록 설정 |
| `compression` | `zstd`, `gzip` 등 압축 방식 지정 (실무에서 `zstd` 많이 사용) |
| `auth.strategy` / `auth.user` / `auth.password` | Basic Auth 인증 정보 |
| `batch.max_bytes` / `batch.timeout_secs` | 배치 삽입 크기·주기 조정 |
| `buffer` | 장애 시 유실 방지용 버퍼(`memory` 또는 `disk`) 설정 |
| `async_insert` 관련 옵션 | ClickHouse가 삽입 데이터를 큐에 쌓았다가 백그라운드로 flush하도록 하는 `async_insert` 설정 등 지원 |

## 6. 실행 및 확인

```bash
vector --config /etc/vector/vector.toml
```

이후 ClickHouse에서 확인:

```sql
SELECT * FROM nginxdb.access_logs LIMIT 10;
```

## 참고 — 실무 팁

- 대용량/고트래픽 환경에서는 `buffer.type = "disk"`로 설정해 Vector 프로세스 재시작이나 ClickHouse 장애 시에도 데이터 유실을 방지하는 걸 권장합니다.
- 여러 ClickHouse 노드로 이중화하려는 경우, 두 개의 sink 블록을 각각 다른 endpoint로 만들면 되지만, 두 sink는 완전히 독립적으로 동작하며 서로 동기화되지 않고, 한쪽 sink가 막히면(backpressure) 같은 source를 공유하는 다른 sink에도 영향을 줍니다.
- 문자열 그대로 저장하는 것보다, 이후 Materialized View로 구조화해서 분석하기 좋은 컬럼으로 파싱하는 것을 추천합니다.
