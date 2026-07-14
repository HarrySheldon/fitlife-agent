import socket

import pytest

from backend.domain.errors import ApplicationError
from backend.domain.model_endpoint_policy import ModelEndpointPolicy


def public_resolver(host: str, port: int, type: int):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]


@pytest.mark.parametrize(
    "url",
    [
        "http://models.example.com/v1",
        "https://user:password@models.example.com/v1",
        "https://models.example.com/v1?token=secret",
        "https://models.example.com/v1#fragment",
        "https://127.0.0.1/v1",
        "https://169.254.169.254/latest/meta-data",
        "https://10.0.0.8/v1",
        "https://[::1]/v1",
    ],
)
def test_custom_endpoint_rejects_unsafe_urls(url):
    policy = ModelEndpointPolicy(resolver=public_resolver)

    with pytest.raises(ApplicationError) as raised:
        policy.validate_base_url(url)

    assert raised.value.code == "INVALID_MODEL_ENDPOINT"


def test_custom_endpoint_normalizes_https_public_url():
    policy = ModelEndpointPolicy(resolver=public_resolver)

    result = policy.validate_base_url("https://Models.Example.com/v1/")

    assert result == "https://models.example.com/v1"


def test_custom_endpoint_revalidates_dns_on_each_request():
    resolved_addresses = iter(["93.184.216.34", "10.0.0.8"])

    def rebinding_resolver(host: str, port: int, type: int):
        address = next(resolved_addresses)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    policy = ModelEndpointPolicy(resolver=rebinding_resolver)

    policy.validate_request_url("https://models.example.com/v1/responses")
    with pytest.raises(ApplicationError) as raised:
        policy.validate_request_url("https://models.example.com/v1/responses")

    assert raised.value.code == "INVALID_MODEL_ENDPOINT"
