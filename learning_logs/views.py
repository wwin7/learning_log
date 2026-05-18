import json
import os
import re
from collections import Counter
from datetime import timedelta
from uuid import uuid4

from django.conf import settings
from django.http import HttpResponse
from django.utils.text import slugify

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.storage import default_storage
from django.db.models import Count, Max, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.utils import timezone
from django.views.decorators.http import require_POST

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


def _sanitize_export_html(raw_html):
  """清理富文本中的潜在危险内容，供导出渲染使用。"""
  html = raw_html or ""
  html = html.replace("\u21b5", "")  # remove visible soft-return symbol in some exports
  html = re.sub(r"<script[\s\S]*?>[\s\S]*?</script>", "", html, flags=re.IGNORECASE)
  html = re.sub(r"<style[\s\S]*?>[\s\S]*?</style>", "", html, flags=re.IGNORECASE)
  html = re.sub(r"\son\w+\s*=\s*(['\"]).*?\1", "", html, flags=re.IGNORECASE)
  html = re.sub(r"\son\w+\s*=\s*[^\s>]+", "", html, flags=re.IGNORECASE)
  html = re.sub(r'(href|src)\s*=\s*([\'"])\s*javascript:[\s\S]*?\2', r'\1=\2#\2', html, flags=re.IGNORECASE)
  return html


def _build_export_html(title, date_str, body_html):
  return (
    "<!doctype html><html><head>"
    "<meta charset='utf-8'>"
    "<meta http-equiv='Content-Type' content='text/html; charset=utf-8' />"
    "<style>"
    "body{font-family:'Microsoft YaHei','PingFang SC','Noto Sans CJK SC','SimSun',sans-serif;padding:24px;line-height:1.75;color:#111;font-size:14px;word-break:break-word;}"
    "h1{font-size:28px;margin:0 0 10px 0;font-weight:700;}"
    ".meta{font-size:12px;color:#666;margin:0 0 18px 0;}"
    ".content p{margin:10px 0;}"
    ".content img{max-width:100%;height:auto;display:block;margin:8px 0;}"
    ".content blockquote{border-left:4px solid #d0d7de;padding-left:10px;color:#555;margin:12px 0;}"
    ".content pre,.content code{font-family:Consolas,'Courier New',monospace;}"
    ".content pre{background:#f6f8fa;padding:10px;border-radius:6px;overflow:auto;}"
    ".content table{border-collapse:collapse;max-width:100%;margin:10px 0;}"
    ".content th,.content td{border:1px solid #d0d7de;padding:6px 8px;vertical-align:top;}"
    ".content video{max-width:100%;height:auto;display:block;margin:8px 0;}"
    ".content a{color:#0969da;text-decoration:underline;}"
    "</style></head><body>"
    f"<h1>{escape(title)}</h1>"
    f"<p class='meta'>最后编辑：{escape(date_str)}</p>"
    f"<div class='content'>{body_html}</div>"
    "</body></html>"
  )


def _rewrite_media_urls_for_export(body_html, request):
  """将 /media/... 资源改为绝对 URL，避免导出渲染丢图。"""
  media_url = (settings.MEDIA_URL or "/media/").rstrip("/")
  origin = request.build_absolute_uri("/").rstrip("/")

  pattern = re.compile(
    r'(?P<attr>src|poster)\s*=\s*(?P<q>[\'"])(?P<url>[^\'"]+)(?P=q)',
    flags=re.IGNORECASE,
  )

  def repl(match):
    attr = match.group("attr")
    q = match.group("q")
    raw_url = match.group("url").strip()

    if raw_url.startswith(("http://", "https://", "data:", "blob:", "file://")):
      return match.group(0)

    candidate = raw_url
    if raw_url.startswith(origin + "/"):
      candidate = raw_url[len(origin):]

    if not candidate.startswith(media_url + "/"):
      return match.group(0)

    absolute_url = request.build_absolute_uri(candidate)
    return f'{attr}={q}{absolute_url}{q}'

  return pattern.sub(repl, body_html)


def _export_dependency_error(message):
  return HttpResponse(
    "富文本导出失败：当前环境缺少渲染能力或依赖未安装完整。\n"
    f"详情：{message}\n"
    "请安装 playwright 并执行 `python -m playwright install chromium`，然后重启服务。",
    status=500,
    content_type="text/plain; charset=utf-8",
  )


def _render_html_pdf(html):
  from playwright.sync_api import sync_playwright

  with sync_playwright() as playwright:
    browser = playwright.chromium.launch()
    page = browser.new_page(viewport={"width": 1400, "height": 2200, "device_scale_factor": 2})
    page.set_content(html, wait_until="networkidle")
    page.emulate_media(media="screen")
    pdf_bytes = page.pdf(
      format="A4",
      print_background=True,
      prefer_css_page_size=True,
      margin={"top": "14mm", "right": "14mm", "bottom": "14mm", "left": "14mm"},
    )
    browser.close()
    return pdf_bytes


def _render_html_image(html, fmt):
  from playwright.sync_api import sync_playwright

  image_type = "jpeg" if fmt in ("jpg", "jpeg") else "png"
  ext = "jpg" if image_type == "jpeg" else "png"
  content_type = "image/jpeg" if image_type == "jpeg" else "image/png"

  with sync_playwright() as playwright:
    browser = playwright.chromium.launch()
    page = browser.new_page(viewport={"width": 1400, "height": 2200, "device_scale_factor": 2})
    page.set_content(html, wait_until="networkidle")
    screenshot_args = {"full_page": True, "type": image_type}
    if image_type == "jpeg":
      screenshot_args["quality"] = 92
    image_bytes = page.screenshot(**screenshot_args)
    browser.close()
    return image_bytes, content_type, ext


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
      Topic.objects.filter(owner=request.user).filter(Q(text__icontains=keyword) | Q(tags__icontains=keyword))
      .annotate(entry_total=Count("entries", filter=Q(entries__is_deleted=False)))
      .order_by("sort_order", "-updated_at")
    )

    entries = (
      _active_entries(request.user)
      .filter(
        Q(text__icontains=keyword)
        | Q(tags__icontains=keyword)
        | Q(topic__text__icontains=keyword)
        | Q(topic__tags__icontains=keyword)
      )
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
def export_entry(request, entry_id, fmt):
  """导出单条笔记为 doc/pdf/jpg/png，富文本优先。"""
  entry = get_object_or_404(Entry, id=entry_id)
  if entry.topic.owner != request.user:
    raise Http404

  title = entry.topic.text or "笔记"
  body_html = _rewrite_media_urls_for_export(_sanitize_export_html(entry.text or ""), request)
  latest_dt = timezone.localtime(entry.updated_at or entry.date_added)
  date_str = latest_dt.strftime("%Y-%m-%d %H:%M")
  html_doc = _build_export_html(title, date_str, body_html)

  fmt = (fmt or "").lower()
  if fmt in ("doc", "word"):
    response = HttpResponse(html_doc, content_type="application/msword; charset=utf-8")
    filename = f"{slugify(title) or 'entry'}.doc"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response

  if fmt == "pdf":
    try:
      pdf_bytes = _render_html_pdf(html_doc)
      response = HttpResponse(pdf_bytes, content_type="application/pdf")
      filename = f"{slugify(title) or 'entry'}.pdf"
      response["Content-Disposition"] = f'attachment; filename="{filename}"'
      return response
    except Exception as exc:
      return _export_dependency_error(str(exc))

  if fmt in ("jpg", "jpeg", "png"):
    try:
      image_bytes, content_type, ext = _render_html_image(html_doc, fmt)
    except Exception as exc:
      return _export_dependency_error(str(exc))

    response = HttpResponse(image_bytes, content_type=content_type)
    filename = f"{slugify(title) or 'entry'}.{ext}"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response

  raise Http404


@login_required
@require_POST
def api_upload_entry_media(request):
  media_file = request.FILES.get("file")
  media_type = (request.POST.get("type") or "image").lower()
  if media_type not in ("image", "video"):
    media_type = "image"

  if not media_file:
    return JsonResponse({"error": "未接收到上传文件。"}, status=400)

  ext = os.path.splitext(media_file.name or "")[1].lower()
  allowed = {
    "image": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"},
    "video": {".mp4", ".webm", ".ogg", ".mov"},
  }
  size_limit = 12 * 1024 * 1024 if media_type == "image" else 120 * 1024 * 1024

  if ext not in allowed[media_type]:
    return JsonResponse({"error": "文件类型不支持。"}, status=400)
  if media_file.size > size_limit:
    return JsonResponse({"error": "文件过大，请压缩后重试。"}, status=400)

  now = timezone.localtime()
  folder = f"entry_uploads/{media_type}/{now.strftime('%Y/%m')}"
  filename = f"{uuid4().hex}{ext}"
  saved_path = default_storage.save(f"{folder}/{filename}", media_file)
  file_url = default_storage.url(saved_path)
  return JsonResponse({"url": file_url})

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
