from fastapi import FastAPI
from .routes import project
from .routes import user
from fastapi.middleware.cors import CORSMiddleware
from .database import engine
from .models import Base
from .routes import webhook

app = FastAPI(
    title="Green CI/CD Backend",
    version="1.0.0"
)

@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(project.router)
app.include_router(user.router)
app.include_router(webhook.router)