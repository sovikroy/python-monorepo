import threading
from collections.abc import Iterator

import pytest

from messaging import broker_from_url
from messaging.backends.tcp import TcpBrokerServer
from tcp_broker.main import check


@pytest.fixture
def server() -> Iterator[TcpBrokerServer]:
    srv = TcpBrokerServer("127.0.0.1", 0)
    thread = threading.Thread(target=srv.serve_forever, args=(0.05,), daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def test_check_reports_a_running_broker(server: TcpBrokerServer) -> None:
    assert check(server.port) == 0


def test_check_fails_when_nothing_listens() -> None:
    srv = TcpBrokerServer("127.0.0.1", 0)
    port = srv.port
    srv.server_close()
    assert check(port) == 1


def test_services_talk_through_the_server(server: TcpBrokerServer) -> None:
    with (
        broker_from_url(f"tcp://127.0.0.1:{server.port}") as producer,
        broker_from_url(f"tcp://127.0.0.1:{server.port}") as consumer,
    ):
        producer.publish("orders.placed", "hello")
        assert server.pending("orders.placed") == 1
        assert consumer.receive("orders.placed", timeout=1) == "hello"
