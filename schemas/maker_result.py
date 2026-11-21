from typing import List, Optional
from pydantic import BaseModel, Field

class MakerResultSchema(BaseModel):
    """Result report produced by ANTIGRAVITY MAKER."""
    status: str = Field(..., description="Execution status: COMPLETED or FAILED")
    files_modified: List[str] = Field(
        default_factory=list,
        description="List of relative file paths modified by the maker"
    )
    commands_run: List[str] = Field(
        default_factory=list,
        description="List of terminal commands executed by the maker"
    )
    summary: str = Field(..., description="Summary of work performed")
    error: Optional[str] = Field(
        default=None,
        description="Error message if status is FAILED"
    )
