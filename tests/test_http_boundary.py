"""@brief 固定来源请求拒绝与读取上限，全部使用受控替身。"""
import io
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest
from scripts import http_boundary


@pytest.mark.parametrize("url", ["http://api.github.com/graphql", "https://api.github.com.evil.invalid/graphql",
    "https://user:pass@api.github.com/graphql", "https://api.github.com:444/graphql", "https://api.github.com/graphql#x",
    "https://api.github.com/graphql?x=1", "https://api.github.com/\nquery"])
def test_invalid_origin_is_rejected_before_network(monkeypatch, url):
    called = []
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: called.append(True))
    with pytest.raises(ValueError):
        http_boundary.read_https_response(urllib.request.Request(url), allowed_host="api.github.com", max_bytes=128)
    assert called == []


def test_redirect_never_creates_second_request():
    req = urllib.request.Request("https://api.github.com/graphql", headers={"Authorization": "Bearer fixture"})
    with pytest.raises(urllib.error.HTTPError):
        http_boundary._NoRedirect().redirect_request(req, None, 302, "fixture", {}, "http://127.0.0.1/fixture")


@pytest.mark.parametrize("headers,body", [({"Content-Length":"9"}, b"123"), ({}, b"12345")])
def test_response_limit_handles_declared_and_chunked_size(monkeypatch, headers, body):
    class Response(io.BytesIO):
        pass
    response = Response(body)
    response.headers = headers
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: SimpleNamespace(open=lambda *_args, **_kwargs: response))
    with pytest.raises(ValueError, match="大小上限"):
        http_boundary.read_https_response(urllib.request.Request("https://api.github.com/graphql"), allowed_host="api.github.com", max_bytes=4)
