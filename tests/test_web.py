from datetime import datetime, timezone

from fastapi.testclient import TestClient

from agent_usage_monitor.models import Agent, SourceStatus, TokenUsage, UsageEvent
from agent_usage_monitor.snapshot import build_snapshot
from agent_usage_monitor.web import _available_port, create_app


class FixtureService:
    def __init__(self) -> None:
        self.requests = []

    def measure(self, request, *, max_age=0):
        self.requests.append((request, max_age))
        event = UsageEvent(
            id="web",
            agent=Agent.OPENCODE,
            timestamp=datetime.now(timezone.utc),
            usage=TokenUsage(input=400, output=50, cache_read=100),
            model="openai/gpt-5",
            project="monitor",
        )
        status = SourceStatus(
            agent=Agent.OPENCODE,
            paths=["/local/opencode.db"],
            files_scanned=1,
            records_read=1,
            events=1,
        )
        return [event], build_snapshot(
            [event],
            [status],
            granularity=request.granularity,
            range_label=request.range_name,
            model_filters=request.models,
        )


def test_web_health_snapshot_and_options(tmp_path):
    (tmp_path / "index.html").write_text("<h1>monitor</h1>")
    service = FixtureService()
    client = TestClient(create_app(service=service, static_dir=tmp_path))

    health = client.get("/api/v1/health")
    snapshot = client.get(
        "/api/v1/snapshot",
        params={"agent": "opencode", "range": "24h", "granularity": "hour"},
    )
    options = client.get("/api/v1/options", params={"agent": "opencode"})
    home = client.get("/")

    assert health.json()["scope"] == "localhost"
    assert health.headers["content-security-policy"].startswith("default-src 'self'")
    assert snapshot.status_code == 200
    assert snapshot.json()["schema_version"] == 2
    assert snapshot.json()["selection"]["granularity"] == "hour"
    assert options.json()["models"] == ["openai/gpt-5"]
    assert home.text == "<h1>monitor</h1>"
    assert service.requests[0][0].agents == [Agent.OPENCODE]


def test_web_rejects_invalid_filters():
    client = TestClient(create_app(service=FixtureService()))

    unknown = client.get("/api/v1/snapshot", params={"agent": "other"})
    granularity = client.get("/api/v1/snapshot", params={"granularity": "minute"})
    custom = client.get("/api/v1/snapshot", params={"range": "custom"})

    assert unknown.status_code == 400
    assert granularity.status_code == 400
    assert custom.status_code == 400


def test_available_port_uses_loopback_and_accepts_ephemeral_port():
    port = _available_port(0)

    assert 0 < port <= 65535
