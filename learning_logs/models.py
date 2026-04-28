from datetime import timedelta

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class Topic(models.Model):
    """用户学习分类。"""

    text = models.CharField(max_length=200, verbose_name="分类名称")
    tags = models.CharField(max_length=255, blank=True, verbose_name="分类标签")
    category_color = models.CharField(max_length=7, default="#3B82F6", verbose_name="分类颜色")
    sort_order = models.PositiveIntegerField(default=0, verbose_name="排序值")
    date_added = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="topics")

    class Meta:
        ordering = ["sort_order", "-updated_at"]

    def __str__(self):
        return self.text


class Entry(models.Model):
    """某个分类下的学习笔记。"""

    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name="entries")
    text = models.TextField(verbose_name="笔记内容")
    tags = models.CharField(max_length=255, blank=True, verbose_name="笔记标签")
    is_pinned = models.BooleanField(default=False, verbose_name="是否置顶")
    pinned_at = models.DateTimeField(null=True, blank=True, verbose_name="置顶时间")
    is_deleted = models.BooleanField(default=False, verbose_name="是否已删除")
    deleted_at = models.DateTimeField(null=True, blank=True, verbose_name="删除时间")
    date_added = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name_plural = "entries"
        ordering = ["-is_pinned", "-pinned_at", "-date_added"]

    def __str__(self):
        return f"{self.text[:50]}..."

    def soft_delete(self):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_deleted", "deleted_at", "updated_at"])

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=["is_deleted", "deleted_at", "updated_at"])

    def toggle_pin(self):
        self.is_pinned = not self.is_pinned
        self.pinned_at = timezone.now() if self.is_pinned else None
        self.save(update_fields=["is_pinned", "pinned_at", "updated_at"])


class DailyCheckIn(models.Model):
    """每日打卡记录，一个用户每天只能打卡一次。"""

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="daily_checkins")
    checkin_date = models.DateField(verbose_name="打卡日期")
    note = models.CharField(max_length=255, blank=True, verbose_name="打卡备注")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="打卡时间")

    class Meta:
        ordering = ["-checkin_date", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "checkin_date"], name="unique_owner_daily_checkin"),
        ]

    def __str__(self):
        return f"{self.owner.username} - {self.checkin_date}"

    @classmethod
    def current_streak(cls, user):
        """计算连续打卡天数。"""
        dates = list(
            cls.objects.filter(owner=user)
            .order_by("-checkin_date")
            .values_list("checkin_date", flat=True)
        )
        if not dates:
            return 0

        today = timezone.localdate()
        expected = today
        streak = 0

        # 如果今天未打卡，但昨天打卡了，连续天数从昨天开始计算。
        if dates[0] != today:
            if dates[0] != today - timedelta(days=1):
                return 0
            expected = today - timedelta(days=1)

        date_set = set(dates)
        while expected in date_set:
            streak += 1
            expected -= timedelta(days=1)
        return streak

    @classmethod
    def badge_name(cls, streak):
        return f"🎖 你已经坚持{streak}天了，继续保持哟！"
