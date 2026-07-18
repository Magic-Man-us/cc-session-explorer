"""The SQLite transcript store: schema, incremental ingest, idempotency, and full-text search."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from cc_session_core import parse_line

from cc_session_explorer.ingest import connect, count_records, default_db_path, ingest, search
from cc_session_explorer.ingest.ingest import RecordRow, searchable_text
from cc_session_explorer.paths import DATA_HOME

if TYPE_CHECKING:
    from pathlib import Path

# Full envelope: cc_session_core models the real transcript shape, where conversation records
# always carry parentUuid/isSidechain/userType/entrypoint/version and an assistant
# message carries id/model/usage.
_ENV = (
    '"parentUuid":null,"isSidechain":false,"userType":"external","entrypoint":"cli",'
    '"version":"1.0.0","sessionId":"s1","timestamp":"2026-06-16T01:39:53.604Z",'
    '"gitBranch":"main","cwd":"/repo"'
)
_ASSISTANT = (
    '{"type":"assistant","uuid":"u1","slug":"myproj",' + _ENV + ","
    '"message":{"type":"message","id":"msg_1","role":"assistant","model":"claude-sonnet-4",'
    '"content":[{"type":"text","text":"the peregrine falcon dives"}],'
    '"usage":{"input_tokens":1,"output_tokens":1,"cache_read_input_tokens":0,'
    '"cache_creation_input_tokens":0,'
    '"cache_creation":{"ephemeral_5m_input_tokens":0,"ephemeral_1h_input_tokens":0}}}}'
)
_USER = (
    '{"type":"user","uuid":"u2",' + _ENV + ","
    '"message":{"role":"user","content":"tell me about birds"}}'
)
_MODE = '{"type":"mode","sessionId":"s1","mode":"default"}'


def _write(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n")


def _corpus(root: Path, lines: list[str]) -> Path:
    file = root / "project" / "session.jsonl"
    file.parent.mkdir(parents=True)
    _write(file, lines)
    return file


def test_connect_creates_owner_only_db(tmp_path: Path) -> None:
    db_path = tmp_path / "state" / "transcripts.db"
    conn = connect(db_path)
    assert db_path.exists()
    assert db_path.stat().st_mode & 0o777 == 0o600
    assert db_path.parent.stat().st_mode & 0o777 == 0o700
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"records", "records_fts", "ingest_state"} <= tables
    conn.close()


def test_ingest_inserts_records_and_projects_columns(tmp_path: Path) -> None:
    _corpus(tmp_path, [_ASSISTANT, _USER, _MODE])
    conn = connect(tmp_path / "db.sqlite")
    report = ingest(conn, projects_root=tmp_path)
    assert report.files_total == 1
    assert report.files_ingested == 1
    assert report.records_inserted == 3
    assert count_records(conn) == 3

    row = conn.execute(
        "SELECT type, uuid, session_id, timestamp, slug, git_branch, cwd, text"
        " FROM records WHERE uuid = 'u1'"
    ).fetchone()
    assert row["type"] == "assistant"
    assert row["session_id"] == "s1"
    assert row["timestamp"] == "2026-06-16T01:39:53.604Z"  # stored verbatim, not re-serialized
    assert row["slug"] == "myproj"
    assert row["git_branch"] == "main"
    assert row["cwd"] == "/repo"
    assert row["text"] == "the peregrine falcon dives"
    conn.close()


def test_ingest_is_idempotent(tmp_path: Path) -> None:
    _corpus(tmp_path, [_ASSISTANT, _USER])
    conn = connect(tmp_path / "db.sqlite")
    ingest(conn, projects_root=tmp_path)
    second = ingest(conn, projects_root=tmp_path)
    assert second.files_skipped == 1
    assert second.files_ingested == 0
    assert second.records_inserted == 0
    assert count_records(conn) == 2
    conn.close()


def test_append_ingests_only_the_new_tail(tmp_path: Path) -> None:
    file = _corpus(tmp_path, [_ASSISTANT, _USER])
    conn = connect(tmp_path / "db.sqlite")
    ingest(conn, projects_root=tmp_path)
    _write(file, [_ASSISTANT, _USER, _MODE])  # appended one line; size grows

    report = ingest(conn, projects_root=tmp_path)
    assert report.files_ingested == 1
    assert report.records_inserted == 1  # boundary verified by hash, only the tail ingested
    assert count_records(conn) == 3
    line_nos = [r[0] for r in conn.execute("SELECT line_no FROM records ORDER BY line_no")]
    assert line_nos == [1, 2, 3]
    conn.close()


def test_rewritten_larger_file_falls_back_to_full_reingest(tmp_path: Path) -> None:
    file = _corpus(tmp_path, [_ASSISTANT])
    conn = connect(tmp_path / "db.sqlite")
    ingest(conn, projects_root=tmp_path)
    _write(file, [_MODE, _USER, _ASSISTANT])  # larger, but different content: not an append

    ingest(conn, projects_root=tmp_path)
    rows = conn.execute("SELECT line_no, type FROM records ORDER BY line_no").fetchall()
    assert [(r["line_no"], r["type"]) for r in rows] == [(1, "mode"), (2, "user"), (3, "assistant")]
    conn.close()


def test_pre_tail_schema_is_migrated_on_connect(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    old = sqlite3.connect(db_path)
    old.execute(
        "CREATE TABLE ingest_state (source TEXT PRIMARY KEY, lines_ingested INTEGER NOT NULL,"
        " size_bytes INTEGER NOT NULL, mtime_ns INTEGER NOT NULL)"
    )
    old.execute("INSERT INTO ingest_state VALUES ('stale', 1, 2, 3)")
    old.commit()
    old.close()

    conn = connect(db_path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(ingest_state)")}
    assert {"tail_offset", "tail_sha"} <= columns
    assert conn.execute("SELECT count(*) FROM ingest_state").fetchone()[0] == 0  # marks dropped
    conn.close()


def test_torn_tail_line_heals_on_next_ingest(tmp_path: Path) -> None:
    file = _corpus(tmp_path, [_ASSISTANT])
    file.write_text(f"{_ASSISTANT}\n{_USER[:20]}")  # a live writer is mid-line: torn tail
    conn = connect(tmp_path / "db.sqlite")
    first = ingest(conn, projects_root=tmp_path)
    assert first.invalid_lines == 1  # the torn tail is stored raw, not dropped

    _write(file, [_ASSISTANT, _USER, _MODE])  # the writer finished the line and appended
    ingest(conn, projects_root=tmp_path)
    healed = conn.execute("SELECT type FROM records WHERE line_no = 2").fetchone()
    assert healed["type"] == "user"  # the invalid row was replaced by the completed record
    assert count_records(conn) == 3
    conn.close()


def test_torn_multibyte_tail_does_not_crash_whole_file_ingest(tmp_path: Path) -> None:
    # A live writer's flush can land mid-character; the falcon emoji is 4 UTF-8 bytes.
    unicode_user = _USER.replace("tell me about birds", "tell me about the falcon \U0001f985")
    file = _corpus(tmp_path, [_ASSISTANT])
    encoded = f"{_ASSISTANT}\n{unicode_user}".encode()
    file.write_bytes(encoded[:-2])  # torn inside the emoji's 4-byte encoding
    conn = connect(tmp_path / "db.sqlite")
    report = ingest(conn, projects_root=tmp_path)  # must not raise UnicodeDecodeError
    assert report.invalid_lines == 1  # the torn tail line is stored raw, not dropped
    assert count_records(conn) == 2
    rows = {r["line_no"]: r["type"] for r in conn.execute("SELECT line_no, type FROM records")}
    assert rows[1] == "assistant"  # the complete line before the torn bytes is untouched
    assert rows[2] == "invalid"

    _write(file, [_ASSISTANT, unicode_user, _MODE])  # the writer finished; the line heals
    ingest(conn, projects_root=tmp_path)
    assert count_records(conn) == 3
    conn.close()


def test_shrunk_file_is_reingested_whole(tmp_path: Path) -> None:
    file = _corpus(tmp_path, [_ASSISTANT, _USER, _MODE])
    conn = connect(tmp_path / "db.sqlite")
    ingest(conn, projects_root=tmp_path)
    _write(file, [_MODE])  # rewritten shorter

    report = ingest(conn, projects_root=tmp_path)
    assert report.records_inserted == 1
    assert count_records(conn) == 1
    remaining = conn.execute("SELECT type FROM records").fetchall()
    assert [r[0] for r in remaining] == ["mode"]  # stale rows gone, no orphans
    conn.close()


def test_search_matches_prose_and_returns_snippet(tmp_path: Path) -> None:
    _corpus(tmp_path, [_ASSISTANT, _USER, _MODE])
    conn = connect(tmp_path / "db.sqlite")
    ingest(conn, projects_root=tmp_path)

    hits = search(conn, "peregrine")
    assert len(hits) == 1
    assert hits[0].session_id == "s1"
    assert hits[0].type == "assistant"
    assert "[peregrine]" in hits[0].snippet

    assert search(conn, "birds")[0].type == "user"
    assert search(conn, "nonexistentword") == []
    conn.close()


def test_search_index_stays_in_sync_after_reingest(tmp_path: Path) -> None:
    file = _corpus(tmp_path, [_ASSISTANT])
    conn = connect(tmp_path / "db.sqlite")
    ingest(conn, projects_root=tmp_path)
    assert len(search(conn, "peregrine")) == 1

    _write(file, [_USER])  # replaces the assistant turn; FTS must drop the stale text
    ingest(conn, projects_root=tmp_path)
    assert search(conn, "peregrine") == []
    assert len(search(conn, "birds")) == 1
    conn.close()


def test_unparseable_line_is_stored_raw_as_invalid(tmp_path: Path) -> None:
    _corpus(tmp_path, [_ASSISTANT, "{not valid json", _USER])
    conn = connect(tmp_path / "db.sqlite")
    report = ingest(conn, projects_root=tmp_path)
    assert report.invalid_lines == 1
    assert report.records_inserted == 3  # the invalid line is kept, losslessly
    row = conn.execute("SELECT line_no, raw, text FROM records WHERE type = 'invalid'").fetchone()
    assert row["line_no"] == 2
    assert row["raw"] == "{not valid json"
    assert row["text"] == ""
    conn.close()


def test_typed_parse_failure_still_stores_raw_without_text(tmp_path: Path) -> None:
    broken = '{"type":"mode","sessionId":"s1"}'  # valid envelope; 'mode' record missing its 'mode'
    _corpus(tmp_path, [_ASSISTANT, broken])
    conn = connect(tmp_path / "db.sqlite")
    report = ingest(conn, projects_root=tmp_path)
    assert report.parse_errors == 1
    assert report.records_inserted == 2  # the broken record is kept, losslessly
    row = conn.execute("SELECT session_id, text, raw FROM records WHERE type = 'mode'").fetchone()
    assert row["session_id"] == "s1"
    assert row["text"] == ""  # no typed record, so no searchable prose
    assert row["raw"] == broken
    conn.close()


def test_default_db_path_sits_in_juno_home() -> None:
    path = default_db_path()
    assert path.name == "transcripts.db"
    assert path.parent == DATA_HOME


def test_unknown_record_columns_are_still_projected(tmp_path: Path) -> None:
    unknown = '{"type":"brand-new","sessionId":"s9","uuid":"uX","slug":"proj"}'
    _corpus(tmp_path, [unknown])
    conn = connect(tmp_path / "db.sqlite")
    ingest(conn, projects_root=tmp_path)
    row = conn.execute("SELECT type, session_id, uuid, slug FROM records").fetchone()
    assert row["type"] == "brand-new"
    assert row["session_id"] == "s9"
    assert row["slug"] == "proj"
    conn.close()


def test_record_row_reads_camel_and_snake() -> None:
    camel = RecordRow.model_validate_json('{"type":"user","sessionId":"s1","parentUuid":"p1"}')
    assert camel.session_id == "s1"
    assert camel.parent_uuid == "p1"


def test_searchable_text_only_for_conversation_turns() -> None:
    assistant = parse_line(_ASSISTANT)
    user = parse_line(_USER)
    mode = parse_line(_MODE)
    assert searchable_text(assistant) == "the peregrine falcon dives"
    assert searchable_text(user) == "tell me about birds"
    assert searchable_text(mode) == ""
