#!/usr/bin/env python3
"""Local docs contract consistency gate. No network, no service availability assertions.
Run from repository root: python contracts/tests/validate_contracts.py
Needs PyYAML and jsonschema.
"""
from pathlib import Path
from urllib.parse import unquote
import json
import re
import sys
import yaml
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / 'contracts'
ERRORS = []


def fail(message):
    ERRORS.append(str(message))


def readj(path):
    return json.loads(path.read_text(encoding='utf-8'))


def collect_refs(node, prefix='#/components/schemas/'):
    if isinstance(node, dict):
        if isinstance(node.get('$ref'), str) and node['$ref'].startswith(prefix):
            yield node['$ref'][len(prefix):].split('/')[0]
        for value in node.values():
            yield from collect_refs(value, prefix)
    elif isinstance(node, list):
        for item in node:
            yield from collect_refs(item, prefix)


# Every internal Markdown link must resolve to a real path; avoid broken README / handoffs.
for file in ROOT.rglob('*.md'):
    if '.git' in file.parts:
        continue
    text = file.read_text(encoding='utf-8')
    for dest in re.findall(r'(?<!!)\[[^\]]+\]\(([^)]+)\)', text):
        path = unquote(dest.split('#', 1)[0].split(' ', 1)[0].strip('<>'))
        if not path or path.startswith(('http://', 'https://', 'mailto:', '/', 'data:')):
            continue
        if not (file.parent / path).exists():
            fail(f'Broken Markdown link in {file.relative_to(ROOT)}: {dest}')

# Legacy typo must be corrected by explicit rename; do not carry conflicting copies.
if (ROOT / '08_INFRA_AND_DEMO 1.md').exists():
    fail('Old infra filename still in tree; delete 08_INFRA_AND_DEMO 1.md')
if not (ROOT / '08_INFRA_AND_DEMO.md').exists():
    fail('Canonical 08_INFRA_AND_DEMO.md missing')

openapis = {}
operation_ids = set()
for file in (PACK / 'openapi').glob('*.yaml'):
    doc = yaml.safe_load(file.read_text(encoding='utf-8'))
    openapis[file.name] = doc
    if not str(doc.get('openapi', '')).startswith('3.1.'):
        fail(f'{file.name}: OpenAPI must be 3.1.x')
    schemas = doc.get('components', {}).get('schemas', {})
    missing = set(collect_refs(doc)) - set(schemas)
    for name in missing:
        fail(f'{file.name}: dangling schema ref {name}')
    for path, routes in doc.get('paths', {}).items():
        for verb, op in routes.items():
            if verb not in {'get','post','put','patch','delete'}:
                continue
            oid = op.get('operationId')
            if not oid:
                fail(f'{file.name} {verb} {path}: no operationId')
            # cross-spec operation IDs may repeat: namespaced to avoid false positives
            elif (file.name, oid) in operation_ids:
                fail(f'{file.name}: duplicate operationId {oid}')
            operation_ids.add((file.name, oid))
            for status, response in op.get('responses', {}).items():
                if 'application/problem+json' in response.get('content', {}):
                    fail(f'{file.name} {verb} {path} {status}: obsolete problem+json envelope')

pub = openapis.get('main-public.openapi.yaml', {})
internal_ai = openapis.get('ai-internal.openapi.yaml', {})
callbacks = openapis.get('main-callbacks.openapi.yaml', {})
if any(x.startswith('/internal') for x in pub.get('paths', {})):
    fail('Internal callback routes leaked into public API')
if '/api/v1/auth/ws-ticket' not in pub.get('paths', {}):
    fail('Public ws-ticket endpoint missing')
if len(internal_ai.get('paths', {})) < 5 or len(callbacks.get('paths', {})) < 3:
    fail('Private API incomplete')
for name, d in [('ai-internal',internal_ai), ('main-callbacks',callbacks)]:
    if d.get('security') != [{'ServiceAuth': []}]:
        fail(f'{name} requires separate service auth')

token_schema = pub.get('components',{}).get('schemas',{}).get('AuthTokens',{})
if 'refresh_token' in token_schema.get('properties', {}):
    fail('AuthTokens leaks refresh_token in JSON')
for path in ('/api/v1/auth/refresh','/api/v1/auth/logout'):
    if pub['paths'][path]['post'].get('requestBody'):
        fail(f'{path} unexpectedly requires refresh body instead of HttpOnly cookie')
    if not any(x.get('name')=='X-CSRF-Token' for x in pub['paths'][path]['post'].get('parameters', [])):
        fail(f'{path} missing CSRF header')

for file in (PACK / 'schemas').glob('*.json'):
    try:
        Draft202012Validator.check_schema(readj(file))
    except Exception as exc:
        fail(f'Invalid JSON schema {file.name}: {exc}')

fixture_map = {
    'ai-start.request.json':'ai-start-request.schema.json',
    'ai-result.callback.json':'ai-result-callback.schema.json',
    'ai-event.tool-completed.json':'ai-events.schema.json',
    'rca-report.json':'rca-report.schema.json',
    'alertmanager.request.json':'alertmanager-webhook.schema.json',
    'ws.subscribe.json':'websocket.schema.json',
    'ws.project-subscribe.json':'websocket.schema.json',
    'ws.subscription-ack.json':'websocket.schema.json',
    'ws.incident-updated.json':'websocket.schema.json',
    'auth-login.challenge.response.json':'email-otp.schema.json',
    'auth-otp-resend.request.json':'email-otp.schema.json',
    'auth-otp-resend.response.json':'email-otp.schema.json',
    'auth-otp-verify.request.json':'email-otp.schema.json',
    'auth.tokens.response.json':'auth-tokens.schema.json',
    'mcp.search-logs.output.json':'mcp-results.schema.json'
}
for fixture, schema_file in fixture_map.items():
    try:
        instance=readj(PACK/'examples'/fixture)
        schema=readj(PACK/'schemas'/schema_file)
        errs=list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(instance))
        for err in errs[:3]:fail(f'Fixture {fixture} invalid against {schema_file}: {err.message}')
    except FileNotFoundError as exc:
        fail(f'Fixture/schema missing: {exc}')
    except Exception as exc:
        fail(f'Fixture {fixture}: validator failed: {exc}')

# Negative check: callback missing event_id or finished_at MUST NOT pass.
res=readj(PACK/'schemas/ai-result-callback.schema.json')
inst=readj(PACK/'examples/ai-result.callback.json')
for field in ('event_id','finished_at'):
    wrong={k:v for k,v in inst.items() if k!=field}
    if Draft202012Validator(res).is_valid(wrong):
        fail(f'Result callback wrong acceptance: missing {field}')

catalog=readj(PACK/'mcp/tool-catalog.json')
for name, tool in catalog.get('tools', {}).items():
    for contract in ('inputSchema','outputSchema'):
        schema={'$schema':'https://json-schema.org/draft/2020-12/schema','$defs':catalog['$defs'],**tool[contract]}
        try:
            Draft202012Validator.check_schema(schema)
        except Exception as exc:
            fail(f'MCP {name} {contract} invalid: {exc}')
for stale in ('get_container_status','get_container_events'):
    if stale in catalog.get('tools',{}):fail(f'Obsolete MCP name still exposed: {stale}')
for name in ('search_logs','query_prometheus','get_trace','get_pod_status','get_pod_events'):
    if name not in catalog.get('tools',{}):fail(f'Required MCP tool missing: {name}')

# Machine-readable contracts must not contain old deployment/source terms or obsolete auth body.
for file in [*PACK.glob('openapi/*.yaml'),*PACK.glob('schemas/*.json'),*PACK.glob('mcp/*.json')]:
    raw=file.read_text(encoding='utf-8').lower()
    for stale in ('elasticsearch','kibana','application/problem+json'):
        if stale in raw:fail(f'Obsolete source/protocol {stale} in {file.relative_to(ROOT)}')

if ERRORS:
    for err in ERRORS:
        print('FAIL:',err)
    print(f'FAIL: {len(ERRORS)} problems')
    sys.exit(1)
print(f'PASS: {len(openapis)} OpenAPI; {len(list((PACK/"schemas").glob("*.json")))} JSON Schemas; '
      f'{len(fixture_map)} validated fixtures; {len(catalog["tools"])} MCP tools; Markdown links resolved.')
print('NOTE: This validates documentation only. Provider/consumer and live infrastructure tests are NOT run.')
