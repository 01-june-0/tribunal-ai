import http.client
import json
import threading
import pytest
from companion_server import CompanionHandler
from dashboard_server import DashboardServer


@pytest.fixture
def http_server():
    server = DashboardServer(('127.0.0.1', 0), CompanionHandler)
    server.bridge_token = 'test-token'
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    yield server
    server.shutdown(); server.server_close(); thread.join(timeout=2)


def request(server, method='POST', path='/bridge/missions', body='{}', headers=None):
    conn = http.client.HTTPConnection('127.0.0.1', server.server_address[1], timeout=3)
    conn.request(method, path, body=body, headers=headers or {})
    response = conn.getresponse(); data = response.read(); code = response.status
    conn.close(); return code, data


def test_missing_token_denied(http_server):
    assert request(http_server)[0] == 403


@pytest.mark.parametrize('headers', [{'Origin': 'https://evil.example'}, {'Origin': 'null'}, {'Host': 'evil.example'}])
def test_foreign_origin_or_host_denied(http_server, headers):
    headers.update({'X-Tribunal-Token': 'test-token', 'Content-Type': 'application/json'})
    assert request(http_server, headers=headers)[0] == 403


def test_authenticated_json_passes_the_gate(http_server):
    # Past the token and origin checks the request itself is judged: without a request_id nothing starts.
    code, body = request(http_server, headers={'X-Tribunal-Token': 'test-token', 'Content-Type': 'application/json'})
    assert code == 400 and 'request_id' in json.loads(body)['error']


def test_old_order_intake_is_gone(http_server):
    headers = {'X-Tribunal-Token': 'test-token', 'Content-Type': 'application/json'}
    # No body: an unknown POST path answers 404 without reading one, so a body could race the closing connection.
    assert request(http_server, path='/bridge/orders', body='', headers=headers)[0] == 404
    assert request(http_server, 'GET', '/bridge/order?id=x', headers=headers)[0] == 404


def test_wrong_content_type_and_oversize_rejected(http_server):
    assert request(http_server, headers={'X-Tribunal-Token': 'test-token'})[0] == 400
    assert request(http_server, body=' ' * 32001, headers={'X-Tribunal-Token': 'test-token', 'Content-Type': 'application/json'})[0] == 400


def test_read_bridge_requires_token(http_server):
    assert request(http_server, 'GET', '/bridge/status')[0] == 403


def test_console_static_served(http_server):
    code, body = request(http_server, 'GET', '/')
    assert code == 200 and 'Tribunal AI 자세히 보기'.encode() in body
    assert request(http_server, 'GET', '/console.js')[0] == 200
