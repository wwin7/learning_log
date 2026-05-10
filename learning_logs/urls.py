"""Defines URL patterns for learning_logs."""

from django.urls import path

from . import views

app_name = 'learning_logs'
urlpatterns = [
    path('', views.index, name='index'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('checkin/', views.checkin, name='checkin'),
    path('pomodoro/', views.pomodoro, name='pomodoro'),

    path('topics/', views.topics, name='topics'),
    path('topics/<int:topic_id>/', views.topic, name='topic'),
    path('new_topic/', views.new_topic, name='new_topic'),
    path('edit_topic/<int:topic_id>/', views.edit_topic, name='edit_topic'),
    path('delete_topic/<int:topic_id>/', views.delete_topic, name='delete_topic'),

    path('new_entry/<int:topic_id>/', views.new_entry, name='new_entry'),
    path('edit_entry/<int:entry_id>/', views.edit_entry, name='edit_entry'),
    path('delete_entry/<int:entry_id>/', views.delete_entry, name='delete_entry'),
    path('toggle_pin/<int:entry_id>/', views.toggle_pin_entry, name='toggle_pin_entry'),

    path('recycle-bin/', views.recycle_bin, name='recycle_bin'),
    path('restore_entry/<int:entry_id>/', views.restore_entry, name='restore_entry'),
    path('search/', views.global_search, name='global_search'),
    path('export/<int:entry_id>/<str:fmt>/', views.export_entry, name='export_entry'),

    path('api/checkin-stats/', views.api_checkin_stats, name='api_checkin_stats'),
    path('api/note-stats/', views.api_note_stats, name='api_note_stats'),
    path('api/reorder-topics/', views.api_reorder_topics, name='api_reorder_topics'),
    path('api/upload-entry-media/', views.api_upload_entry_media, name='api_upload_entry_media'),
]
