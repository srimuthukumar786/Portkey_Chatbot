from django.shortcuts import render
from .models import ChatLog
from django.db.models import Count, Sum, Avg
from django.db.models.functions import TruncHour
import time
from .utils import client, get_available_models, get_provider
import json
from django.core.serializers.json import DjangoJSONEncoder

# Optional: simple cost calculation per 1k tokens
def calculate_cost(tokens):
    rate_per_1k = 0.002
    return round((tokens / 1000) * rate_per_1k, 6)


def chat_view(request):
    response_text = None
    status = "success"
    tokens_used = 0
    model_name = None
    provider = None
    error_message = None
    latency_ms = 0

    models = get_available_models()
    selected_model = models[0][0]  # default

    if request.method == "POST":
        user_query = request.POST.get("query", "").strip()
        selected_model = request.POST.get("model", selected_model)
        provider = get_provider(selected_model)

        if user_query:
            try:
                start_time = time.time()

                response = client.chat.completions.create(
                    model=selected_model,
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant."},
                        {"role": "user", "content": user_query},
                    ],
                    max_tokens=2048,
                    provider=provider
                )

                latency_ms = (time.time() - start_time) * 1000

                # Always use the user-selected model and mapped provider
                model_name = selected_model
                provider = get_provider(selected_model)

                # Parse AI response robustly
                response_text = None
                if hasattr(response, "choices") and len(response.choices) > 0:
                    choice = response.choices[0]
                    if hasattr(choice, "message"):
                        if isinstance(choice.message, dict):
                            response_text = choice.message.get("content")
                        elif hasattr(choice.message, "content"):
                            response_text = choice.message.content
                    elif hasattr(choice, "text"):
                        response_text = choice.text
                    elif isinstance(choice, dict):
                        msg = choice.get("message")
                        if isinstance(msg, dict):
                            response_text = msg.get("content")

                if not response_text:
                    response_text = "⚠️ The AI did not return any content."

                # Tokens used
                tokens_used = getattr(response, "usage", {}).get("total_tokens", 0)

            except Exception as e:
                response_text = f"Error: {str(e)}"
                status = "error"
                error_message = str(e)
                tokens_used = 0

            # Save chat log
            ChatLog.objects.create(
                user=request.user if request.user.is_authenticated else None,
                model_name=model_name or selected_model or "unknown",
                provider=provider or get_provider(selected_model) or "unknown",
                user_query=user_query,
                response_text=response_text,
                tokens_used=tokens_used or 0,
                cost=calculate_cost(tokens_used or 0),
                latency=latency_ms or 0,
                status=status,
                error_message=error_message,
            )

    context = {
        "response": response_text,
        "models": models,
        "selected_model": selected_model,
    }
    return render(request, "chat.html", context)


def analytics_view(request):
    # Overview stats
    total_cost = ChatLog.objects.aggregate(total=Sum("cost"))["total"] or 0
    total_tokens = ChatLog.objects.aggregate(total=Sum("tokens_used"))["total"] or 0
    total_requests = ChatLog.objects.count()
    unique_users = ChatLog.objects.values("user_id").distinct().count()
    avg_latency = ChatLog.objects.aggregate(avg=Avg("latency"))["avg"] or 0
    errors = ChatLog.objects.filter(status="error").count()

    # Requests per model
    model_usage = list(
        ChatLog.objects.values("model_name")
        .annotate(requests=Count("id"))
        .order_by("-requests")
    )

    # Requests per provider
    provider_usage = list(
        ChatLog.objects.values("provider")
        .annotate(requests=Count("id"))
        .order_by("-requests")
    )

    # Requests per user
    user_usage = list(
        ChatLog.objects.values("user__username")
        .annotate(requests=Count("id"), cost=Sum("cost"))
        .order_by("-requests")
    )

    # Time-series (hourly)
    time_series = ChatLog.objects.annotate(hour=TruncHour("timestamp")).values(
        "hour"
    ).annotate(
        requests=Count("id"),
        tokens=Sum("tokens_used"),
        cost=Sum("cost"),
        latency=Avg("latency"),
        unique_users=Count("user_id", distinct=True),
    ).order_by("hour")

    context = {
        "total_cost": round(total_cost, 4),
        "total_tokens": total_tokens,
        "total_requests": total_requests,
        "unique_users": unique_users,
        "avg_latency": round(avg_latency, 2),
        "errors": errors,
        # ✅ Pass JSON-safe data
        "time_series_json": json.dumps(list(time_series), cls=DjangoJSONEncoder),
        "model_usage_json": json.dumps(list(model_usage), cls=DjangoJSONEncoder),
        "provider_usage_json": json.dumps(list(provider_usage), cls=DjangoJSONEncoder),
        "user_usage_json": json.dumps(list(user_usage), cls=DjangoJSONEncoder),
    }
    return render(request, "chatlog_analytics.html", context)