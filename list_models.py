from openai import OpenAI

from app import app

with app.app_context():
    client = OpenAI(api_key=app.config["AI_API_KEY"], base_url=app.config["AI_BASE_URL"])
    for model in client.models.list().data:
        print(model.id)