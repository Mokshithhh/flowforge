from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=72)
    organization_name: str = Field(min_length=1, max_length=160)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class WorkflowInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    definition: dict


class ExecuteInput(BaseModel):
    input: dict = Field(default_factory=dict)


class AgentRequest(BaseModel):
    prompt: str = Field(min_length=5, max_length=4000)
