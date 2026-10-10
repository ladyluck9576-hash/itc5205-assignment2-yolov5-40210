"""Derive transparent summary metrics from recorded AWS responses and REPORT logs."""
import json, re, statistics
from pathlib import Path
root=Path(__file__).resolve().parents[1]; results=root/'test-results'
def read(name): return json.loads((results/name).read_text())
reports=[]
for e in read('cloudwatch-events.json'):
    m=e['message']
    if not m.startswith('REPORT RequestId:'): continue
    def field(name):
        match=re.search(re.escape(name)+r': ([\d.]+)',m)
        return float(match.group(1)) if match else None
    reports.append({'request_id':m.split()[2], 'duration_ms':field('Duration'),
        'billed_ms':field('Billed Duration'),'memory_mb':field('Memory Size'),
        'max_memory_mb':field('Max Memory Used'),'init_ms':field('Init Duration'),
        'log_stream':e['logStreamName'],'raw':m.strip()})
direct=read('cloud-lambda-tests.json')
comparison=[]
for memory, entries in [(1024,direct[1:4]),(2048,direct[4:7])]:
    ids=[json.loads(x['payload']['body'])['request_id'] for x in entries]
    selected=[r for r in reports if r['request_id'] in ids]
    warm=[r for r in selected if r['init_ms'] is None]
    comparison.append({'memory_mb':memory,'runs':len(selected),'warm_runs':len(warm),
        'mean_duration_ms':round(statistics.mean(r['duration_ms'] for r in selected),3),
        'mean_warm_duration_ms':round(statistics.mean(r['duration_ms'] for r in warm),3),
        'mean_warm_gb_seconds':round(statistics.mean(r['billed_ms']/1000*memory/1024 for r in warm),4),
        'max_memory_mb':max(r['max_memory_mb'] for r in selected),
        'init_ms':[r['init_ms'] for r in selected if r['init_ms'] is not None]})
http=read('cloud-http-tests.json')
cold=read('cloud-api-cold-probe.json')['requests'] if (results/'cloud-api-cold-probe.json').exists() else []
for item in cold:
    item['report']=next((r for r in reports if r['request_id']==item['response']['request_id']),None)
gb_seconds=sum(r['billed_ms']/1000*r['memory_mb']/1024 for r in reports)
summary={'http_requests':len(http)+len(cold),'direct_requests':len(direct),
    'http_successes':sum(x['http_status']==200 for x in http+cold),
    'http_5xx':sum(x['http_status']>=500 for x in http+cold),
    'http_5xx_explanation':'One deliberate S3 write-denial test; restored request succeeded',
    'reports':reports,'comparison':comparison,'cold_probe':cold,
    'observed_billed_gb_seconds':round(gb_seconds,6),
    'estimated_lambda_usd_before_free_allowances':round(gb_seconds*0.0000166667+len(reports)*0.20/1000000,8),
    'cost_scope':'Lambda REPORT-based compute and requests only; excludes S3, API Gateway, DynamoDB, logs, transfer and tax; not an account invoice',
    'cost_rate_source':'https://aws.amazon.com/lambda/pricing/',
    'concurrency':read('cloud-concurrency.json')}
(results/'cloud-analysis.json').write_text(json.dumps(summary,indent=2))
print(json.dumps({k:v for k,v in summary.items() if k not in ('reports','cold_probe')},indent=2))
