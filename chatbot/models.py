from django.db import models
from django.contrib.auth.models import User

class ChatLog(models.Model):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    model_name = models.CharField(max_length=255)
    provider = models.CharField(max_length=255, default="openai")
    user_query = models.TextField()
    response_text = models.TextField()
    tokens_used = models.IntegerField(default=0)
    cost = models.FloatField(default=0.0)
    latency = models.FloatField(default=0.0)
    status = models.CharField(max_length=20, default="success")
    error_message = models.TextField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)


    def __str__(self):
        return f"{self.user.username} - {self.model_name}"
