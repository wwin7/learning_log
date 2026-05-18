from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Entry, Topic


class GlobalSearchTagTests(TestCase):
  def setUp(self):
    self.user = User.objects.create_user(username="tester", password="pwd12345")
    self.client.login(username="tester", password="pwd12345")

  def test_global_search_matches_topic_tags(self):
    topic = Topic.objects.create(
      text="后端学习",
      tags="django, python",
      owner=self.user,
    )
    Entry.objects.create(topic=topic, text="今天记录了 ORM 的基础用法。", tags="note")

    response = self.client.get(reverse("learning_logs:global_search"), {"q": "django"})

    self.assertEqual(response.status_code, 200)
    self.assertIn(topic, response.context["topic_results"])

  def test_global_search_matches_entry_via_topic_tags(self):
    topic = Topic.objects.create(
      text="框架速记",
      tags="flask, web",
      owner=self.user,
    )
    entry = Entry.objects.create(topic=topic, text="只写了基础内容。", tags="basics")

    response = self.client.get(reverse("learning_logs:global_search"), {"q": "flask"})

    self.assertEqual(response.status_code, 200)
    self.assertIn(entry, response.context["entry_results"])
