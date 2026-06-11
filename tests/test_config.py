import importlib

from ticketflow import config


def test_config_reads_temporal_settings_from_environment(monkeypatch):
    monkeypatch.setenv("TEMPORAL_ADDRESS", "temporal.example:7233")
    monkeypatch.setenv("TEMPORAL_NAMESPACE", "prod")
    monkeypatch.setenv("TICKETFLOW_TASK_QUEUE", "tickets-prod")

    reloaded = importlib.reload(config)

    assert reloaded.TEMPORAL_ADDRESS == "temporal.example:7233"
    assert reloaded.TEMPORAL_NAMESPACE == "prod"
    assert reloaded.TASK_QUEUE == "tickets-prod"

    monkeypatch.delenv("TEMPORAL_ADDRESS")
    monkeypatch.delenv("TEMPORAL_NAMESPACE")
    monkeypatch.delenv("TICKETFLOW_TASK_QUEUE")
    importlib.reload(config)


def test_config_reads_temporal_settings_from_dotenv(tmp_path, monkeypatch):
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "\n".join(
            [
                "TEMPORAL_ADDRESS=dotenv.example:7233",
                "TEMPORAL_NAMESPACE=dotenv",
                "TICKETFLOW_TASK_QUEUE=tickets-dotenv",
            ]
        )
    )
    monkeypatch.chdir(tmp_path)

    reloaded = importlib.reload(config)

    assert reloaded.TEMPORAL_ADDRESS == "dotenv.example:7233"
    assert reloaded.TEMPORAL_NAMESPACE == "dotenv"
    assert reloaded.TASK_QUEUE == "tickets-dotenv"

    monkeypatch.delenv("TEMPORAL_ADDRESS")
    monkeypatch.delenv("TEMPORAL_NAMESPACE")
    monkeypatch.delenv("TICKETFLOW_TASK_QUEUE")
    importlib.reload(config)
