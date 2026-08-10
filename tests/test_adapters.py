import json
import sqlite3

from agent_usage_monitor.adapters.claude import ClaudeAdapter
from agent_usage_monitor.adapters.codex import CodexAdapter
from agent_usage_monitor.adapters.ide import TraeAdapter
from agent_usage_monitor.adapters.opencode import OpenCodeAdapter
from agent_usage_monitor.models import Accuracy


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")


def test_claude_exact_usage_and_deduplication(tmp_path):
    record = {
        "timestamp": "2026-08-08T10:00:00Z",
        "sessionId": "session-a",
        "cwd": "/work/project",
        "requestId": "req-a",
        "message": {
            "id": "msg-a",
            "model": "claude-sonnet-4-5",
            "usage": {
                "input_tokens": 100,
                "output_tokens": 20,
                "cache_read_input_tokens": 50,
                "cache_creation_input_tokens": 10,
            },
        },
    }
    write_jsonl(tmp_path / "session.jsonl", [record, record])
    adapter = ClaudeAdapter([tmp_path])

    events = adapter.collect()

    assert len(events) == 1
    assert events[0].usage.total == 180
    assert events[0].project == "/work/project"


def test_codex_uses_cumulative_delta_and_ignores_duplicate_snapshot(tmp_path):
    records = [
        {
            "timestamp": "2026-08-08T10:00:00Z",
            "type": "session_meta",
            "payload": {"id": "codex-a", "cwd": "/work/project"},
        },
        {
            "timestamp": "2026-08-08T10:00:30Z",
            "type": "turn_context",
            "payload": {"model": "gpt-5.6-sol"},
        },
        _codex_token_record("2026-08-08T10:01:00Z", 100, 20, 40),
        _codex_token_record("2026-08-08T10:02:00Z", 100, 20, 40),
        {
            "timestamp": "2026-08-08T10:02:30Z",
            "type": "event_msg",
            "payload": {
                "type": "thread_settings_applied",
                "thread_settings": {"model": "gpt-5.6-terra"},
            },
        },
        _codex_token_record("2026-08-08T10:03:00Z", 180, 30, 80),
    ]
    write_jsonl(tmp_path / "rollout.jsonl", records)
    adapter = CodexAdapter([tmp_path])

    events = adapter.collect()

    assert len(events) == 2
    assert [event.usage.total for event in events] == [120, 90]
    assert sum(event.usage.total for event in events) == 210
    assert events[0].usage.cache_read == 40
    assert [event.model for event in events] == ["gpt-5.6-sol", "gpt-5.6-terra"]


def _codex_token_record(timestamp, input_tokens, output_tokens, cached):
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "total_token_usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cached_input_tokens": cached,
                    "reasoning_output_tokens": 5,
                }
            },
        },
    }


def test_codex_backfills_initial_events_from_first_explicit_model(tmp_path):
    records = [
        _codex_token_record("2026-08-08T10:00:00Z", 100, 20, 40),
        {
            "timestamp": "2026-08-08T10:01:00Z",
            "type": "turn_context",
            "payload": {"model": "gpt-5.6-sol"},
        },
    ]
    write_jsonl(tmp_path / "rollout.jsonl", records)

    events = CodexAdapter([tmp_path]).collect()

    assert len(events) == 1
    assert events[0].model == "gpt-5.6-sol"


def test_opencode_message_tokens(tmp_path):
    path = tmp_path / "message" / "msg.json"
    path.parent.mkdir()
    path.write_text(
        json.dumps(
            {
                "id": "message-a",
                "sessionID": "session-a",
                "modelID": "gpt-5",
                "time": {"completed": 1786183200000},
                "tokens": {
                    "input": 50,
                    "output": 10,
                    "reasoning": 4,
                    "cache": {"read": 20, "write": 2},
                },
                "cost": 0.012,
            }
        ),
        encoding="utf-8",
    )
    adapter = OpenCodeAdapter([tmp_path])

    events = adapter.collect()

    assert len(events) == 1
    assert events[0].usage.total == 82
    assert events[0].usage.reasoning == 4
    assert events[0].cost_usd == 0.012


def test_opencode_current_sqlite_session_totals(tmp_path, monkeypatch):
    database = tmp_path / "opencode.db"
    connection = sqlite3.connect(database)
    connection.execute(
        """CREATE TABLE session (
        id TEXT PRIMARY KEY, directory TEXT, time_created INTEGER, time_updated INTEGER,
        cost REAL, tokens_input INTEGER, tokens_output INTEGER, tokens_reasoning INTEGER,
        tokens_cache_read INTEGER, tokens_cache_write INTEGER, model TEXT)"""
    )
    connection.execute(
        "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "session-db-a",
            "/work/opencode",
            1786183000000,
            1786183200000,
            0.25,
            100,
            20,
            5,
            30,
            2,
            json.dumps({"providerID": "openai", "id": "gpt-5"}),
        ),
    )
    connection.commit()
    connection.close()

    # SQLite is queried lazily and can legitimately grow into the GB range. The
    # safety limit for whole-file JSON reads must never hide the database.
    monkeypatch.setattr("agent_usage_monitor.adapters.base.MAX_LOG_BYTES", 1)

    events = OpenCodeAdapter([tmp_path]).collect()

    assert len(events) == 1
    assert events[0].usage.total == 152
    assert events[0].usage.reasoning == 5
    assert events[0].model == "openai/gpt-5"
    assert events[0].metadata["cumulative"] is True


def test_opencode_prefers_message_events_over_cumulative_sessions(tmp_path):
    database = tmp_path / "opencode.db"
    connection = sqlite3.connect(database)
    connection.execute(
        """CREATE TABLE session (
        id TEXT PRIMARY KEY, directory TEXT, time_created INTEGER, time_updated INTEGER,
        cost REAL, tokens_input INTEGER, tokens_output INTEGER, tokens_reasoning INTEGER,
        tokens_cache_read INTEGER, tokens_cache_write INTEGER, model TEXT)"""
    )
    connection.execute(
        """CREATE TABLE message (
        id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER, time_updated INTEGER,
        data TEXT)"""
    )
    connection.execute(
        "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("s1", "/work", 1786183000000, 1786183200000, 1.0, 1000, 200, 0, 300, 0, None),
    )
    for index, tokens in enumerate(((100, 20, 30), (200, 40, 60))):
        connection.execute(
            "INSERT INTO message VALUES (?, ?, ?, ?, ?)",
            (
                f"m{index}",
                "s1",
                1786183000000 + index * 60_000,
                1786183000000 + index * 60_000,
                json.dumps(
                    {
                        "providerID": "openai",
                        "modelID": "gpt-5",
                        "tokens": {
                            "input": tokens[0],
                            "output": tokens[1],
                            "cache": {"read": tokens[2], "write": 0},
                        },
                    }
                ),
            ),
        )
    connection.commit()
    connection.close()

    events = OpenCodeAdapter([tmp_path]).collect()

    assert len(events) == 2
    assert sum(event.usage.total for event in events) == 450
    assert all(event.source_kind == "opencode_sqlite_message" for event in events)


def test_ide_sqlite_exact_and_text_estimate(tmp_path):
    database = tmp_path / "state.vscdb"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE ItemTable (key TEXT, value TEXT)")
    connection.executemany(
        "INSERT INTO ItemTable VALUES (?, ?)",
        [
            (
                "tokenUsage",
                json.dumps(
                    {
                        "id": "exact-a",
                        "timestamp": "2026-08-08T10:00:00Z",
                        "usage": {"inputTokens": 90, "outputTokens": 10},
                    }
                ),
            ),
            (
                "tokenMessages",
                json.dumps(
                    {
                        "id": "estimate-a",
                        "timestamp": "2026-08-08T10:01:00Z",
                        "role": "assistant",
                        "content": "This response contains sixteen ASCII chars.",
                    }
                ),
            ),
        ],
    )
    connection.commit()
    connection.close()
    adapter = TraeAdapter([tmp_path])

    events = adapter.collect()

    assert any(event.accuracy is Accuracy.EXACT and event.usage.total == 100 for event in events)
    assert any(event.accuracy is Accuracy.ESTIMATED for event in events)


def test_ide_exact_only_disables_estimates(tmp_path):
    path = tmp_path / "messages.json"
    path.write_text(
        json.dumps(
            {"id": "a", "timestamp": "2026-08-08T10:00:00Z", "role": "user", "text": "hello"}
        ),
        encoding="utf-8",
    )
    adapter = TraeAdapter([tmp_path], include_estimates=False)

    assert adapter.collect() == []
