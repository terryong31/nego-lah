from pydantic import BaseModel
from typing import List

class UserSchema(BaseModel):
    username: str
    password: str
    
class ItemSchema(BaseModel):
    item_id: str
    name: str
    description: str
    condition: str
    images: str