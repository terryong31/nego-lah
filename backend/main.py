from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Import routers
from routes.auth import router as auth_router
from routes.items import router as items_router
from routes.chat import router as chat_router
from routes.payment import router as payment_router
from routes.admin import router as admin_router

app = FastAPI(
    title="Second-Hand Store API",
    description="Fully autonomous second-hand store with AI negotiation",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth_router)
app.include_router(items_router)
app.include_router(chat_router)
app.include_router(payment_router)
app.include_router(admin_router)


@app.get("/")
def root():
    return {"message": "Second-Hand Store API", "status": "running"}


@app.get("/health")
def health_check():
    return {"status": "healthy"}