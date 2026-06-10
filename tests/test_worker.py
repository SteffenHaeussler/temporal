from ticketflow import worker


def test_worker_exposes_async_main():
    assert callable(worker.main)
