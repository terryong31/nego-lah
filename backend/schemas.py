from pydantic import BaseModel

class UserSchema(BaseModel):
    username: str
    password: str
    
class ItemSchema(BaseModel):
    id: int
    name: str
    description: str
    condition: str
    image_path: str