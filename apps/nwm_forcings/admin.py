from django.contrib import admin
from .models import NWMIngestionLog


@admin.register(NWMIngestionLog)
class NWMIngestionLogAdmin(admin.ModelAdmin):
    list_display = ["ingest_date", "status", "stations_updated", "created_at"]
    list_filter = ["status"]
    ordering = ["-ingest_date"]
    readonly_fields = ["created_at"]
