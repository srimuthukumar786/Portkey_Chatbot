# utils.py
from django.conf import settings
from portkey_ai import Portkey

client = Portkey(api_key=settings.PORTKEY_API_KEY)

# Map models to providers
MODEL_PROVIDERS = {
    "@first-integrati-600395/gemini-2.5-pro": "google",
    "gpt-4": "openai",
    "gpt-3.5-turbo": "openai",
    "claude-3-opus-20240229": "anthropic",
}

def get_available_models():
    """
    Fetch available models from Portkey. Fallback to static list.
    Returns: list of tuples (model_id, model_name)
    """
    try:
        models_response = client.models.list()
        return [(m.id, m.name) for m in models_response.data]
    except Exception:
        # fallback static list
        return [(k, k) for k in MODEL_PROVIDERS.keys()]

def get_provider(model_id):
    return MODEL_PROVIDERS.get(model_id, "openai")
