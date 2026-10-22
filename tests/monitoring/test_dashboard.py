"""Regression checks for complete, readable service-health charts."""
import importlib
from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture
def dashboard(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / 'monitoring'))
    return importlib.import_module('generate_monitoring_dashboard')


def history(timestamps, *, latencies=None, successes=None):
    size = len(timestamps)
    return pd.DataFrame({
        'request_timestamp': pd.to_datetime(timestamps, utc=True),
        'request_id': [f'r-{index}' for index in range(size)],
        'session_id': ['test-session'] * size,
        'response_time_ms': pd.to_numeric(pd.Series(latencies if latencies is not None else [100] * size)),
        'success': successes if successes is not None else [True] * size,
        'counts': [{'car': 2}] * size, 'detected_count': [2] * size,
        'threshold': [0.5] * size,
    })


def test_single_request_after_midnight_is_visible_in_all_service_charts(dashboard):
    frame = history(['2026-10-22T16:38:42Z'], latencies=[1250])
    charts = dashboard.build_charts(frame)
    assert list(charts['request_volume'].data[0].y) == [1]
    assert list(charts['response_time'].data[0].y) == [1250]
    assert list(charts['error_rate'].data[0].y) == [0]
    assert len(charts['latency_percentiles'].data) == 3
    for trace in charts['latency_percentiles'].data:
        assert list(trace.y) == [1250]
        assert list(trace.text) == ['1,250']
    for name in ['request_volume', 'response_time', 'error_rate', 'latency_percentiles']:
        chart = charts[name]
        assert chart.layout.height == 300
        assert 'UTC' in chart.layout.xaxis.title.text
        assert chart.layout.xaxis.range[0] < frame.request_timestamp[0] < chart.layout.xaxis.range[1]
    assert charts['error_rate'].layout.yaxis.range[0] < 0 < charts['error_rate'].layout.yaxis.range[1]


def test_twenty_calls_in_an_hour_keep_counts_errors_and_percentiles(dashboard):
    timestamps = pd.date_range('2026-10-22T16:00:00Z', periods=20, freq='3min')
    frame = history(timestamps, latencies=list(range(100, 2100, 100)), successes=[True] * 19 + [False])
    timeline, volume, response, errors, latency = dashboard._build_time_series(frame)
    assert timeline.attrs['bucket_label'] == '5 minutes'
    assert volume.requests.sum() == 20
    assert len(volume) == 12
    assert volume.requests.iloc[-1] == 1
    assert response.response_time_ms.iloc[-1] == 2000
    assert errors.error_rate.iloc[-1] == 100
    assert latency.p95.iloc[0] == pytest.approx(195)
    assert latency.p99.iloc[-1] == 2000
    assert dashboard.build_charts(frame)['error_rate'].layout.yaxis.range[1] >= 100
    assert '20 calls' in dashboard._service_history_description(frame)
    assert '5 minutes per bucket' in dashboard._service_history_description(frame)


def test_midnight_and_latest_day_records_are_not_dropped(dashboard):
    frame = history(['2026-10-21T23:59:59Z', '2026-10-22T00:00:00Z', '2026-10-22T23:59:59Z'])
    _, volume, response, _, _ = dashboard._build_time_series(frame.iloc[::-1])
    assert volume.requests.sum() == 3
    assert volume.requests.iloc[-1] == 1
    assert response.response_time_ms.iloc[-1] == 100


@pytest.mark.parametrize('days', [8, 30, 120, 1000])
def test_long_history_retains_every_call_in_bounded_buckets(dashboard, days):
    frame = history(pd.date_range('2023-01-01T12:00:00Z', periods=days, freq='D'))
    _, volume, _, _, _ = dashboard._build_time_series(frame)
    assert volume.requests.sum() == days
    assert volume.requests.iloc[-1] > 0
    assert len(volume) <= 42


def test_idle_intervals_are_zero_volume_without_inventing_measurements(dashboard):
    frame = history(['2026-10-22T16:00:00Z', '2026-10-22T16:30:00Z'])
    _, volume, response, errors, latency = dashboard._build_time_series(frame)
    idle = volume.requests == 0
    assert idle.any()
    assert response.loc[idle, 'response_time_ms'].isna().all()
    assert errors.loc[idle, 'error_rate'].isna().all()
    assert latency.loc[idle, ['p50', 'p95', 'p99']].isna().all().all()


def test_missing_timestamps_and_latency_are_explained(dashboard):
    frame = history(['2026-10-22T16:38:42Z', None], latencies=[None, None])
    charts = dashboard.build_charts(frame)
    assert sum(charts['request_volume'].data[0].y) == 1
    for name in ['response_time', 'latency_percentiles']:
        assert any('without latency' in annotation.text for annotation in charts[name].layout.annotations)
    assert '1 records without valid timestamps' in dashboard._service_history_description(frame)
    empty = dashboard.build_charts(frame.iloc[1:])
    assert all('No request history' in empty[name].layout.annotations[0].text
               for name in ['request_volume', 'response_time', 'error_rate', 'latency_percentiles'])


def test_generated_report_uses_current_routes_and_explains_time_window(dashboard, monkeypatch):
    frame = history(['2026-10-22T16:38:42Z'])
    monkeypatch.setattr(dashboard, 'load_requests_df', lambda: frame)
    monkeypatch.setattr(dashboard, 'write_dashboard', lambda name, content: content)
    html = dashboard.generate_dashboard()
    assert '1 calls' in html
    assert '1 second per bucket' in html
    assert 'Routes: /api/detect and /object-detection' in html
    assert html.count('class="chart-card service-chart"') == 4


def test_last_hour_filter_matches_metrics_and_charts_and_keeps_navigation(dashboard, monkeypatch):
    frame = history(['2026-10-21T12:00:00Z', '2026-10-22T15:59:59Z',
                     '2026-10-22T16:00:00Z', '2026-10-22T16:59:59Z', '2026-10-22T17:00:01Z'])
    monkeypatch.setattr(dashboard, 'load_requests_df', lambda: frame)
    monkeypatch.setattr(dashboard, 'write_dashboard', lambda name, content: content)
    html = dashboard.generate_dashboard('1h', now='2026-10-22T17:00:00Z')
    assert '2 calls' in html
    assert 'window=1h" aria-current="page"' in html
    assert 'window=all' in html
    empty = dashboard.generate_dashboard('1h', now='2027-01-01T00:00:00Z')
    assert 'No detection calls in this time range' in empty
    assert 'window=all' in empty
    with pytest.raises(ValueError):
        dashboard.generate_dashboard('invalid')
