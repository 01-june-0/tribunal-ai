from typing import Any, List, Literal
from pydantic import BaseModel, Field, field_validator


class InspectorTest(BaseModel):
    """A new test file proposed by the inspector (text only; the Director writes and runs it)."""
    path: str
    content: str

class ReviewResultSchema(BaseModel):
    """Result report produced by CODEX INSPECTOR."""
    verdict: Literal["pass", "changes_required"] = Field(
        ...,
        description="Review verdict: pass or changes_required"
    )
    p0: List[str] = Field(
        default_factory=list,
        description="Blocker bugs, regressions, or severe security/architectural flaws"
    )
    p1: List[str] = Field(
        default_factory=list,
        description="High-priority bugs, missing critical tests, or scope concerns"
    )
    p2: List[str] = Field(
        default_factory=list,
        description="Minor improvements, style nitpicks, or suggestions"
    )
    summary: str = Field(..., description="Summary of the code review")
    tests: List[InspectorTest] = Field(
        default_factory=list,
        description="Optional new test files for the Director to run (see core/inspector_tests.py)"
    )

    @field_validator("tests", mode="before")
    @classmethod
    def _only_well_formed_tests(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return []
        return [t for t in value if isinstance(t, InspectorTest)
                or (isinstance(t, dict) and isinstance(t.get("path"), str) and isinstance(t.get("content"), str)
                    and len(t["content"]) <= 20_000 and len(t["path"]) <= 300)][:5]
