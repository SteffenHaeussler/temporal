import importlib

from ticketflow import config


def test_config_reads_temporal_settings_from_environment(monkeypatch):
    monkeypatch.setenv("TEMPORAL_ADDRESS", "temporal.example:7233")
    monkeypatch.setenv("TEMPORAL_NAMESPACE", "prod")
    monkeypatch.setenv("TICKETFLOW_TASK_QUEUE", "tickets-prod")
    monkeypatch.setenv("TICKETFLOW_LOG_FORMAT", "json")
    monkeypatch.setenv("TICKETFLOW_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("TICKETFLOW_LOG_FIELDS", "level,message,task_queue")
    monkeypatch.setenv("TICKETFLOW_TRACE_EXPORTER", "otlp")
    monkeypatch.setenv("TICKETFLOW_OTLP_ENDPOINT", "http://otel.example:4318/v1/traces")

    reloaded = importlib.reload(config)

    assert reloaded.TEMPORAL_ADDRESS == "temporal.example:7233"
    assert reloaded.TEMPORAL_NAMESPACE == "prod"
    assert reloaded.TASK_QUEUE == "tickets-prod"
    assert reloaded.LOG_FORMAT == "json"
    assert reloaded.LOG_LEVEL == "DEBUG"
    assert reloaded.LOG_FIELDS == ["level", "message", "task_queue"]
    assert reloaded.TRACE_EXPORTER == "otlp"
    assert reloaded.OTLP_ENDPOINT == "http://otel.example:4318/v1/traces"

    monkeypatch.delenv("TEMPORAL_ADDRESS")
    monkeypatch.delenv("TEMPORAL_NAMESPACE")
    monkeypatch.delenv("TICKETFLOW_TASK_QUEUE")
    monkeypatch.delenv("TICKETFLOW_LOG_FORMAT")
    monkeypatch.delenv("TICKETFLOW_LOG_LEVEL")
    monkeypatch.delenv("TICKETFLOW_LOG_FIELDS")
    monkeypatch.delenv("TICKETFLOW_TRACE_EXPORTER")
    monkeypatch.delenv("TICKETFLOW_OTLP_ENDPOINT")
    importlib.reload(config)


def test_config_trace_settings_default_to_disabled():
    assert config.TRACE_EXPORTER == "none"
    assert config.OTLP_ENDPOINT == "http://localhost:4318/v1/traces"


def test_config_reads_temporal_settings_from_dotenv(tmp_path, monkeypatch):
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "\n".join(
            [
                "TEMPORAL_ADDRESS=dotenv.example:7233",
                "TEMPORAL_NAMESPACE=dotenv",
                "TICKETFLOW_TASK_QUEUE=tickets-dotenv",
                "TICKETFLOW_LOG_FORMAT=json",
                "TICKETFLOW_LOG_LEVEL=WARNING",
                "TICKETFLOW_LOG_FIELDS=time,level,message",
            ]
        )
    )
    monkeypatch.chdir(tmp_path)

    reloaded = importlib.reload(config)

    assert reloaded.TEMPORAL_ADDRESS == "dotenv.example:7233"
    assert reloaded.TEMPORAL_NAMESPACE == "dotenv"
    assert reloaded.TASK_QUEUE == "tickets-dotenv"
    assert reloaded.LOG_FORMAT == "json"
    assert reloaded.LOG_LEVEL == "WARNING"
    assert reloaded.LOG_FIELDS == ["time", "level", "message"]

    monkeypatch.delenv("TEMPORAL_ADDRESS")
    monkeypatch.delenv("TEMPORAL_NAMESPACE")
    monkeypatch.delenv("TICKETFLOW_TASK_QUEUE")
    monkeypatch.delenv("TICKETFLOW_LOG_FORMAT")
    monkeypatch.delenv("TICKETFLOW_LOG_LEVEL")
    monkeypatch.delenv("TICKETFLOW_LOG_FIELDS")
    importlib.reload(config)
