# ClickHouse INSERT, UPDATE, DELETE 예제

ClickHouse의 INSERT/UPDATE/DELETE는 문법은 표준 SQL과 비슷하지만, **내부 동작 방식(즉시 반영 vs 백그라운드 처리)이 방식별로 다르다**는 점이 중요합니다.

## 0. 예제 테이블 생성

```sql
CREATE TABLE orders (
    order_id    UInt64,
    customer_id UInt32,
    product     String,
    quantity    UInt32,
    price       Decimal(10,2),
    status      LowCardinality(String),   -- 'pending','shipped','cancelled'
    created_at  DateTime
) ENGINE = MergeTree()
ORDER BY (customer_id, order_id);
```

---

## 1. INSERT

### 단건 삽입
```sql
INSERT INTO orders (order_id, customer_id, product, quantity, price, status, created_at)
VALUES (1, 1001, 'Laptop', 1, 1200.00, 'pending', now());
```

### 다건(배치) 삽입 — 실무에서 훨씬 권장
```sql
INSERT INTO orders (order_id, customer_id, product, quantity, price, status, created_at)
VALUES
    (2, 1002, 'Mouse',    2,   25.00, 'pending', now()),
    (3, 1003, 'Keyboard', 1,   80.00, 'shipped', now()),
    (4, 1001, 'Monitor',  1,  350.00, 'pending', now());
```

### SELECT 결과로 삽입 (다른 테이블에서 이전)
```sql
INSERT INTO orders
SELECT * FROM orders_staging
WHERE created_at >= today();
```

### 대량 파일 삽입 (CSV 등)
```sql
INSERT INTO orders FORMAT CSVWithNames;
```
```bash
clickhouse-client --query="INSERT INTO orders FORMAT CSV" < orders.csv
```

**참고**: 성공한 INSERT는 클라이언트에 응답하기 전에 파일시스템에 기록되므로 durability가 보장됩니다. 다만 ClickHouse는 **작은 단건 INSERT를 자주 실행하는 것보다, 어느 정도 모아서(수천~수만 행) 배치로 넣는 것이 훨씬 효율적**입니다 (파트가 너무 많이 생기면 병합 부담 증가).

---

## 2. UPDATE

### 방법 A. 경량(Lightweight) UPDATE — v25.7 이상, 빠름 (권장)
```sql
UPDATE orders
SET status = 'shipped'
WHERE order_id = 2;
```
- 변경된 컬럼과 시스템 컬럼만 저장하는 patch part 방식으로, 파트 전체를 재작성하지 않아 단건 업데이트가 매우 빠릅니다(최대 1,000~2,400배 성능 향상).
- SELECT에 거의 즉시 반영됩니다.

### 방법 B. ALTER TABLE ... UPDATE (mutation, 구버전/대량 갱신용)
```sql
ALTER TABLE orders
UPDATE status = 'cancelled'
WHERE status = 'pending' AND created_at < now() - INTERVAL 30 DAY;
```
- 이 방식은 **백그라운드 비동기 처리**입니다. 즉시 반영되지 않고, 실행 후 처리 상태를 아래로 확인해야 합니다:
```sql
SELECT * FROM system.mutations WHERE table = 'orders' AND is_done = 0;
```
- 대량(수백만 행) 갱신에는 이 방식이 여전히 적합하지만, 단건/소량 갱신에는 방법 A(경량 UPDATE)가 훨씬 빠릅니다.

### 여러 컬럼 동시 갱신
```sql
UPDATE orders
SET status = 'shipped', quantity = quantity + 1
WHERE order_id = 3;
```

---

## 3. DELETE

### 방법 A. 경량(Lightweight) DELETE — v22.8 이상 GA, 권장
```sql
DELETE FROM orders
WHERE order_id = 4;
```
- 행을 즉시 삭제된 것으로 표시하지만, 실제 디스크에서 물리적으로 제거되는 건 다음 병합(merge) 시점입니다. SELECT에는 즉시 반영되어 안 보입니다.

### 방법 B. ALTER TABLE ... DELETE (mutation, 대량 삭제용)
```sql
ALTER TABLE orders
DELETE WHERE status = 'cancelled' AND created_at < now() - INTERVAL 90 DAY;
```
- 방법 A와 마찬가지로 백그라운드 비동기 처리이며, 대량 삭제(수백만~수십억 행) 시 더 안정적일 수 있습니다.

### 파티션 전체 삭제 — 대량 삭제의 가장 빠른 방법
```sql
ALTER TABLE orders DROP PARTITION '202601';   -- 특정 파티션 통째로 삭제 (즉시, 매우 빠름)
```
날짜 기준으로 파티셔닝해뒀다면, 오래된 데이터를 지울 때 `DELETE`보다 `DROP PARTITION`이 훨씬 빠르고 가볍습니다.

### 테이블 전체 비우기
```sql
TRUNCATE TABLE orders;
```

---

## 4. 처리 상태/진행 확인 (mutation 방식 사용 시 필수)

```sql
-- 진행 중인 mutation(UPDATE/DELETE) 확인
SELECT database, table, mutation_id, command, is_done, latest_fail_reason
FROM system.mutations
WHERE table = 'orders'
ORDER BY create_time DESC;

-- 특정 mutation 강제 종료(주의해서 사용)
KILL MUTATION WHERE mutation_id = '0000000001';
```

---

## 5. 실무 선택 기준 요약

| 상황 | 권장 방법 |
|---|---|
| 몇 건~수백 건 단위, 빠른 반영 필요 | `UPDATE ... SET ...` / `DELETE FROM ...` (경량 방식) |
| 수백만 건 이상 대량 갱신/삭제 | `ALTER TABLE ... UPDATE/DELETE` (mutation) |
| 특정 기간 데이터 통째로 삭제 (예: 보관기간 만료) | `ALTER TABLE ... DROP PARTITION` |
| 빈번한 갱신이 예상되는 테이블 설계 시 | `ReplacingMergeTree` (버전 컬럼으로 최신값만 유지)로 아예 테이블 엔진 자체를 바꾸는 것도 고려 |

**버전 확인 필수**: 경량 `UPDATE` 문법은 25.7~25.8부터 도입된 비교적 최신 기능이라, 사용 중인 ClickHouse 버전이 이보다 낮다면 `ALTER TABLE ... UPDATE`(mutation) 방식만 사용 가능합니다.

```sql
SELECT version();  -- 현재 버전 확인
```
