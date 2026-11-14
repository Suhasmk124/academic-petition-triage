"""API contracts. Execution state is separate from the academic-review recommendation."""
from typing import Literal
from uuid import UUID
from pydantic import Field, StrictBool, field_validator
from assessment import Contract, PetitionRequest
from service_config import ExecutionMode
from position import PetitionFacts

JobStatus = Literal['QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED']

class Submission(PetitionRequest):
    synthetic: Literal[True]
    facts: PetitionFacts | None = None

    @field_validator('synthetic', mode='before')
    @classmethod
    def synthetic_only(cls, value):
        if value is not True:
            raise ValueError('Only explicitly synthetic petitions are accepted')
        return value

class SupportingDocument(Contract):
    content: str = Field(min_length=1, max_length=6_990_508)


class PrivateSubmission(PetitionRequest):
    synthetic: StrictBool = False
    facts: PetitionFacts | None = None
    attachment: SupportingDocument | None = None


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

class AccountInput(Contract):
    username: str = Field(min_length=3, max_length=32,pattern=r'^[a-z][a-z0-9_.-]+$')
    password: str = Field(min_length=12,max_length=128)
    role: Literal['student','reviewer']


class OfficerReview(Contract):
    outcome: Literal['needs_information','recommend_exception','recommend_standard_rule']
    note: str = Field(min_length=1,max_length=1200)

    @field_validator('note')
    @classmethod
    def clean_note(cls,value):
        if not value.strip():
            raise ValueError('Enter a reviewer note')
        return value.strip()


class RunView(Contract):
    run_id: UUID
    status: JobStatus
    mode: ExecutionMode
    correlation_id: UUID
    created_at: float
    updated_at: float
    attempts: int
    private_petition: str | None = None
    attachment_available: bool = False
    attendance_percent: float | None = None
    officer_review: dict | None = None
    triage_status: str | None = None
    result: dict | None = None
    error: dict | None = None
