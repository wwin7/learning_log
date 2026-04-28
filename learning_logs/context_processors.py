import json
from collections import Counter
from datetime import timedelta

from django.utils import timezone

from .models import Entry


def sidebar_learning_stats(request):
    if not request.user.is_authenticated:
        return {
            "sidebar_weekly_target": 10,
            "sidebar_weekly_count": 0,
            "sidebar_weekly_progress": 0,
            "sidebar_heatmap_json": "[]",
            "sidebar_heatmap_max": 1,
        }

    today = timezone.localdate()
    week_start = today - timedelta(days=today.weekday())
    weekly_target = 10

    entries = Entry.objects.filter(topic__owner=request.user, is_deleted=False)
    weekly_count = entries.filter(date_added__date__gte=week_start).count()
    weekly_progress = min(round((weekly_count / weekly_target) * 100, 1), 100)

    heatmap_counter = Counter()
    recent_entries = entries.filter(date_added__date__gte=today - timedelta(days=29))
    for dt in recent_entries.values_list("date_added", flat=True):
        local_dt = timezone.localtime(dt)
        heatmap_counter[(local_dt.hour, local_dt.weekday())] += 1

    heatmap_data = [[hour, weekday, count] for (hour, weekday), count in heatmap_counter.items()]
    heatmap_max = max(heatmap_counter.values()) if heatmap_counter else 1

    return {
        "sidebar_weekly_target": weekly_target,
        "sidebar_weekly_count": weekly_count,
        "sidebar_weekly_progress": weekly_progress,
        "sidebar_heatmap_json": json.dumps(heatmap_data, ensure_ascii=False),
        "sidebar_heatmap_max": heatmap_max,
    }
