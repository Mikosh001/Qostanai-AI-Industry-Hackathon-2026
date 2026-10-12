"""Verify exported evidence metadata against an independently obtained hub key."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.signed_export import verify_report
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('report',type=Path)
parser.add_argument('--public-key',required=True,help='Trusted public key from the university administrator, not from the report itself')
args=parser.parse_args()
try:
    value=verify_report(json.loads(args.report.read_text(encoding='utf-8')),args.public_key)
    print(json.dumps({'signature_valid':True,'session_id':value['session']['id'],'integrity_ok':value['integrity_ok']},ensure_ascii=False))
except Exception as exc:
    print('Verification failed: '+str(exc),file=sys.stderr);sys.exit(1)
