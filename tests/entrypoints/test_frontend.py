from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from counter import config
from counter.adapters.database.count_mongo_repo import CountInMemoryRepo
from counter.domain.models import Prediction, Box
from counter.entrypoints.webapp import create_app


@pytest.fixture
def workspace(monkeypatch, tmp_path):
    class Detector:
        def predict(self, image):
            return [Prediction('car',.95,Box(10,10,35,35)), Prediction('free',.6,Box(40,10,60,35))]
    class Monitor:
        rows = []
        def log_request(self, **kwargs): self.rows.append(kwargs)
    repo, monitor = CountInMemoryRepo(), Monitor()
    monkeypatch.setattr(config,'get_repo',lambda:repo)
    monkeypatch.setattr(config,'get_monitor',lambda:monitor)
    monkeypatch.setattr(config,'get_detector',Detector)
    monkeypatch.setattr('counter.domain.actions.RESULTS_DIR',str(tmp_path/'results'))
    # Route's result root follows the test-only results directory.
    monkeypatch.setattr('counter.entrypoints.webapp.ROOT',tmp_path)
    with TestClient(create_app()) as client:
        yield client, repo, monitor


def image():
    stream = BytesIO(); Image.new('RGB',(100,80)).save(stream,'PNG'); return stream.getvalue()


def submit(client, **values):
    return client.post('/api/detect',data={'session_id':'frontend-test','counter':'true',**values},files={'file':('image.png',image(),'image/png')})


def test_frontend_gallery_detections_totals_and_downloads(workspace):
    client, repo, monitor = workspace
    assert client.get('/').status_code == 200
    assert client.get('/static/app.js').status_code == 200
    samples = client.get('/api/samples').json()
    assert len(samples) == 8
    assert client.get(samples[0]['url']).status_code == 200
    for total in (1,2):
        response = submit(client,threshold='.8')
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['counts'] == {'car':1}
        assert result['total_counts'] == {'car':total}
        assert result['detection_count'] == 1
        assert result['mean_confidence'] == .95
        assert result['width'] == 100
        assert result['predictions'][0]['box']['xmin'] == 10
        assert client.get(result['annotated_url']).headers['content-type'] == 'image/jpeg'
        original = client.get(result['image_url'])
        assert original.status_code == 200
        assert Image.open(BytesIO(original.content)).getexif() == {}
    assert client.get('/api/sessions/frontend-test').json()['total_counts'] == {'car':2}
    result = submit(client,counter='false').json()
    assert result['counts'] == {'car':1,'free':1}
    assert result['total_counts'] == {'car':2}
    assert len(monitor.rows) == 3
    assert all(row['provider'] == 'local' for row in monitor.rows)


def test_legacy_response_contract(workspace):
    client,_,_ = workspace
    r = client.post('/object-detection',data={'session_id':'legacy','counter':'true'},files={'file':('image.png',image(),'image/png')})
    assert r.status_code == 200
    assert set(r.json()) == {'current_objects','total_objects'}
    assert isinstance(client.post('/object-detection',data={'session_id':'legacy'},files={'file':('image.png',image(),'image/png')}).json(),list)


@pytest.mark.parametrize('values',[
    {'session_id':'../../etc'}, {'session_id':'a'*81}, {'threshold':'nan'}, {'threshold':'inf'},
    {'threshold':'1.1'}, {'threshold':'-.1'}, {'provider':'https://localhost'},
    {'provider':'roboflow','api_key':'key','workspace_name':'http://localhost'}, {'counter':'maybe'},
])
def test_rejects_bad_fields_without_counting(workspace,values):
    client,repo,monitor = workspace
    assert submit(client,**values).status_code == 400
    assert repo.read_values('frontend-test') == []
    assert monitor.rows == []


def test_rejects_invalid_oversized_and_animated_images(workspace):
    client,repo,monitor = workspace
    for content,status in [(b'fake image',400),(b'x'*(10*1024*1024+1),413)]:
        r=client.post('/api/detect',data={'session_id':'frontend-test'},files={'file':('bad.jpg',content,'image/jpeg')})
        assert r.status_code == status
    stream=BytesIO(); Image.new('RGB',(33,33)).save(stream,'GIF')
    assert client.post('/api/detect',data={'session_id':'frontend-test'},files={'file':('bad.gif',stream.getvalue(),'image/gif')}).status_code == 400
    large=BytesIO(); Image.new('RGB',(4001,4000)).save(large,'PNG')
    assert client.post('/api/detect',data={'session_id':'frontend-test'},files={'file':('large.png',large.getvalue(),'image/png')}).status_code == 400
    assert not monitor.rows


def test_cross_origin_and_path_traversal_are_blocked(workspace):
    client,_,_=workspace
    assert client.post('/api/detect',headers={'Origin':'https://untrusted.example'}).status_code == 403
    assert client.get('/api/samples/.env').status_code == 404
    assert client.get('/api/results/session/%2E%2E%2F.env').status_code == 404
    assert client.get('/dashboards/other.html').status_code == 404
    assert client.get('/').headers['x-content-type-options'] == 'nosniff'


def test_provider_failure_is_sanitized_and_logged_without_counting(workspace,monkeypatch):
    from counter.adapters.detection.roboflow_detector import RoboflowDetector, RoboflowError
    def fail(*args): raise RoboflowError('Roboflow denied access. Check your key and deployment permissions.')
    monkeypatch.setattr(RoboflowDetector,'predict',fail)
    client,repo,monitor = workspace
    response=submit(client,provider='roboflow',api_key='secret')
    assert response.status_code == 502
    assert 'secret' not in response.text
    assert not repo.read_values('frontend-test')
    assert monitor.rows[0]['success'] is False
    assert monitor.rows[0]['provider'] == 'roboflow'
    assert 'secret' not in str(monitor.rows)


def test_every_gallery_sample_is_a_supported_upload(workspace):
    client,_,_=workspace
    for sample in client.get('/api/samples').json():
        response=client.get(sample['url'])
        assert Image.open(BytesIO(response.content)).format in {'JPEG','PNG'}
        detection=client.post('/api/detect',data={'session_id':'gallery-test'},files={'file':(sample['id'],response.content,response.headers['content-type'])})
        assert detection.status_code == 200, sample['id'] + ': ' + detection.text


def test_orientation_metadata_animation_and_filename_safety(workspace):
    client,_,_=workspace
    photo=Image.new('RGB',(80,100)); exif=Image.Exif(); exif[274]=6; exif[270]='private metadata'
    content=BytesIO(); photo.save(content,'JPEG',exif=exif)
    response=client.post('/api/detect',data={'session_id':'safe-session'},files={'file':('../../attack.jpg',content.getvalue()+b'<script>unsafe</script>','image/jpeg')})
    assert response.status_code == 200
    body=response.json()
    assert body['image_name']=='attack.jpg'
    assert (body['width'],body['height']) == (100,80)
    original=client.get(body['image_url']).content
    assert not Image.open(BytesIO(original)).getexif()
    assert b'<script>' not in original
    animated=BytesIO()
    Image.new('RGB',(40,40),'red').save(animated,'PNG',save_all=True,append_images=[Image.new('RGB',(40,40),'blue')],duration=100,loop=0)
    assert client.post('/api/detect',data={'session_id':'safe-session'},files={'file':('animated.png',animated.getvalue(),'image/png')}).status_code == 400


def test_cloud_model_uses_the_same_counter_and_monitor(workspace,monkeypatch):
    from counter.adapters.detection.roboflow_detector import RoboflowDetector
    monkeypatch.setattr(RoboflowDetector,'predict',lambda self,image:[Prediction('bicycle',.85,Box(0,0,30,30))])
    client,repo,monitor=workspace
    body=submit(client,provider='roboflow',api_key='private-key',roboflow_mode='model',model_id='bicycles/2').json()
    assert body['provider']=='roboflow'
    assert body['counts']=={'bicycle':1}
    assert body['total_counts']=={'bicycle':1}
    assert monitor.rows[0]['provider']=='roboflow'
    assert monitor.rows[0]['persisted_counts']=={'bicycle':1}
    assert 'private-key' not in str(monitor.rows)


def test_chunked_body_limit_is_enforced_before_form_parsing(workspace):
    client,repo,monitor=workspace
    def chunks():
        for _ in range(11):
            yield b'x'*(1024*1024)
    response=client.post('/api/detect',content=chunks(),headers={'Content-Type':'application/octet-stream'})
    assert response.request.headers.get('Transfer-Encoding') == 'chunked'
    assert 'Content-Length' not in response.request.headers
    assert response.status_code == 413
    assert not monitor.rows
