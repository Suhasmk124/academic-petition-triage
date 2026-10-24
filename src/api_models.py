"""API contracts. Execution state is separate from the academic-review recommendation."""
from typing import Literal
from uuid import UUID
from pydantic import Field, field_validator
from assessment import Contract, PetitionRequest
from service_config import ExecutionMode

JobStatus = Literal['QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED']

class Submission(PetitionRequest):
    synthetic: Literal[True]

    @field_validator('synthetic', mode='before')
    @classmethod
    def synthetic_only(cls, value):
        if value is not True:
            raise ValueError('Only explicitly synthetic petitions are accepted')
        return value

class AcceptedRun(Contract):
    run_id: UUID
    status: Literal['QUEUED'] = 'QUEUED'
    mode: ExecutionMode
    correlation_id: UUID
    poll_url: str


class Feedback(Contract):
    rating: Literal['helpful', 'needs_review']
    category: Literal['none', 'missing_rule', 'incorrect_citation', 'unclear', 'other'] = 'none'
    comment: str = Field(default='', max_length=500)
    synthetic: Literal[True]
    @field_validator('synthetic', mode='before')
    @classmethod
    def synthetic_only(cls, value):
        if value is not True:
            raise ValueError('Only explicitly synthetic feedback is accepted')
        return value

class RunView(Contract):
    run_id: UUID
    status: JobStatus
    mode: ExecutionMode
    correlation_id: UUID
    created_at: float
    updated_at: float
    attempts: int
    triage_status: str | None = None
    result: dict | None = None
    error: dict | None = None
