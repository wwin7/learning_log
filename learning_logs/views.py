import json
import re
from collections import Counter
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Max, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from accounts.models import UserProfile
from .forms import DailyCheckInForm, EntryForm, TopicForm
from .models import DailyCheckIn, Entry, Topic


def index(request):
  """首页：已登录进入仪表盘，未登录展示介绍页。"""
  if request.user.is_authenticated:
    return redirect("learning_logs:dashboard")
  return render(request, "learning_logs/index.html")


@login_required
def pomodoro(request):
  """番茄工作法页面。"""
  return render(request, "learning_logs/pomodoro.html")


def _get_owned_topic(user, topic_id):
  topic = get_object_or_404(Topic, id=topic_id)
  if topic.owner != user:
    raise Http404
  return topic


def _get_recent_day_labels(days=7):
  today = timezone.localdate()
  return [today - timedelta(days=offset) for offset in range(days - 1, -1, -1)]


def _active_entries(user):
  return Entry.objects.filter(topic__owner=user, is_deleted=False)


def _get_user_profile(user):
  profile, _ = UserProfile.objects.get_or_create(user=user)
  return profile


def _highlight_text(text, keyword):
  escaped_text = escape(text)
  if not keyword:
    return mark_safe(escaped_text)
  pattern = re.compile(re.escape(keyword), re.IGNORECASE)
  highlighted = pattern.sub(lambda m: f"<mark>{m.group(0)}</mark>", escaped_text)
  return mark_safe(highlighted)


@login_required
def dashboard(request):
  today = timezone.localdate()
  last_7_days = today - timedelta(days=6)
  last_30_days = today - timedelta(days=29)
  week_start = today - timedelta(days=today.weekday())
  profile = _get_user_profile(request.user)
  weekly_target = max(profile.weekly_target, 1)
  active_entries = _active_entries(request.user)
  weekly_entry_count = active_entries.filter(date_added__date__gte=week_start).count()
  weekly_progress = min(round((weekly_entry_count / weekly_target) * 100, 1), 100)

  recent_checkins = DailyCheckIn.objects.filter(owner=request.user, checkin_date__gte=last_7_days)
  checkin_days_30 = DailyCheckIn.objects.filter(owner=request.user, checkin_date__gte=last_30_days).count()
  checkin_rate = round((checkin_days_30 / 30) * 100, 1)
  streak = DailyCheckIn.current_streak(request.user)
  today_checked = DailyCheckIn.objects.filter(owner=request.user, checkin_date=today).exists()
  checkin_status_text = "已打卡，明天继续加油" if today_checked else "今日待打卡"
  badge_message = DailyCheckIn.badge_name(streak)

  context = {
    "today_checked": today_checked,
    "recent_checkins": recent_checkins.order_by("-checkin_date")[:7],
    "checkin_days_30": checkin_days_30,
    "checkin_rate": checkin_rate,
    "streak": streak,
    "badge": badge_message,
    "checkin_status_text": checkin_status_text,
    "topic_count": Topic.objects.filter(owner=request.user).count(),
    "entry_count": active_entries.count(),
    "weekly_target": weekly_target,
    "weekly_entry_count": weekly_entry_count,
    "weekly_progress": weekly_progress,
  }
  return render(request, "learning_logs/dashboard.html", context)


@login_required
def checkin(request):
  today = timezone.localdate()
  if request.method == "POST":
    form = DailyCheckInForm(request.POST)
    if form.is_valid():
      checkin_obj, created = DailyCheckIn.objects.get_or_create(
        owner=request.user,
        checkin_date=today,
        defaults={"note": form.cleaned_data.get("note", "")},
      )
      if created:
        messages.success(request, "打卡成功，继续保持！")
      else:
        messages.warning(request, "今天已经打过卡了，每天只能打卡一次。")
    else:
      messages.error(request, "打卡失败，请检查输入内容。")
    return redirect("learning_logs:checkin")

  checkins = DailyCheckIn.objects.filter(owner=request.user).order_by("-checkin_date")[:20]
  streak = DailyCheckIn.current_streak(request.user)
  today_checked = DailyCheckIn.objects.filter(owner=request.user, checkin_date=today).exists()
  checkin_status_text = "已打卡，明天继续加油" if today_checked else "今日待打卡"
  context = {
    "form": DailyCheckInForm(),
    "today_checked": today_checked,
    "checkins": checkins,
    "streak": streak,
    "badge": DailyCheckIn.badge_name(streak),
    "checkin_status_text": checkin_status_text,
  }
  return render(request, "learning_logs/checkin.html", context)


@login_required
def topics(request):
  topic_qs = (
    Topic.objects.filter(owner=request.user)
    .annotate(entry_total=Count("entries", filter=Q(entries__is_deleted=False)))
    .order_by("sort_order", "-updated_at")
  )
  context = {"topics": topic_qs}
  return render(request, "learning_logs/topics.html", context)


@login_required
def topic(request, topic_id):
  current_topic = _get_owned_topic(request.user, topic_id)
  keyword = request.GET.get("q", "").strip()
  entries_qs = current_topic.entries.filter(is_deleted=False).order_by("-is_pinned", "-pinned_at", "-date_added")
  if keyword:
    entries_qs = entries_qs.filter(text__icontains=keyword)

  entries = list(entries_qs)
  for entry in entries:
    entry.highlighted_text = _highlight_text(entry.text, keyword)

  context = {
    "topic": current_topic,
    "entries": entries,
    "keyword": keyword,
  }
  return render(request, "learning_logs/topic.html", context)


@login_required
def new_topic(request):
  if request.method != "POST":
    form = TopicForm()
  else:
    form = TopicForm(data=request.POST)
    if form.is_valid():
      topic_obj = form.save(commit=False)
      topic_obj.owner = request.user
      max_order = Topic.objects.filter(owner=request.user).aggregate(max_sort=Max("sort_order")).get("max_sort")
      topic_obj.sort_order = (max_order or 0) + 1
      topic_obj.save()
      messages.success(request, "分类创建成功。")
      return redirect("learning_logs:topics")

  context = {"form": form, "page_title": "新建分类", "form_action": "learning_logs:new_topic"}
  return render(request, "learning_logs/new_topic.html", context)


@login_required
def edit_topic(request, topic_id):
  topic_obj = _get_owned_topic(request.user, topic_id)
  if request.method != "POST":
    form = TopicForm(instance=topic_obj)
  else:
    form = TopicForm(instance=topic_obj, data=request.POST)
    if form.is_valid():
      form.save()
      messages.success(request, "分类已更新。")
      return redirect("learning_logs:topic", topic_id=topic_obj.id)

  context = {
    "form": form,
    "topic": topic_obj,
    "page_title": "编辑分类",
    "form_action": "learning_logs:edit_topic",
  }
  return render(request, "learning_logs/new_topic.html", context)


@login_required
def delete_topic(request, topic_id):
  topic_obj = _get_owned_topic(request.user, topic_id)
  if request.method == "POST":
    topic_obj.delete()
    messages.success(request, "分类及其笔记已删除。")
    return redirect("learning_logs:topics")
  return redirect("learning_logs:topic", topic_id=topic_id)


@login_required
def new_entry(request, topic_id):
  topic_obj = _get_owned_topic(request.user, topic_id)

  if request.method != "POST":
    form = EntryForm()
  else:
    form = EntryForm(data=request.POST)
    if form.is_valid():
      entry_obj = form.save(commit=False)
      entry_obj.topic = topic_obj
      entry_obj.save()
      messages.success(request, "笔记创建成功。")
      return redirect("learning_logs:topic", topic_id=topic_id)

  context = {
    "topic": topic_obj,
    "form": form,
    "page_title": "新建笔记",
    "form_action": "learning_logs:new_entry",
    "editor_mode": "create",
    "draft_key": f"entry-draft-new-{topic_obj.id}",
  }
  return render(request, "learning_logs/new_entry.html", context)


@login_required
def edit_entry(request, entry_id):
  entry_obj = get_object_or_404(Entry, id=entry_id)
  topic_obj = entry_obj.topic
  if topic_obj.owner != request.user:
    raise Http404
  if entry_obj.is_deleted:
    messages.warning(request, "该笔记在回收站中，恢复后可编辑。")
    return redirect("learning_logs:recycle_bin")

  if request.method != "POST":
    form = EntryForm(instance=entry_obj)
  else:
    form = EntryForm(instance=entry_obj, data=request.POST)
    if form.is_valid():
      form.save()
      messages.success(request, "笔记已更新。")
      return redirect("learning_logs:topic", topic_id=topic_obj.id)

  context = {
    "entry": entry_obj,
    "topic": topic_obj,
    "form": form,
    "page_title": "编辑笔记",
    "form_action": "learning_logs:edit_entry",
    "editor_mode": "edit",
    "draft_key": f"entry-draft-edit-{entry_obj.id}",
  }
  return render(request, "learning_logs/edit_entry.html", context)


@login_required
def delete_entry(request, entry_id):
  entry_obj = get_object_or_404(Entry, id=entry_id)
  topic_obj = entry_obj.topic
  if topic_obj.owner != request.user:
    raise Http404

  if request.method == "POST":
    entry_obj.soft_delete()
    messages.success(request, "笔记已移入回收站，可在 7 天内恢复。")
  return redirect("learning_logs:topic", topic_id=topic_obj.id)


@login_required
def toggle_pin_entry(request, entry_id):
  entry_obj = get_object_or_404(Entry, id=entry_id)
  if entry_obj.topic.owner != request.user:
    raise Http404
  if entry_obj.is_deleted:
    messages.warning(request, "回收站中的笔记不能置顶。")
    return redirect("learning_logs:recycle_bin")

  if request.method == "POST":
    entry_obj.toggle_pin()
    messages.success(request, "已置顶笔记。" if entry_obj.is_pinned else "已取消置顶。")
  return redirect("learning_logs:topic", topic_id=entry_obj.topic.id)


@login_required
def recycle_bin(request):
  deadline = timezone.now() - timedelta(days=7)
  deleted_entries = (
    Entry.objects.filter(topic__owner=request.user, is_deleted=True, deleted_at__gte=deadline)
    .select_related("topic")
    .order_by("-deleted_at")
  )
  context = {
    "entries": deleted_entries,
    "deadline_days": 7,
  }
  return render(request, "learning_logs/recycle_bin.html", context)


@login_required
def restore_entry(request, entry_id):
  entry_obj = get_object_or_404(Entry, id=entry_id)
  if entry_obj.topic.owner != request.user:
    raise Http404

  if request.method == "POST":
    if not entry_obj.is_deleted:
      messages.info(request, "该笔记已是正常状态。")
    elif entry_obj.deleted_at and entry_obj.deleted_at < timezone.now() - timedelta(days=7):
      messages.error(request, "该笔记已超过可恢复期限。")
    else:
      entry_obj.restore()
      messages.success(request, "笔记恢复成功。")
  return redirect("learning_logs:recycle_bin")


@login_required
def global_search(request):
  keyword = request.GET.get("q", "").strip()
  topic_results = []
  entry_results = []

  if keyword:
    topic_results = list(
      Topic.objects.filter(owner=request.user, text__icontains=keyword)
      .annotate(entry_total=Count("entries", filter=Q(entries__is_deleted=False)))
      .order_by("sort_order", "-updated_at")
    )

    entries = (
      _active_entries(request.user)
      .filter(Q(text__icontains=keyword) | Q(tags__icontains=keyword) | Q(topic__text__icontains=keyword))
      .select_related("topic")
      .order_by("-is_pinned", "-pinned_at", "-date_added")[:50]
    )
    entry_results = list(entries)
    for entry in entry_results:
      entry.highlighted_text = _highlight_text(entry.text, keyword)

  context = {
    "keyword": keyword,
    "topic_results": topic_results,
    "entry_results": entry_results,
  }
  return render(request, "learning_logs/global_search.html", context)


@login_required
def api_checkin_stats(request):
  day_labels = _get_recent_day_labels(7)
  checkin_map = {
    item.checkin_date: 1
    for item in DailyCheckIn.objects.filter(owner=request.user, checkin_date__in=day_labels)
  }
  checkin_series = [checkin_map.get(day, 0) for day in day_labels]

  today = timezone.localdate()
  last_30_days = today - timedelta(days=29)
  checkin_days_30 = DailyCheckIn.objects.filter(owner=request.user, checkin_date__gte=last_30_days).count()
  checkin_rate = round((checkin_days_30 / 30) * 100, 1)
  streak = DailyCheckIn.current_streak(request.user)
  today_checked = DailyCheckIn.objects.filter(owner=request.user, checkin_date=today).exists()

  return JsonResponse(
    {
      "labels": [day.strftime("%m-%d") for day in day_labels],
      "series": checkin_series,
      "days30": checkin_days_30,
      "rate": checkin_rate,
      "streak": streak,
      "badge": DailyCheckIn.badge_name(streak),
      "status_text": "已打卡，明天继续加油" if today_checked else "今日待打卡",
    }
  )


def _extract_tag_counts(tag_texts):
  counter = Counter()
  for raw_text in tag_texts:
    if not raw_text:
      continue
    tags = [item.strip() for item in raw_text.split(",") if item.strip()]
    counter.update(tags)
  return counter


@login_required
def api_note_stats(request):
  user_topics = Topic.objects.filter(owner=request.user)
  user_entries = _active_entries(request.user)

  topic_distribution = (
    user_topics.annotate(entry_total=Count("entries", filter=Q(entries__is_deleted=False)))
    .values("text", "entry_total")
    .order_by("-entry_total")
  )

  day_labels = _get_recent_day_labels(7)
  trend_raw = (
    user_entries.filter(date_added__date__in=day_labels)
    .values("date_added__date")
    .annotate(total=Count("id"))
  )
  trend_map = {item["date_added__date"]: item["total"] for item in trend_raw}
  trend_series = [trend_map.get(day, 0) for day in day_labels]

  topic_tag_counter = _extract_tag_counts(user_topics.values_list("tags", flat=True))
  entry_tag_counter = _extract_tag_counts(user_entries.values_list("tags", flat=True))
  topic_tag_counter.update(entry_tag_counter)

  top_tags = topic_tag_counter.most_common(8)

  heatmap_counter = Counter()
  recent_entries = user_entries.filter(date_added__date__gte=timezone.localdate() - timedelta(days=29))
  for dt in recent_entries.values_list("date_added", flat=True):
    local_dt = timezone.localtime(dt)
    heatmap_counter[(local_dt.hour, local_dt.weekday())] += 1

  heatmap_data = [[hour, weekday, count] for (hour, weekday), count in heatmap_counter.items()]
  heatmap_max = max(heatmap_counter.values()) if heatmap_counter else 1

  return JsonResponse(
    {
      "topic_labels": [item["text"] for item in topic_distribution],
      "topic_values": [item["entry_total"] for item in topic_distribution],
      "trend_labels": [day.strftime("%m-%d") for day in day_labels],
      "trend_values": trend_series,
      "tag_labels": [item[0] for item in top_tags],
      "tag_values": [item[1] for item in top_tags],
      "heatmap_hours": [f"{h:02d}:00" for h in range(24)],
      "heatmap_weekdays": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"],
      "heatmap_data": heatmap_data,
      "heatmap_max": heatmap_max,
    }
  )


@login_required
@require_POST
def api_reorder_topics(request):
  try:
    payload = json.loads(request.body.decode("utf-8"))
    ordered_ids = payload.get("ordered_ids", [])
  except (json.JSONDecodeError, UnicodeDecodeError):
    return JsonResponse({"ok": False, "message": "无效请求数据"}, status=400)

  if not isinstance(ordered_ids, list):
    return JsonResponse({"ok": False, "message": "ordered_ids 必须是列表"}, status=400)

  own_topics = list(Topic.objects.filter(owner=request.user, id__in=ordered_ids).values_list("id", flat=True))
  if len(own_topics) != len(ordered_ids):
    return JsonResponse({"ok": False, "message": "包含无权限分类"}, status=403)

  for idx, topic_id in enumerate(ordered_ids, start=1):
    Topic.objects.filter(owner=request.user, id=topic_id).update(sort_order=idx)

  return JsonResponse({"ok": True})


@login_required
@require_POST
def api_upload_image(request):
  """Upload an image file and return its URL.

  Expects a multipart POST with file field named 'image'. Returns JSON {ok: True, url: ...}.
  """
  upload = request.FILES.get('image')
  if not upload:
    return JsonResponse({"ok": False, "message": "没有上传的文件"}, status=400)

  if not upload.content_type.startswith('image/'):
    return JsonResponse({"ok": False, "message": "只支持图片文件"}, status=400)

  # Limit size to ~8MB
  max_size = 8 * 1024 * 1024
  if upload.size > max_size:
    return JsonResponse({"ok": False, "message": "图片体积过大（最大 8MB）"}, status=400)

  try:
    filename = f"uploads/user_{request.user.id}/{int(timezone.now().timestamp())}_{upload.name}"
    saved_path = default_storage.save(filename, ContentFile(upload.read()))
    url = default_storage.url(saved_path)
    return JsonResponse({"ok": True, "url": url})
  except Exception as exc:
    return JsonResponse({"ok": False, "message": str(exc)}, status=500)