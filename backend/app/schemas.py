from typing import Any, Literal
from typing import Literal

from pydantic import BaseModel, Field
from app.services.parser import ChunkingConfig


class SetupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=120)
    # Keep this in sync with the authentication form. Passwords are measured
    # in Unicode characters at the API boundary; the auth service pre-hashes
    # them before bcrypt so multi-byte passwords are not rejected at 72 bytes.
    password: str = Field(min_length=8, max_length=72)


class LoginRequest(SetupRequest):
    pass


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = None


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None


class KnowledgeBaseCreate(BaseModel):
    workspace_id: str
    name: str = Field(min_length=1, max_length=160)
    description: str | None = None
    chunking_config: ChunkingConfig | None = None


class ChunkingConfigRequest(ChunkingConfig):
    pass


class ChunkerPreviewRequest(BaseModel):
    text: str = Field(min_length=1, max_length=65536)
    chunking_config: ChunkingConfig = Field(default_factory=ChunkingConfig)


class FolderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    parent_id: str | None = None


class FolderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    parent_id: str | None = None


class SessionCreate(BaseModel):
    workspace_id: str
    knowledge_base_id: str | None = None
    model_id: str | None = None


class MessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    model_id: str | None = None


class ConversationMessageRequest(MessageRequest):
    mode: Literal["rag", "agent"]


class ChunkUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=100000)
    version: int


class MemoryCreate(BaseModel):
    workspace_id: str
    type: Literal["profile", "preference", "fact", "task", "interest"]
    content: str = Field(min_length=1, max_length=2000)


class MemoryUpdate(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=2000)
    type: str | None = None


class ModelProfileCreate(BaseModel):
    workspace_id: str
    provider: Literal["openai", "deepseek"]
    base_url: str
    model_name: str
    api_key: str | None = None
    supports_tools: bool = True
    supports_reasoning: bool = False
    is_default_rag: bool = False
    is_default_agent: bool = False


class McpServerCreate(BaseModel):
    workspace_id: str
    name: str = Field(min_length=1, max_length=160)
    transport: Literal["stdio", "sse", "streamable_http"]
    command: str | None = None
    args: list[str] = []
    endpoint: str | None = None
    auth_type: Literal["none", "bearer", "api_key"] | None = None
    auth_secret: str | None = None
    enabled: bool = False
    timeout_seconds: int = Field(default=30, ge=1, le=120)


class SearchRequest(BaseModel):
    workspace_id: str
    knowledge_base_id: str
    query: str = Field(min_length=1, max_length=20000)
    folder_id: str | None = None
    top_k: int = Field(default=8, ge=1, le=50)
