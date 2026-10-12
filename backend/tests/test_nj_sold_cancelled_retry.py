import asyncio

import httpx
import pytest

import pipeline.scrape_nj_sold_cancelled as sold_cancelled


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    real_sleep = asyncio.sleep

    async def fast(_):
        await real_sleep(0)
    monkeypatch.setattr(sold_cancelled.asyncio, "sleep", fast)


def run(handler, method="POST"):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await sold_cancelled._request(client, method, "https://salesweb.example/Sales/SalesSearch")
    return asyncio.run(go())


def test_a_passing_server_error_is_retried():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(500 if len(calls) < 3 else 200)
    assert run(handler).status_code == 200 and len(calls) == 3


def test_persistent_server_errors_give_up_and_client_errors_are_not_retried():
    calls = []
    with pytest.raises(httpx.HTTPStatusError):
        run(lambda request: (calls.append(1), httpx.Response(500))[1])
    assert len(calls) == sold_cancelled.RETRIES
    calls.clear()
    with pytest.raises(httpx.HTTPStatusError):
        run(lambda request: (calls.append(1), httpx.Response(404))[1], "GET")
    assert len(calls) == 1
