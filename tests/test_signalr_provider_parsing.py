import base64
import json
import zlib

from src.live.signalr_provider import UnofficialF1SignalRProvider


def _compress_raw_deflate(payload: dict) -> str:
    raw = json.dumps(payload).encode("utf-8")
    compressor = zlib.compressobj(level=6, wbits=-zlib.MAX_WBITS)
    packed = compressor.compress(raw) + compressor.flush()
    return base64.b64encode(packed).decode("ascii")


def _provider() -> UnofficialF1SignalRProvider:
    return UnofficialF1SignalRProvider(
        connection_url="wss://example.invalid/signalrcore",
        negotiate_url="https://example.invalid/signalrcore/negotiate",
        timeout_sec=3,
        verify_ssl=False,
    )


def test_extract_updates_from_signalr_arguments_shape():
    provider = _provider()

    class InvocationLike:
        arguments = [{"TimingData": {"Lines": {"1": {"Position": "1"}}}}]

    updates = provider._extract_updates(InvocationLike())
    assert updates
    topic, payload, extra = updates[0]
    assert topic == "TimingData"
    assert isinstance(payload, dict)
    assert extra == ""


def test_apply_update_decodes_compressed_timing_payload():
    provider = _provider()
    compressed = _compress_raw_deflate(
        {
            "Lines": {
                "1": {
                    "Position": "1",
                    "GapToLeader": "0.000",
                    "LastLapTime": {"Value": "1:30.000", "Utc": "2026-02-18T12:00:00Z"},
                    "Sectors": {
                        "0": {"Value": "30.000", "Segments": {"0": {"Status": 2048}}},
                        "1": {"Value": "30.000", "Segments": {"0": {"Status": 2049}}},
                        "2": {"Value": "30.000", "Segments": {"0": {"Status": 2051}}},
                    },
                }
            }
        }
    )

    provider._apply_update("TimingData.z", compressed)
    rows = provider._build_rows_payload()

    assert rows
    assert rows[0]["position"] == "1"
    assert rows[0]["lap"]["microsectors_1_labels"] == ["slower"]
    assert rows[0]["lap"]["microsectors_2_labels"] == ["improved"]
    assert rows[0]["lap"]["microsectors_3_labels"] == ["best_overall"]
