# yourapp/admin.py
from django.contrib import admin
from django.urls import path
from django.template.response import TemplateResponse
from django.db.models import Count, Sum, Avg, Value
from django.db.models.functions import TruncDay, Coalesce
from django.core.cache import cache
from django.http import HttpResponse
import json
import csv

from .models import ChatLog

class ChatLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "user", "model_name", "provider", "status", "tokens_used")
    list_filter = ("model_name", "provider", "status")
    search_fields = ("user_query", "response_text", "user__username")
    date_hierarchy = "timestamp"
    actions = ["export_as_csv"]

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path("analytics/", self.admin_site.admin_view(self.analytics_view), name="chatlog-analytics"),
        ]
        return custom_urls + urls

    def analytics_view(self, request):
        """
        Renders the analytics page inside Django Admin.
        We cache the heavy aggregation for 5 minutes using Django cache.
        """
        cache_key = "chatlog_analytics_v1"
        context = cache.get(cache_key)
        if not context:
            qs = ChatLog.objects.all()

            # Basic counters
            total_requests = qs.count()
            success_count = qs.filter(status="success").count()
            error_count = qs.filter(status="error").count()

            # Tokens summaries (use Coalesce to avoid None)
            total_tokens = qs.aggregate(total=Coalesce(Sum("tokens_used"), Value(0)))["total"]
            avg_tokens = qs.aggregate(avg=Coalesce(Avg("tokens_used"), Value(0)))["avg"]

            # Requests per model
            per_model = list(qs.values("model_name").annotate(count=Count("id")).order_by("-count"))
            models_labels = [r["model_name"] or "unknown" for r in per_model]
            models_counts = [r["count"] for r in per_model]

            # Errors / counts by provider
            per_provider = list(qs.values("provider").annotate(count=Count("id")).order_by("-count"))
            providers_labels = [r["provider"] or "unknown" for r in per_provider]
            providers_counts = [r["count"] for r in per_provider]

            # Requests per day (last N days automatically via the data, adjust by filtering if needed)
            daily_qs = (
                qs.annotate(day=TruncDay("timestamp"))
                  .values("day")
                  .annotate(count=Count("id"))
                  .order_by("day")
            )
            daily_labels = [d["day"].strftime("%Y-%m-%d") for d in daily_qs]
            daily_counts = [d["count"] for d in daily_qs]

            # Top users (if available)
            top_users = list(
                qs.values("user__username")
                  .annotate(count=Count("id"))
                  .order_by("-count")[:10]
            )
            top_users = [{"user": r["user__username"] or "anonymous", "count": r["count"]} for r in top_users]

            context = {
                "title": "ChatLog Analytics",
                "total_requests": total_requests,
                "success_count": success_count,
                "error_count": error_count,
                "total_tokens": total_tokens,
                "avg_tokens": round(avg_tokens or 0, 2),
                # JSON-ready data for charts
                "models_labels": json.dumps(models_labels),
                "models_counts": json.dumps(models_counts),
                "providers_labels": json.dumps(providers_labels),
                "providers_counts": json.dumps(providers_counts),
                "daily_labels": json.dumps(daily_labels),
                "daily_counts": json.dumps(daily_counts),
                "top_users": top_users,
                # meta for template
                "opts": self.model._meta,
            }
            # cache for 300 seconds
            cache.set(cache_key, context, 300)

        return TemplateResponse(request, "admin/chatlog_analytics.html", context)

    def export_as_csv(self, request, queryset):
        """
        Export selected ChatLog queryset as CSV.
        """
        fieldnames = ["timestamp", "user", "model_name", "provider", "status", "tokens_used", "user_query", "response_text", "error_message"]
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = "attachment; filename=chatlogs.csv"
        writer = csv.writer(response)
        writer.writerow(fieldnames)
        for obj in queryset:
            writer.writerow([
                obj.timestamp.isoformat(),
                obj.user.username if obj.user else "",
                obj.model_name,
                obj.provider,
                obj.status,
                obj.tokens_used if obj.tokens_used is not None else "",
                obj.user_query,
                obj.response_text,
                obj.error_message,
            ])
        return response
    export_as_csv.short_description = "Export selected logs as CSV"


admin.site.register(ChatLog, ChatLogAdmin)
