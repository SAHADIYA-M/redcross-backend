from pydantic import BaseModel

class Need(BaseModel):
    id: int
    code: str
    name: str

class Priority(BaseModel):
    id: int
    code: str
    name: str
