import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", "mysql+pymysql://root:@localhost/fixwise_ai"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5 MB upload limit (for screenshots later)

    # AI (any OpenAI-compatible provider). Leave AI_API_KEY empty to use keyword matching only.
    AI_API_KEY = os.getenv("AI_API_KEY") or os.getenv("OPENAI_API_KEY", "")
    AI_BASE_URL = os.getenv("AI_BASE_URL", "")
    AI_MODEL = os.getenv("AI_MODEL", "")
    # Reading screenshots needs a model that accepts images. Leave empty to reuse AI_MODEL.
    AI_VISION_MODEL = os.getenv("AI_VISION_MODEL", "")