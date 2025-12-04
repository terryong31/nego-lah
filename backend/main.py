from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from login.user_crud import authentication, register_new_user
from items.retrieve import all_items, get_item_by_id
from schemas import UserSchema, ItemSchema
from admin.upload import upload_item
from login.user_crud import create_access_token

# API Endpoints
app = FastAPI()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

@app.post('/login')
def login(user: UserSchema) -> dict:
    username = user.username
    password = user.password
    check = authentication(username, password)
    if check:
        token = create_access_token(data={"sub": username})
        return {"access_token": token, "token_type": "bearer"}
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unauthorized")
    
@app.post('/register')
def register(user: UserSchema) -> dict:
    username = user.username
    password = user.password
    check = register_new_user(username, password)
    if check:
        token = create_access_token(data={"sub": username})
        return {"access_token": token, "token_type": "bearer"}
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Username already exists")
    
@app.get('/items')
async def get_all_items():
    items = all_items()
    if items.data:
        return items.data
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Items not found")
    
@app.get('/items')
async def get_item(items: ItemSchema):
    id = items.id
    item = get_item_by_id(id)
    if item:
        return item.data
    else:
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

@app.post('/items')
def update(items: ItemSchema):
    id: int = items.id
    name: str = items.name 
    description: str = items.description
    condition: str = items.condition
    image_path: object = items.image_path
    
    item_creation_status = upload_item(id, name, description, condition, image_path)
    if item_creation_status:
        return HTTPException(status_code=status.HTTP_201_CREATED, detail="Item created successfully")
    else:
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Item failed to upload")