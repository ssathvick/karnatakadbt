"""Native approval-policy contracts, independent of the former workflow runtime."""
from typing import Any
from pydantic import BaseModel, Field, field_validator


class Rule(BaseModel):
    rule_type: str
    rule_value: dict[str, Any]
    kind: str = 'approver'
    required: bool = False

    @field_validator('rule_type')
    @classmethod
    def rule_type_valid(cls, value):
        if value not in {'user', 'role', 'group', 'expression', 'http'}:
            raise ValueError('Unsupported approver rule type')
        return value

    @field_validator('kind')
    @classmethod
    def kind_valid(cls, value):
        if value not in {'approver', 'observer'}:
            raise ValueError('Unsupported approver rule kind')
        return value


class Stage(BaseModel):
    name: str
    stage_order: int = Field(ge=1)
    mode: str = 'all'
    mode_value: int | None = Field(default=None, ge=1)
    sla_hours: int | None = Field(default=None, ge=1)
    skip_if: dict[str, Any] | None = None
    on_empty: str = 'block'
    parallel_group: int | None = None
    on_breach: str | None = None
    escalation_rules: list[Rule] = Field(default_factory=list)
    rules: list[Rule] = Field(default_factory=list)

    @field_validator('mode')
    @classmethod
    def mode_valid(cls, value):
        value = value.lower()
        if value not in {'all', 'any-n', 'quorum', 'percentage'}:
            raise ValueError('Unsupported approval mode')
        return value

    @field_validator('on_empty')
    @classmethod
    def empty_valid(cls, value):
        if value not in {'skip', 'block'}:
            raise ValueError('Unsupported empty-stage action')
        return value

    @field_validator('on_breach')
    @classmethod
    def breach_valid(cls, value):
        if value is not None and value not in {'notify', 'auto_approve', 'auto_reject', 'escalate'}:
            raise ValueError('Unsupported deadline action')
        return value


class PolicyInput(BaseModel):
    policy_key: str = Field(max_length=128)
    name: str = Field(max_length=255)
    description: str | None = Field(default=None, max_length=1024)
    artifact_type: str = Field(max_length=128)
    forbid_self_approval: bool = False
    forbid_repeat_approvers: bool = False
    stages: list[Stage] = Field(default_factory=list)


class ApprovalFailure(ValueError):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message
        super().__init__(message)
