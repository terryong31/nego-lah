from fastapi import FastAPI, Depends, HTTPException, status, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from login.user_crud import authentication, register_new_user
from items.item_crud import all_items, get_item_by_name, upload_item, delete_item, update_item
from schemas import UserSchema, ItemSchema
from login.user_crud import create_access_token
from typing import List, Annotated

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
async def get_all_items(items: ItemSchema, keyword: dict = None) -> dict:
    if keyword is None:
        items = all_items()
        if len(items) > 0:
            return items
        else:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Items not found")
    elif keyword is not None:
        keyword = items.name
        item = get_item_by_name(keyword)
        if item:
            return item.data
        else:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

@app.post('/items', status_code=status.HTTP_201_CREATED)
async def upload(
    name: Annotated[str, Form()],
    description: Annotated[str, Form()],
    condition: Annotated[str, Form()],
    images: Annotated[List[UploadFile], File()]
):
    
    item_creation_status = await upload_item(name, description, condition, images)
        
    if item_creation_status:
        return {"message": "Item created successfully"}
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Item failed to upload")
    
@app.delete('/items')
def delete_by_id(items: ItemSchema):
    item_id = items.item_id
    
    item_delete_status = delete_item(item_id)
    if item_delete_status:
        raise HTTPException(status_code=status.HTTP_200_OK, detail="Item deleted successfully")
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Item failed to delete")
    
@app.put('/items', status_code=status.HTTP_200_OK)
def update(items: ItemSchema):
    item_id: str = items.item_id
    name: str = items.name 
    description: str = items.description
    condition: str = items.condition
    images = items.images
    
    item_update_status = update_item(item_id, name, description, condition, images)
    if item_update_status:
        return {"message": "Item updated successfully"}
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Item failed to delete")