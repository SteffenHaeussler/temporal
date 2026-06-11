"""Tests for the SQLite read model."""

from ticketflow import config, readmodel
from ticketflow.models import TicketResult, TicketStatus


def make_result(ticket_id: str = "t-1", **overrides) -> TicketResult:
    defaults = dict(
        ticket_id=ticket_id,
        status=TicketStatus.RESOLVED,
        reply_text="All done.",
        refund_executed=False,
    )
    defaults.update(overrides)
    return TicketResult(**defaults)


def test_save_and_load_roundtrip(tmp_path):
    db = str(tmp_path / "read.db")
    result = make_result(refund_executed=True)
    readmodel.save_result(result, db)
    assert readmodel.load_result("t-1", db) == result


def test_save_overwrites_existing_result(tmp_path):
    db = str(tmp_path / "read.db")
    readmodel.save_result(make_result(reply_text="first"), db)
    readmodel.save_result(make_result(reply_text="second"), db)
    loaded = readmodel.load_result("t-1", db)
    assert loaded is not None
    assert loaded.reply_text == "second"


def test_load_missing_ticket_returns_none(tmp_path):
    db = str(tmp_path / "read.db")
    readmodel.save_result(make_result(), db)
    assert readmodel.load_result("other", db) is None


def test_load_without_db_file_returns_none(tmp_path):
    assert readmodel.load_result("t-1", str(tmp_path / "missing.db")) is None


def test_clear_removes_all_rows(tmp_path):
    db = str(tmp_path / "read.db")
    readmodel.save_result(make_result("a"), db)
    readmodel.save_result(make_result("b"), db)
    assert readmodel.clear(db) == 2
    assert readmodel.load_result("a", db) is None


def test_clear_without_db_file_returns_zero(tmp_path):
    assert readmodel.clear(str(tmp_path / "missing.db")) == 0


def test_default_db_path_resolves_from_config_at_call_time(tmp_path, monkeypatch):
    db = str(tmp_path / "default.db")
    monkeypatch.setattr(config, "DB_PATH", db)
    result = make_result()
    readmodel.save_result(result)
    assert readmodel.load_result("t-1") == result
