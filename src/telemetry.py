"""Payload-free OpenTelemetry spans and process-local HTTP Prometheus metrics."""
import os
import time
from contextlib import contextmanager
from opentelemetry import trace, propagate
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import CollectorRegistry, Counter, Histogram, Gauge

_provider = None


def tracer():
    global _provider
    if _provider is None:
        _provider = TracerProvider(resource=Resource.create({'service.name': os.getenv('OTEL_SERVICE_NAME', 'petition-triage')}))
        endpoint = os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT')
        if endpoint:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            _provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint.rstrip('/')+'/v1/traces', timeout=3)))
    return _provider.get_tracer('petition-triage')


def carrier():
    result = {}
    propagate.inject(result)
    return result.get('traceparent')


@contextmanager
def span(name, parent=None, **attributes):
    context = propagate.extract({'traceparent': parent}) if parent else None
    with tracer().start_as_current_span(name, context=context) as current:
        for key, value in attributes.items():
            if value is not None:
                current.set_attribute(key, value)
        yield current


class HttpMetrics:
    def __init__(self):
        self.registry = CollectorRegistry()
        self.requests = Counter('triage_http_requests_total', 'HTTP requests', ['route','status'], registry=self.registry)
        self.duration = Histogram('triage_http_duration_seconds', 'HTTP duration', ['route'], registry=self.registry)
        started=time.monotonic()
        Gauge('triage_uptime_seconds','API process uptime',registry=self.registry).set_function(lambda:time.monotonic()-started)
