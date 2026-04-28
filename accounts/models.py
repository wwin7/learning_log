from django.contrib.auth.models import User
from django.db import models


class UserProfile(models.Model):
	user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
	avatar = models.ImageField(upload_to="avatars/", blank=True, null=True, verbose_name="头像")
	weekly_target = models.PositiveIntegerField(default=10, verbose_name="每周目标笔记数")
	signature = models.CharField(max_length=56, blank=True, verbose_name="个性签名")

	def __str__(self):
		return f"{self.user.username} profile"

	@property
	def avatar_url(self):
		if self.avatar:
			return self.avatar.url
		return f"https://ui-avatars.com/api/?name={self.user.username}&background=1f7ae0&color=fff&rounded=true"
