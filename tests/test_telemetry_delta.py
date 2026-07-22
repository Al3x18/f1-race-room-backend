import numpy as np
import pandas as pd

from src.telemetry import Telemetry


def _telemetry(distances, seconds):
    return pd.DataFrame(
        {
            "Distance": distances,
            "Time": pd.to_timedelta(seconds, unit="s"),
        }
    )


def test_calculate_delta_interpolates_comparison_on_reference_distance():
    reference = _telemetry([0.0, 100.0, 200.0], [0.0, 1.0, 2.0])
    comparison = _telemetry([0.0, 50.0, 100.0], [0.0, 1.5, 3.0])

    delta, returned_reference, returned_comparison = Telemetry._calculate_delta(
        None,
        None,
        reference,
        comparison,
    )

    np.testing.assert_allclose(delta, [0.0, 0.5, 1.0])
    assert returned_reference is reference
    assert returned_comparison is comparison


def test_calculate_delta_ignores_repeated_comparison_distances():
    reference = _telemetry([0.0, 100.0, 200.0], [0.0, 1.0, 2.0])
    comparison = _telemetry(
        [0.0, 50.0, 50.0, 40.0, 100.0],
        [0.0, 1.0, 1.1, 1.2, 2.5],
    )

    delta, _, _ = Telemetry._calculate_delta(None, None, reference, comparison)

    np.testing.assert_allclose(delta, [0.0, 0.0, 0.5])


def test_calculate_delta_falls_back_when_required_data_is_missing():
    reference = _telemetry([0.0, 100.0], [0.0, 1.0])
    comparison = pd.DataFrame({"Distance": [0.0, 100.0]})

    delta, returned_reference, returned_comparison = Telemetry._calculate_delta(
        None,
        None,
        reference,
        comparison,
    )

    assert delta is None
    assert returned_reference is reference
    assert returned_comparison is comparison
