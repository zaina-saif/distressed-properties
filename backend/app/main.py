from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.properties import router as properties_router
from app.api.liens import router as liens_router


app = FastAPI(
    title="NJ Sheriff Sale API",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(properties_router)
app.include_router(liens_router)


@app.get("/health")
def health_check():
    return {"status": "healthy"}

@app.get("/")
async def root():
    return {
        "message": "NJ Sheriff Sale API is running"
    }
