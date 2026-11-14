"""Expose only fixed diagnostic messages, never raw provider output or request text."""

MESSAGES = {
    'RATE_LIMITED': 'The provider rate limit was reached. Wait for the quota to reset.',
    'QUOTA_WAIT': 'The provider quota needs a longer reset interval than this run allows.',
    'CONTEXT_BUDGET': 'The request would exceed the provider token limit.',
    'REQUEST_BUDGET': 'The run used its allowed number of hosted requests.',
    'TOOL_FORMAT_REJECTED': 'The provider rejected the tool-output format.',
    'PROVIDER_HTTP_ERROR': 'The provider rejected the request.',
    'CONFIGURATION_UNAVAILABLE': 'Hosted model configuration is unavailable.',
    'TRUNCATED_OR_FILTERED': 'The provider truncated or filtered the response.',
    'REFUSED': 'The model refused the request.',
    'TRANSPORT_FAILURE': 'The provider connection failed after retrying.',
    'TIMEOUT': 'The provider timed out after retrying.',
    'INVALID_RESPONSE': 'The response did not match the provider response format.',
    'AGENT_CONTRACT_FAILED': 'The agent output did not pass the workflow contract.',
    'CIRCUIT_OPEN': 'The provider circuit is temporarily open.',
    'MODEL_UNAVAILABLE': 'The hosted model could not finish this run.',
}


def hosted_failure_details(result):
    code = result.get('hosted_failure_code')
    code = code if code in MESSAGES else 'MODEL_UNAVAILABLE'
    metrics = result.get('metrics') or []
    role = metrics[-1].get('agent') if metrics else None
    details = {'code':code, 'message':MESSAGES[code]}
    if role in ('investigator','verifier'):
        details['role'] = role
    events = result.get('model_usage') or []
    if events and code in ('RATE_LIMITED','PROVIDER_HTTP_ERROR','TOOL_FORMAT_REJECTED'):
        status = events[-1].get('http_status')
        if type(status) is int and 400 <= status <= 599:
            details['http_status'] = status
    return details
