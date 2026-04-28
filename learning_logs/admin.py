from django.contrib import admin

from .models import DailyCheckIn, Entry, Topic


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
	list_display = ("text", "owner", "sort_order", "category_color", "updated_at")
	search_fields = ("text", "tags", "owner__username")


@admin.register(Entry)
class EntryAdmin(admin.ModelAdmin):
	list_display = ("topic", "is_pinned", "is_deleted", "date_added", "updated_at")
	search_fields = ("topic__text", "text", "tags")


@admin.register(DailyCheckIn)
class DailyCheckInAdmin(admin.ModelAdmin):
	list_display = ("owner", "checkin_date", "created_at")
	search_fields = ("owner__username", "note")
