"""Defines URL patterns for accounts."""

from django.urls import path, include

from . import views

app_name = 'accounts'  # 命名空间，用于反向解析
urlpatterns = [
    # 包含Django默认的认证路由
    path('', include('django.contrib.auth.urls')),
    # Registration page.
    path('register/', views.register, name='register'),
]