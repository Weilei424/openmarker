from core.layout.cancellation import StoppedWithWarmStart


def test_stopped_with_warm_start_carries_result():
    payload = (["placement"], 123.4, 56.7)
    exc = StoppedWithWarmStart(payload)
    assert exc.result == payload
    assert isinstance(exc, Exception)
