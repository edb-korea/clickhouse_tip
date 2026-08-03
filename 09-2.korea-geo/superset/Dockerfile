# apache/superset 공식 이미지에 ClickHouse 드라이버(clickhouse-connect)만 추가.
# 버전은 deck.gl Polygon 차트가 안정적으로 동작하는 4.x 로 고정.
FROM apache/superset:4.1.1

USER root
COPY requirements-local.txt /app/requirements-local.txt
RUN pip install --no-cache-dir -r /app/requirements-local.txt

COPY superset_config.py /app/pythonpath/superset_config.py
COPY bootstrap.sh /app/bootstrap.sh
RUN chmod +x /app/bootstrap.sh

ENV SUPERSET_CONFIG_PATH=/app/pythonpath/superset_config.py

USER superset
ENTRYPOINT []
CMD ["/app/bootstrap.sh"]
