from ticketflow import agent_worker, worker


def test_worker_exposes_async_main():
    assert callable(worker.main)


def test_agent_worker_exposes_async_main():
    assert callable(agent_worker.main)
