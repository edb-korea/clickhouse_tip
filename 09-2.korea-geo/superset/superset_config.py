import os

# 로컬 랩: 메타데이터는 superset_home 의 SQLite 로 충분(볼륨에 영속).
# 운영이라면 postgres 권장.
SECRET_KEY = os.environ.get("SUPERSET_SECRET_KEY", "korea_geo_lab_secret_change_me")
SQLALCHEMY_DATABASE_URI = "sqlite:////app/superset_home/superset.db"

# deck.gl 베이스맵 타일 토큰. 비어 있으면 폴리곤은 렌더되지만 지도 배경은 제한될 수 있음.
MAPBOX_API_KEY = os.environ.get("MAPBOX_API_KEY", "")

# SQLite 메타DB 에서 동시쓰기 경고 억제 + Superset 가 거부하지 않도록.
SQLALCHEMY_ENGINE_OPTIONS = {"connect_args": {"check_same_thread": False}}
PREVENT_UNSAFE_DB_CONNECTIONS = False

FEATURE_FLAGS = {
    "DASHBOARD_NATIVE_FILTERS": True,
    "DASHBOARD_CROSS_FILTERS": True,
}

WTF_CSRF_ENABLED = True
WTF_CSRF_TIME_LIMIT = None

# 비-dev 환경 안내 배너 제거
TALISMAN_ENABLED = False
