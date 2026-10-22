from io import BytesIO

import httpx
import pytest
from PIL import Image

from counter.adapters.detection.roboflow_detector import RoboflowDetector, RoboflowError, RoboflowOptions


def image():
    data = BytesIO()
    Image.new('RGB', (100, 80)).save(data, 'JPEG')
    data.seek(0)
    return data


def transport(monkeypatch, response, status=200):
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(status, json=response)
    original = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))
    return requests


def detection(**overrides):
    return {'class':'car','confidence':.91,'x':50,'y':40,'width':20,'height':10,**overrides}


def test_workflow_uses_fixed_origin_header_auth_and_converts_center_boxes(monkeypatch):
    requests = transport(monkeypatch, {'outputs':[{'predictions':{'predictions':[detection()]}}]})
    result = RoboflowDetector(RoboflowOptions(api_key='test-secret')).predict(image())
    assert result[0].class_name == 'car'
    assert result[0].box.xmin == 40
    assert result[0].box.ymax == 45
    request = requests[0]
    assert str(request.url) == 'https://serverless.roboflow.com/model-version2/workflows/parking-detection-v3-logic'
    assert request.headers['Authorization'] == 'Bearer test-secret'
    assert b'test-secret' not in request.content
    import json
    body = json.loads(request.content)
    assert body['use_cache'] is True
    assert body['inputs']['image']['type'] == 'base64'


def test_model_and_empty_predictions(monkeypatch):
    requests = transport(monkeypatch, {'predictions':[]})
    assert RoboflowDetector(RoboflowOptions(api_key='test-secret',mode='model',model_id='parking/3')).predict(image()) == []
    assert requests[0].url.host == 'detect.roboflow.com'
    assert requests[0].url.path == '/parking/3'
    assert 'api_key' not in requests[0].url.params


def test_nested_output_rescales_to_original_image(monkeypatch):
    transport(monkeypatch, {'outputs':[{'detections':{'cars':{'image':{'width':200,'height':160},'predictions':[detection(x=100,y=80,width=40,height=20)]}}}]})
    result = RoboflowDetector(RoboflowOptions(api_key='test',output_path='detections.cars')).predict(image())
    assert result[0].box.xmin == 40
    assert result[0].box.ymax == 45


@pytest.mark.parametrize('response',[
    {'outputs':[{'predictions':{'predictions':[{'class':'car','confidence':.8}]}}]},
    {'outputs':[{'visualization':{'type':'base64','value':'abc'}}]},
    {'outputs':[{'predictions':{'predictions':[detection(confidence=float('inf'))]}}]},
    {'outputs':[{'predictions':{'predictions':[detection(width=-2)]}}]},
])
def test_rejects_unsupported_outputs(response):
    with pytest.raises(RoboflowError):
        RoboflowDetector(RoboflowOptions(api_key='test'))._parse(response,100,80)


@pytest.mark.parametrize('kwargs',[
    {'workspace':'http://localhost'}, {'workflow_id':'../../secret'},
    {'mode':'model','model_id':'https://127.0.0.1/3'}, {'output_path':'../key'},
    {'api_key':'bad\nheader'}, {'mode':'custom'},
])
def test_rejects_unsafe_configuration(kwargs):
    with pytest.raises(ValueError):
        RoboflowOptions(**{'api_key':'test',**kwargs})


def test_upstream_error_does_not_expose_response_body_or_key(monkeypatch):
    transport(monkeypatch, {'error':'test-secret'}, 403)
    with pytest.raises(RoboflowError) as error:
        RoboflowDetector(RoboflowOptions(api_key='test-secret')).predict(image())
    assert 'test-secret' not in str(error.value)
    assert 'test-secret' not in repr(RoboflowOptions(api_key='test-secret'))


def test_does_not_follow_redirects(monkeypatch):
    requests = transport(monkeypatch, {}, 302)
    with pytest.raises(RoboflowError):
        RoboflowDetector(RoboflowOptions(api_key='test-secret')).predict(image())
    assert len(requests) == 1
