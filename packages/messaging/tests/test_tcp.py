"""TCP-specific behaviour: the wire protocol, reconnects and not losing messages."""

import json
import socket
import threading

import pytest

from messaging import BrokerError
from messaging.backends.tcp import TcpBroker, TcpBrokerServer


def raw(server: TcpBrokerServer, *requests: object) -> list[dict[str, object]]:
    with socket.create_connection(("127.0.0.1", server.port), timeout=5) as sock:
        file = sock.makefile("rwb")
        replies = []
        for request in requests:
            line = request if isinstance(request, bytes) else json.dumps(request).encode()
            file.write(line + b"\n")
            file.flush()
            replies.append(json.loads(file.readline()))
        return replies


def test_protocol(tcp_server: TcpBrokerServer) -> None:
    assert raw(
        tcp_server,
        {"op": "ping"},
        {"op": "publish", "topic": "t", "message": "m"},
        {"op": "receive", "topic": "t", "timeout": 0},
        {"op": "receive", "topic": "t", "timeout": 0},
    ) == [{"ok": True}, {"ok": True}, {"ok": True, "message": "m"}, {"ok": True, "message": None}]


@pytest.mark.parametrize(
    "bad",
    [
        b"not json",
        {"op": "explode", "topic": "t"},
        {"op": "publish", "topic": "t"},
        {"op": "publish", "topic": "", "message": "m"},
        {"op": "publish", "topic": "t", "message": 1},
        [],
    ],
)
def test_bad_requests_get_an_error_and_keep_the_connection(
    tcp_server: TcpBrokerServer, bad: object
) -> None:
    error, pong = raw(tcp_server, bad, {"op": "ping"})
    assert error["ok"] is False
    assert pong == {"ok": True}


def test_server_errors_surface_as_broker_error(tcp_server: TcpBrokerServer) -> None:
    with TcpBroker("127.0.0.1", tcp_server.port) as broker, pytest.raises(BrokerError):
        broker._call({"op": "explode"}, wait=0)


def test_receive_blocks_until_a_message_arrives(tcp_server: TcpBrokerServer) -> None:
    with (
        TcpBroker("127.0.0.1", tcp_server.port) as consumer,
        TcpBroker("127.0.0.1", tcp_server.port) as producer,
    ):
        timer = threading.Timer(0.2, producer.publish, args=("t", "late"))
        timer.start()
        assert consumer.receive("t", timeout=5) == "late"
        timer.join()


def test_each_message_goes_to_one_consumer(tcp_server: TcpBrokerServer) -> None:
    port = tcp_server.port
    with TcpBroker("127.0.0.1", port) as producer:
        for i in range(50):
            producer.publish("work", str(i))
    seen: list[str] = []
    lock = threading.Lock()

    def consume() -> None:
        with TcpBroker("127.0.0.1", port) as consumer:
            while (message := consumer.receive("work", timeout=0.2)) is not None:
                with lock:
                    seen.append(message)

    workers = [threading.Thread(target=consume) for _ in range(4)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert sorted(seen, key=int) == [str(i) for i in range(50)]


def test_client_reconnects_after_the_server_restarts() -> None:
    first = TcpBrokerServer("127.0.0.1", 0)
    port = first.port
    threading.Thread(target=first.serve_forever, args=(0.05,), daemon=True).start()
    broker = TcpBroker("127.0.0.1", port)
    broker.publish("t", "before")
    first.shutdown()
    first.server_close()
    second = TcpBrokerServer("127.0.0.1", port)
    threading.Thread(target=second.serve_forever, args=(0.05,), daemon=True).start()
    try:
        broker.publish("t", "after")
        assert broker.receive("t", timeout=1) == "after"
    finally:
        broker.close()
        second.shutdown()
        second.server_close()


def test_message_is_requeued_if_the_consumer_vanishes(tcp_server: TcpBrokerServer) -> None:
    topic, message = "t", "precious"
    tcp_server.requeue(topic, message)
    reply, taken = tcp_server.dispatch(json.dumps({"op": "receive", "topic": topic}).encode())
    assert reply == {"ok": True, "message": message}
    assert taken == (topic, message)
    # The handler gives `taken` back when writing the reply fails:
    tcp_server.requeue(*taken)
    assert tcp_server.pending(topic) == 1


def test_connection_refused_raises() -> None:
    server = TcpBrokerServer("127.0.0.1", 0)
    port = server.port
    server.server_close()
    broker = TcpBroker("127.0.0.1", port, connect_timeout=1)
    with pytest.raises(ConnectionRefusedError):
        broker.publish("t", "m")
