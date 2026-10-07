from app import app
from services import ai_service
from services import decision_tree_service as tree

categories = {k: v for k, v in tree.CATEGORY_LABELS.items() if k != "unknown"}
with app.app_context():
    print("key set:", bool(app.config["AI_API_KEY"]), "| model:", app.config["AI_MODEL"], "| base:", app.config["AI_BASE_URL"])
    result = ai_service.analyze_problem("what happen on my usb port not working", categories, tree.detect_category)
    print("RESULT:", result["source"], "|", result["category"], "|", result["summary"])