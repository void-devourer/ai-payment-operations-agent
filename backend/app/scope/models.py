"""Bounded public inputs and exact acceptance payloads for Scope & Pay."""
import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Text = Annotated[str, Field(strict=True, min_length=1, max_length=6000)]
Name = Annotated[str, Field(strict=True, min_length=1, max_length=160)]
Count = Annotated[int, Field(strict=True, ge=1, le=100000000)]
Version = Annotated[int, Field(strict=True, ge=1, le=100000000)]


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, str_strip_whitespace=True)

    @field_validator('*')
    @classmethod
    def postgres_text(cls, value):
        if isinstance(value, str) and '\x00' in value:
            raise ValueError('Text cannot contain null characters')
        return value


class ProjectInput(Input):
    name: Name
    client_name: Name
    client_email: Annotated[str, Field(strict=True, min_length=3, max_length=254, pattern=r'^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$')]
    brief: Text
    base_amount_minor: Count
    currency: Literal['usd'] = 'usd'


class BriefInput(Input):
    brief: Text
    expected_revision: Version


class MessageInput(Input):
    text: Text


class AnalysisInput(Input):
    mode: Literal['sample', 'openai', 'gemini']


class EvidenceInput(Input):
    message_id: Annotated[str, Field(strict=True, min_length=1, max_length=100)]
    quote: Annotated[str, Field(strict=True, min_length=1, max_length=2000)]


class ProposalInput(Input):
    title: Annotated[str, Field(strict=True, min_length=1, max_length=120)]
    description: Annotated[str, Field(strict=True, min_length=1, max_length=1000)]
    amount_minor: Count
    evidence: Annotated[list[EvidenceInput], Field(min_length=1, max_length=10)]
    expected_brief_revision: Version


class ProposalEdit(ProposalInput):
    expected_version: Version


class ShareInput(Input):
    expected_version: Version


class DecisionInput(Input):
    decision: Literal['accepted', 'declined']
    name: Name
    proposal_version: Version
    proposal_digest: Annotated[str, Field(strict=True, pattern=r'^[a-f0-9]{64}$')]


class InvoiceInput(Input):
    proposal_id: Annotated[str, Field(strict=True, min_length=1, max_length=100)]
    mode: Literal['local', 'paypal_sandbox']


class Empty(Input):
    pass


def canonical_digest(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def connection_digest(connection):
    return canonical_digest({'client_id': connection.client_id, 'merchant_id': connection.merchant_id,
                             'environment': connection.environment})


def proposal_digest(project, body, version):
    """Everything the client consents to, including the complete original brief."""
    return canonical_digest({'project_id': project['project_id'], 'brief': project['brief'],
        'brief_revision': project['brief_revision'], 'proposal_version': version,
        'title': body['title'], 'description': body['description'],
        'amount_minor': body['amount_minor'], 'currency': 'usd', 'evidence': body['evidence']})
