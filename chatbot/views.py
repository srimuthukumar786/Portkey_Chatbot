from django.shortcuts import render
from .models import ChatLog
from django.db.models import Count, Sum, Avg, Q
from django.db.models.functions import TruncHour
import time
from .utils import client, get_available_models, get_provider
import json
from django.core.serializers.json import DjangoJSONEncoder
from datetime import datetime, timedelta

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
    # --- Filter handling ---
    user_filter = request.GET.get("user")  # username
    start_date = request.GET.get("start_date")
    end_date = request.GET.get("end_date")

    queryset = ChatLog.objects.all()

    if user_filter:
        queryset = queryset.filter(user__username=user_filter)
    if start_date:
        start_date = datetime.strptime(start_date, "%Y-%m-%d")
        queryset = queryset.filter(timestamp__gte=start_date)

    if end_date:
        end_date = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1) - timedelta(seconds=1)
        queryset = queryset.filter(timestamp__lte=end_date)

    # --- Overview metrics ---
    total_cost = queryset.aggregate(total=Sum("cost"))["total"] or 0
    total_tokens = queryset.aggregate(total=Sum("tokens_used"))["total"] or 0
    total_requests = queryset.count()
    unique_users = queryset.values("user_id").distinct().count()
    avg_latency = queryset.aggregate(avg=Avg("latency"))["avg"] or 0
    errors = queryset.filter(~Q(error_message__isnull=True)).count()

    # --- Requests per user ---
    user_usage = list(
        queryset.values("user__username")
        .annotate(requests=Count("id"), cost=Sum("cost"))
        .order_by("-requests")
    )

    # --- Requests per model ---
    model_usage = list(
        queryset.values("model_name")
        .annotate(requests=Count("id"))
        .order_by("-requests")
    )

    # --- Requests per provider ---
    provider_usage = list(
        queryset.values("provider")
        .annotate(requests=Count("id"))
        .order_by("-requests")
    )

    # --- Errors per provider ---
    error_usage = list(
        queryset.filter(~Q(error_message__isnull=True))
        .values("provider")
        .annotate(errors=Count("id"))
        .order_by("-errors")
    )

    # --- Error types distribution ---
    error_types = list(
        queryset.filter(~Q(error_message__isnull=True))
        .values("error_message")
        .annotate(count=Count("id"))
        .order_by("-count")
    )

    # --- Feedback trend ---
    feedback_trend = (
        queryset.annotate(hour=TruncHour("timestamp"))
        .values("hour")
        .annotate(avg_feedback=Avg("latency"))  # ⚠ replace with feedback field if exists
        .order_by("hour")
    )

    # --- Time-series (hourly stats) ---
    time_series = (
        queryset.annotate(hour=TruncHour("timestamp"))
        .values("hour")
        .annotate(
            requests=Count("id"),
            errors=Count("id", filter=~Q(error_message__isnull=True)),
            tokens=Sum("tokens_used"),
            cost=Sum("cost"),
            latency=Avg("latency"),
            unique_users=Count("user_id", distinct=True),
        )
        .order_by("hour")
    )

    # --- All usernames for filter dropdown ---
    all_users = ChatLog.objects.values_list("user__username", flat=True).distinct().order_by("user__username")

    context = {
        # Filters
        "all_users": all_users,
        "selected_user": user_filter,
        "start_date": start_date,
        "end_date": end_date,

        # Summary
        "total_cost": round(total_cost, 4),
        "total_tokens": total_tokens,
        "total_requests": total_requests,
        "unique_users": unique_users,
        "avg_latency": round(avg_latency, 2),
        "errors": errors,

        # JSON dumps for charts
        "time_series_json": json.dumps(list(time_series), cls=DjangoJSONEncoder),
        "user_usage_json": json.dumps(list(user_usage), cls=DjangoJSONEncoder),
        "model_usage_json": json.dumps(list(model_usage), cls=DjangoJSONEncoder),
        "provider_usage_json": json.dumps(list(provider_usage), cls=DjangoJSONEncoder),
        "error_usage_json": json.dumps(list(error_usage), cls=DjangoJSONEncoder),
        "error_types_json": json.dumps(list(error_types), cls=DjangoJSONEncoder),
        "feedback_json": json.dumps(list(feedback_trend), cls=DjangoJSONEncoder),
    }
    return render(request, "chatlog_analytics.html", context)
