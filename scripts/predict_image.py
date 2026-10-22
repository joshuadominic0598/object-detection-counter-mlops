"""Submit local image paths to the running app; no host dependencies required."""
import argparse
import json
import mimetypes
import os
from pathlib import Path
import secrets
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('images', nargs='+', type=Path)
    parser.add_argument('--provider', choices=['local','roboflow'], default='local')
    parser.add_argument('--session', default='cli-session')
    parser.add_argument('--threshold', type=float, default=.5)
    parser.add_argument('--no-count', action='store_true')
    parser.add_argument('--workspace', default='model-version2')
    parser.add_argument('--workflow', default='parking-detection-v3-logic')
    parser.add_argument('--model', help='Use a hosted detection model ID, e.g. parking/3')
    parser.add_argument('--output', default='predictions', help='Workflow prediction output field path')
    parser.add_argument('--port', type=int, default=5000)
    args = parser.parse_args()
    if len(args.images) > 20:
        parser.error('Use up to 20 images per batch.')
    for path in args.images:
        if not path.is_file() or path.stat().st_size > 10*1024*1024:
            parser.error(f'{path}: expected an existing image no larger than 10 MB.')
    fields = {'provider':args.provider,'session_id':args.session,'threshold':str(args.threshold),
              'counter':str(not args.no_count).lower(),'workspace_name':args.workspace,
              'workflow_id':args.workflow,'output_path':args.output,
              'roboflow_mode':'model' if args.model else 'workflow','model_id':args.model or ''}
    if args.provider == 'roboflow' and os.getenv('ROBOFLOW_API_KEY'):
        fields['api_key'] = os.environ['ROBOFLOW_API_KEY']
    failed = False
    for path in args.images:
        boundary = secrets.token_hex(24)
        parts = []
        for key,value in fields.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
        filename = path.name.replace('"','_').replace('\r','_').replace('\n','_')
        mime = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: {mime}\r\n\r\n'.encode())
        parts.extend([path.read_bytes(),f'\r\n--{boundary}--\r\n'.encode()])
        request = Request(f'http://localhost:{args.port}/api/detect',data=b''.join(parts),
                          headers={'Content-Type':f'multipart/form-data; boundary={boundary}'})
        try:
            with urlopen(request,timeout=120) as response:
                print(json.dumps(json.load(response),ensure_ascii=False))
        except HTTPError as error:
            failed = True
            print(f'{path.name}: HTTP {error.code}: {error.read().decode(errors="replace")}',file=sys.stderr)
        except (URLError, TimeoutError):
            failed = True
            print(f'{path.name}: cannot reach the app; run make start and check the port.',file=sys.stderr)
    return int(failed)


if __name__ == '__main__':
    sys.exit(main())
