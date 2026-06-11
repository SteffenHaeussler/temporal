import pytest
from temporalio.api.enums.v1 import IndexedValueType
from temporalio.api.operatorservice.v1 import request_response_pb2
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment


@pytest.fixture
async def env():
    env = await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    )
    try:
        await env.client.operator_service.add_search_attributes(
            request_response_pb2.AddSearchAttributesRequest(
                namespace=env.client.namespace,
                search_attributes={
                    "TicketStatus": IndexedValueType.Value("INDEXED_VALUE_TYPE_KEYWORD")
                },
            )
        )
        yield env
    finally:
        await env.shutdown()
