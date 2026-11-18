def test_request_id_is_returned_and_preserved(client) -> None:
    generated = client.get("/health")
    assert generated.status_code == 200
    request_id = generated.headers["x-request-id"]
    assert request_id

    preserved = client.get("/health", headers={"X-Request-ID": "trace-123"})
    assert preserved.status_code == 200
    assert preserved.headers["x-request-id"] == "trace-123"


def test_invalid_request_id_is_replaced(client) -> None:
    response = client.get("/health", headers={"X-Request-ID": "bad value"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] != "bad value"
    assert len(response.headers["x-request-id"]) == 36
