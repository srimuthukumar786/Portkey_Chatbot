from django.urls import path
from .views import *

urlpatterns = [
    path("", chat_view, name="chat"),
    path("analytics/", analytics_view, name="chat_analytics"),
]
